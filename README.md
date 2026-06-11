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

> **状态：初步开发完成，正在进行后续优化。** 核心链路 M1–M4 已全部跑通，当前聚焦稳定性、可观测与画像自更新等优化项（M5 / M6，P1）。

| ID | 目标 | 状态 |
|----|------|------|
| **M1** | 地基与最小链路（compose up → Streamlit + /status） | ✅ 完成 |
| **M2** | `search_papers` 工具（搜+去重+评分+落盘）+ 文件记忆 | ✅ 完成 |
| **M3** | 每日推送闭环（10:00 触发 → 调一次 search_papers → 发邮件 + 站内） | ✅ 完成 |
| **M4** | 对话 / 跨日召回 / session md 派生归档 | ✅ 完成 |
| M5 | 画像自更新 | 🚧 优化中（P1） |
| M6 | 鲁棒 / 可观测 / 备份 | 🚧 优化中（P1） |

详见 [docs/05_roadmap.md](docs/05_roadmap.md)。
