# BartenderAI

BartenderAI 是一套可本地运行的 AI 调酒工作台。项目使用 Vue 3、FastAPI、LangGraph、Milvus、BGE-M3 与 BGE-Reranker，覆盖正式账号体系、441 款配方检索、库存匹配、AI 创作、配方实验、场景酒单、图片识别和管理控制台。

外部模型、Milvus、联网搜索、视觉模型和 SMTP 都是可选增强能力。未配置时，账号、配方目录、库存、收藏、规则引擎、场景玩法和本地 BM25 检索仍可使用，前端会展示当前能力等级。

对话中的 `model` 能力只在真实模型请求成功后标记为可用。系统会把同一条真实任务按
`LLM_PROVIDER_PRIORITY` 在本地模型、DeepSeek 和 Qwen 之间切换；不会用独立的 `ping`
冒充任务成功，也不会把本地规则解析包装成多 Agent 推理。连接、鉴权或余额错误会触发
短时熔断，避免多个 Agent 重复等待同一个故障供应商。

本地模型可通过任意 OpenAI-compatible 服务接入。例如 Ollama：

```powershell
ollama serve
ollama pull qwen3:8b
```

然后在 `backend/.env` 设置：

```env
LOCAL_LLM_BASE_URL=http://127.0.0.1:11434/v1
LOCAL_LLM_MODEL=qwen3:8b
LLM_PROVIDER_PRIORITY=deepseek,qwen,local
```

## 在线演示

[打开 BartenderAI Demo](https://wangpingping009-web.github.io/bartenderai/)

在线演示开放调酒台、配方探索、创作室、实验室、酒柜、场景酒单、拍照识方、个人中心和控制台。调酒台与创作室使用浏览器内的规则和 8 款示例配方。拍照识方提供本地照片预览与固定结果样例，控制台提供只读界面。酒柜、会话、试调档案、收藏和偏好保存在当前浏览器。完整配方库、实时模型、账号与后台运维可通过下方的本地启动方式体验。

`main` 分支更新后，GitHub Actions 会重新构建并发布演示。首次部署时，在仓库的 **Settings → Pages** 中将 **Source** 设为 **GitHub Actions**。本地可在 `frontend` 目录执行 `npm ci`、`npm run build:demo` 和 `npm run preview` 预览演示。

## 产品模块

- AI 调酒台：多会话、流式回答、停止生成、结构化引用和 Agent 轨迹。
- 配方探索：441 款配方，支持名称、材料、类别、基酒、风味、酒精度和库存筛选。
- AI 创作室与配方实验室：人格化生成、规则质检、材料替代、经典解构和零酒改造。
- 我的酒柜：库存维护、可调配方、缺失材料与替代建议。
- 场景酒单：每日一酒、主题酒单、情境推荐、挑战、晚宴换算和成长徽章。
- 个人中心：收藏、口味画像、喝后评分、改密、数据导出和账号注销。
- 拍照识方：JPEG/PNG/WebP，最大 8 MB；临时文件在请求结束后删除。
- AI 控制台：管理员查看用量、审计、Prompt、知识版本、评测与索引任务。

## 技术结构

```text
frontend/                 Vue 3 + Router + Pinia + Vitest + Playwright
backend/app/api/          FastAPI 路由、认证、统一错误和请求 ID
backend/app/graph/        LangGraph 自适应 Agent 编排
backend/app/rag/          别名扩展、BM25/向量/混合检索、重排与评测
backend/app/db/           SQLAlchemy 2 模型和兼容仓储层
backend/alembic/          数据库迁移
backend/data/knowledge/   带版本的知识卡
```

Agent 根据问题复杂度走快速回答、知识检索或并行专家路径，审校最多进行一次定向回炉。检索无命中时返回空结果，不会用数据集前几条伪装命中；Milvus 不可用时降级到真正的本地 BM25。

## 本地启动

要求 Python 3.11+ 和 Node.js 20+。先复制根目录 `.env.example` 或 `backend/.env.example` 为 `.env`，至少设置开发密钥；生产环境必须使用独立强密钥并配置严格 CORS。

```powershell
cd D:\xunlei\BartenderAI\backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload
```

另开终端：

```powershell
cd D:\xunlei\BartenderAI\frontend
npm install
npm run dev
```

前端地址为 `http://127.0.0.1:5173`，API 文档为 `http://127.0.0.1:8000/docs`，能力状态为 `http://127.0.0.1:8000/api/capabilities`。

开发邮件推荐使用 Compose 中的 Mailpit，Web UI 为 `http://127.0.0.1:8025`。Mailpit 未运行时，开发环境的注册和找回密码页面会提供一次性本地链接，保证仍可完成流程；生产环境绝不会返回令牌链接。生产邮件通过 `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD` 和 `SMTP_FROM` 配置。

## Docker Compose

```powershell
docker compose --profile app up -d --build
```

该配置包含 Milvus、etcd、MinIO、Mailpit、后端和前端。应用数据和模型使用挂载卷保留。当前机器若未安装 Docker，可由 CI 的手动 Compose smoke job 验证。

## RAG 数据与评测

知识入库和固定评测集：

```powershell
cd backend
python scripts/ingest_knowledge.py
python scripts/benchmark_retrieval.py --modes bm25
```

评测集包含 90 条配方、材料、别名、技法和无答案样例，可比较 `vector`、`bm25`、`hybrid` 与 `rerank`。本地 BM25 基线为 Recall@5 `0.9875`、MRR@5 `0.9479`、nDCG@5 `0.9582`、无答案精度 `1.0`，p95 `3.3 ms`。Dense/Hybrid/Reranker 指标需在 Milvus 和模型可用的环境重新生成，不能用本地降级结果代替。

## 测试

```powershell
cd backend
pytest -m "not e2e"

cd ..\frontend
npm test
npm run build
npm run test:e2e
```

Playwright 覆盖 360、768 和 1440 像素视口，包括登录、强制刷新后保持登录、配方加载和移动端完整导航。CI 运行迁移、确定性后端测试、前端测试和生产构建；真实模型、Milvus 和 RAGAS 留在手动或定时评测。

## 安全约束

- 密码使用 Argon2id；Access Token 仅保存在内存，Refresh Token 使用 HttpOnly SameSite Cookie 并轮换。
- 普通用户与管理员权限隔离，不允许通过 URL 用户名读取他人数据。
- 对话与画像敏感字段加密，上传限制类型和体积，认证与 AI 接口均有限流。
- API 错误统一为 `{code, message, details, request_id}`，列表统一为 `{items, page, page_size, total}`。
- SSE 事件统一为 `status`、`agent_event`、`partial`、`reference`、`done` 和 `error`。

完整产品范围见 [REQUIREMENTS.md](REQUIREMENTS.md)。
