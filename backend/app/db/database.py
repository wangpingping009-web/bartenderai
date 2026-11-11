# -*- coding: utf-8 -*-
"""SQLAlchemy-backed database access with a sqlite-compatible adapter."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine

from app.core.config import settings
from app.db.models import Base

_engines: dict[str, Engine] = {}
_engine_lock = Lock()


def database_url() -> str:
    if settings.DATABASE_URL:
        return settings.DATABASE_URL
    path = Path(settings.DATABASE_PATH).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def get_engine() -> Engine:
    url = database_url()
    with _engine_lock:
        engine = _engines.get(url)
        if engine is None:
            engine = create_engine(url, future=True, pool_pre_ping=True)
            if url.startswith("sqlite"):
                @event.listens_for(engine, "connect")
                def _sqlite_pragmas(dbapi_connection, _):
                    dbapi_connection.execute("PRAGMA foreign_keys = ON")
                    dbapi_connection.execute("PRAGMA journal_mode = WAL")
                    dbapi_connection.execute("PRAGMA busy_timeout = 5000")
            _engines[url] = engine
        return engine


class _Result:
    def __init__(self, result):
        self._result = result
        self.rowcount = result.rowcount
        self.lastrowid = getattr(result, "lastrowid", None)

    def fetchone(self):
        return self._result.mappings().fetchone()

    def fetchall(self):
        return list(self._result.mappings().fetchall())

    def __iter__(self):
        return iter(self._result.mappings())


class _EmptyResult:
    rowcount = 0
    lastrowid = None

    @staticmethod
    def fetchone():
        return None

    @staticmethod
    def fetchall():
        return []

    def __iter__(self):
        return iter(())


class CompatConnection:
    """Preserve repository calls while SQLAlchemy owns connections/transactions."""
    def __init__(self, conn: Connection):
        self._conn = conn

    def execute(self, sql: str, params=()):
        return _Result(self._conn.exec_driver_sql(sql, params))

    def executemany(self, sql: str, params):
        values = list(params)
        if not values:
            return _EmptyResult()
        return _Result(self._conn.exec_driver_sql(sql, values))


@contextmanager
def db():
    with get_engine().begin() as conn:
        yield CompatConnection(conn)


def init_db() -> None:
    # Upgrade prototype tables before metadata inspects them. Existing data stays readable.
    _upgrade_legacy_users()
    Base.metadata.create_all(get_engine())


def _column_names(table: str) -> set[str]:
    with get_engine().connect() as conn:
        exists = conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            return set()
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").mappings().all()
    return {r["name"] for r in rows}


def _upgrade_legacy_users() -> None:
    """Idempotently add auth columns to pre-SQLAlchemy prototype databases."""
    if not database_url().startswith("sqlite"):
        return
    columns = _column_names("users")
    if not columns:
        return
    additions = {
        "email": "TEXT",
        "password_hash": "TEXT",
        "display_name": "TEXT NOT NULL DEFAULT ''",
        "role": "TEXT NOT NULL DEFAULT 'user'",
        "is_verified": "INTEGER NOT NULL DEFAULT 0",
        "is_active": "INTEGER NOT NULL DEFAULT 1",
    }
    with get_engine().begin() as conn:
        for name, ddl in additions.items():
            if name not in columns:
                conn.exec_driver_sql(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
