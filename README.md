# 文献情报 Agent

一个跑在本机 / NAS 上的**个人文献情报员**（单用户，锂电池 / 固态电解质 / 电池热管理方向）。
每天 10:00 一个 `lit_agent` 被叫醒，生成检索词、调一次 `search_papers` 拿到已去重已评分的精选，
写邮件并在站内对话呈现；推送过的文献以 markdown 永久落 `./memory/`，可随时追问、重搜、调偏好。

> 设计哲学：**结构化、确定性的活交给代码和成熟框架；模糊判断和对话交给 agent；能不加的组件就不加。**
> 详见 [CLAUDE.md](CLAUDE.md) 与 [docs/](docs/)（01~05，v0.4，唯一事实来源）。

## 适用 / 失效边界（务必先看）

- ✅ 适用：**正在更新的宽泛领域**（每天至少 3–5 篇新文），如锂电池正负极材料、固态电解质、电池热管理。
- ❌ 失效：极窄子方向（一个月才 1 篇）、完全静态的历史领域、中文文献（暂不支持）。

详见 [docs/01_PRD.md §8](docs/01_PRD.md)。

## 快速开始

```bash
cp .env.example .env          # 填 API_TOKEN / ANTHROPIC_API_KEY 等
docker compose up -d          # 起 postgres / api / frontend
# 浏览器打开 http://localhost:8501 应显示 alive ✅
```

## 本地开发（容器外）

```bash
pip install uv                # 若未装 uv
uv sync                       # 按 uv.lock 安装依赖
uv run python scripts/init_memory.py
uv run alembic upgrade head   # 需本地 / 容器 postgres 可达
uv run uvicorn lit_agent.api.main:app --reload --port 8000
uv run streamlit run src/lit_agent/frontend/app.py --server.port 8501
```

## 质量门禁

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

## 里程碑进度

| ID | 目标 | 状态 |
|----|------|------|
| **M1** | 地基与最小链路（compose up → Streamlit + /status） | ✅ 进行中 |
| M2 | `search_papers` 工具 + 文件记忆 | 待办 |
| M3 | 每日推送闭环 | 待办 |
| M4 | 对话 / 跨日召回 / 派生归档 | 待办 |

详见 [docs/05_roadmap.md](docs/05_roadmap.md)。
