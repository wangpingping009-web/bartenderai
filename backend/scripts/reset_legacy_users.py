# -*- coding: utf-8 -*-
"""Reset anonymous prototype data after an external database backup was made."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.database import db, init_db


def main() -> None:
    init_db()
    with db() as conn:
        conn.execute("UPDATE prompt_versions SET created_by=NULL")
        conn.execute("UPDATE jobs SET created_by=NULL")
        for table in ("messages", "conversations", "feedback", "creations", "refresh_tokens",
                      "auth_tokens", "favorites", "inventory", "profiles", "user_badges",
                      "user_progress", "user_action_claims", "chat_history", "users"):
            conn.execute(f"DELETE FROM {table}")
    print("Legacy user data reset. Usage, evaluations and knowledge versions were preserved.")


if __name__ == "__main__":
    main()
