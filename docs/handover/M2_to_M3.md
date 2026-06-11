# M2 → M3 上下文交接

> 用途：明天的新会话拿不到今天的聊天记录，靠本文件 + 项目文件 + `docs/01~05` + `CLAUDE.md` 接续 M3。
> 本文件只交接**事实与已定决策**，不写 M3 怎么做（那是新会话的事）。生成于 2026-05-22。
> 本文件为临时交接资料，**不进版本历史**（不要 git commit）。

---

## 1. 当前 git 状态

```
$ git log --oneline -5
2c03f2c feat(M2): file-memory tools + fetch_once CLI + daily_search skill draft; fix paper.md frontmatter newline
4a6a896 feat(M2): search_papers tool with vendored fork + 4-source dedup/scoring
352b242 build(deps): 暴露 vendored paper_search_mcp + 仅装 3 个真依赖
8d3a17c chore(vendor): 引入 paper-search-mcp @d438222 (完整 fork, 非 submodule) + patches
7b0d006 M1: 地基与最小链路 (FastAPI + LangGraph checkpointer + PG 3表 + Streamlit)
```

- 分支：`main`（无远程，纯本地仓库，尚未 push 到任何 remote）。
- working tree：**干净**（`git status -sb` 仅显示 `## main`）。
- 唯一正式目录：`D:\paper-agent`（旧目录 `d:\1文献搜索agent2.0` 已弃用、待 owner 确认后删除）。

---

## 2. M1 + M2 已跑通的核心能力（有数据证据，非"理论可做"）

**M1（地基，已在真实 docker 栈验证）**
- `docker compose up` 起 3 容器（postgres / api / frontend），postgres healthy。
- `GET /health` → `{"status":"ok"}`；`GET /api/v1/status` 真 ping：postgres ok(~84ms)、memory_dir ok、anthropic ok（经 newapi 网关 `models.list`）、paper_search_mcp 标 degraded（M1 设计内）。
- 无 Token → 401 + RFC7807 `application/problem+json`。
- alembic 迁移 `0001_initial` 已应用；3 张表 + LangGraph 4 张 checkpoint 表已建（见 §3）；单用户 seed `id=1`。

**M2（检索工具，端到端实测）**
- `search_papers(queries, sort="date_desc", limit_per_query=20, dedup_against_memory=True, min_score=6.0)` 端到端跑通，单 query/limit=8 实测 **~20s（含 Haiku 评分）**。
- 4 源真实命中：arxiv / openalex / crossref / s2，单 query/limit=8 各返回 8 篇（raw=32）。
- 强制按发表日期降序：arxiv `sortBy=submittedDate` / crossref `sort=published&order=desc` / openalex `sort=publication_date:desc` / s2 `sort=publicationDate:desc`（经 patch 走 bulk 端点）。
- 三锚点去重（doi > arxiv_id > normalized_title）+ 历史 memory 去重：**RUN A** raw=32→deduped=32→selected=10 落盘；**RUN B**（同 query 再跑）raw=32→**deduped=22**→selected=7（已落盘的 10 篇被记忆去重剔除，不再重复）。
- Haiku 单次批量评分：`claude-haiku-4-5-20251001` 经 `ANTHROPIC_BASE_URL`（newapi）网关，tool_use + Pydantic `ScoreBatch` 校验，批 ≤60 偶分 + min_batch 15 保护；实测 `POST .../v1/messages 200`，scored=32。
- S2 限流器实测生效：隔离测试相邻间隔 1.103~1.114s（≥1.1）；`x-api-key` 经 header 正确发送、5 次连发未触发 429。
- 文件记忆工具：`search_memory`(grep 式) / `read_file` / `write_file`(原子) / `list_dir`，含路径白名单（memory 读写、skills 只读、防 `..` 穿越），单测覆盖。
- `paper.md` 按 `03_data_model §2.2` frontmatter 落盘，YAML 安全（含控制字符/换行清理）。
- 质量门禁：`ruff` / `mypy --strict`(22 files) / `pytest` **17 passed** 全绿。

> 已知质量观察（非 bug）：本次评分 10 篇全 8.0、且夹带 1 篇跑题（纳米孔测序）。原因＝`profile.md` 仍空占位 + arxiv `all:` 查询较宽，Haiku 无区分依据。靠后续画像 + 更精准检索词收敛，见 §5。

---

## 3. 当前项目结构快照

```
src/lit_agent/
├── __init__.py
├── api/        main.py  middleware.py(RFC7807+traceid)  routes/system.py(/health,/status)
├── core/       config.py(Settings)  deps.py(verify_token/get_db/checkpointer)  logging.py(structlog)
├── db/         base.py(async engine/session)  models.py(users/pushes/feedback)
├── frontend/   app.py(Streamlit 占位显示 /status)
└── tools/      schemas.py(Paper/ScoreBatch)  paper_md.py(渲染/去重索引/原子写)
                sources.py(4源抓取+RateLimiter+并发)  scoring.py(Haiku批量评分)
                search_papers.py(6步编排)  memory.py(search_memory/read/write/list)
scripts/        init_memory.py  fetch_once.py(M2 Demo 入口)
skills/         daily_search.skill.md(草稿)  memory_recall.skill.md(占位)  profile_update.skill.md(占位)
tests/          conftest.py  test_m1.py  test_vendor_import.py  test_memory.py   (17 passed)
docs/           01_PRD 02_architecture 03_data_model 04_api_design 05_roadmap (+v0.3/v0.4 提示词)
vendor/paper-search-mcp/   完整 fork(锁 commit d438222) + VENDOR.md + PATCHES.md
    paper_search_mcp/academic_platforms/  (25 源；我们只用 arxiv/semantic/crossref/openalex 4 个)
alembic/  alembic.ini  docker-compose.yml  Dockerfile  pyproject.toml  uv.lock  CLAUDE.md
```

**PostgreSQL 表（M1 实测存在）**：
- 我们的 3 张：`users` / `pushes` / `feedback`（见 `src/lit_agent/db/models.py` + 迁移 `0001_initial`）。
- LangGraph 自管 4 张：`checkpoints` / `checkpoint_blobs` / `checkpoint_writes` / `checkpoint_migrations`（由 `setup_checkpointer()` 启动期建，**我们不画不动**）。
- 注：以上在 M1 的运行容器里 `psql` 验证过；**当前 docker 栈是否仍在运行＝不确定**，M3 启动可能需重新 `docker compose up -d`。

---

## 4. 跨 M2 累积的"已拍板决策"（不要再争，每条附来源）

- **paper-search-mcp 接入方式**：fork vendored 进 `vendor/`，`search_papers` **直接 import 4 个 source 类，不跑 MCP 子进程**。来源：`docs/02 §A.2`、`vendor/paper-search-mcp/VENDOR.md`。
- **vendored 锁版本**：上游 `openags/paper-search-mcp` main commit `d438222`（2026-05-17）；本地 3 个 patch（S2 走 bulk 加 sort / OpenAlex 加 sort / pypdf 惰性导入），全部 `grep PATCH(lit-agent)` 可定位。来源：`vendor/.../PATCHES.md`。
- **依赖裁剪**：不 pip install vendored 包，用 hatch packages 暴露 `paper_search_mcp`，只装 `requests/feedparser/beautifulsoup4`，跳过 `fastmcp/mcp[cli]/pypdf/lxml/httpx[socks]`。来源：`pyproject.toml` 注释、`VENDOR.md`。
- **去重/评分在 `search_papers` 工具内由代码完成，agent 永不做 for 循环**。来源：`CLAUDE.md §2` 第 1 条。
- **强制 `sort="date_desc"`**（否则经典老论文反复被去重 → 0 篇产出）。来源：`docs/01 §8`、`search_papers.py` 入口校验。
- **LangGraph state/checkpoint 框架自管，不自建 `messages`/`locks`/`sessions` 表**。来源：`CLAUDE.md §2` 第 3 条。
- **PG 仅 3 表**（users/pushes/feedback）。来源：`docs/03 §1`。
- **`profile.md` / session md 写入用原子写（临时文件 + `os.replace`），不是分布式锁**。来源：`CLAUDE.md §2` 末、`paper_md.atomic_write`。
- **文件工具路径白名单**：`./memory/` 读写、`skills/` 只读，防越权读 `.env`。来源：`CLAUDE.md §5`、`tools/memory.py`。
- **S2 key**：`.env` 变量名 `SEMANTIC_SCHOLAR_API_KEY`（兼容别名 `S2_API_KEY`），**必填 fail-fast，不留无 key 双模式**；限流 1 req/s 累计 → 串行 RateLimiter 默认 `S2_MIN_INTERVAL_S=1.1`。来源：`.env.example`、`core/config.py`。
- **评分模型**：`claude-haiku-4-5-20251001`，经 `ANTHROPIC_BASE_URL`（newapi 网关 `https://newapi.tsingyuai.com`，base_url 不带 `/v1`）。来源：`core/config.py`、`tools/scoring.py`。
- **deepagents 推迟到 M3 才锁版本**，且 M3 用 uv 统一解析时**以 deepagents 为约束源**、langgraph 跟着回调 pin。来源：`CLAUDE.md §3`。
- **包管理 uv + uv.lock；Python 3.12；Postgres 17**。来源：`CLAUDE.md §3`。
- **⚠️ M3 必验（未决）**：newapi 网关是否透传 `cache_control: ephemeral` 并回报 `cache_read_tokens` —— 直接关系 PRD「≤$5/月」预算。来源：`CLAUDE.md §3` 注。

---

## 5. 累积 P1/P2 TODO（登记，**现在不做**）

- **P2** `scoring.py` system prompt 加"评分锚点"（如 9-10/7-8/5-6/0-4 分档），M3 上线观察评分趋同（本次全 8.0）后再决定。
- **P2** `profile.md` 仍是空占位 → M5 启动前先手填基础画像做冷启动锚点；在那之前评分缺区分依据。
- **P2** `docker-compose.yml` postgres 端口改 `127.0.0.1:5432:5432`（internal-only）+ 密码从 `.env` 读取（当前 `5432:5432` + 弱密码 `lit/lit`）。M6 部署阶段。来源：`CLAUDE.md §6` M6 行 TODO。
- **P2** `scoring.py` 的 `client.messages.create(...)` 上有 `# type: ignore[call-overload]`（动态 tool input_schema mypy 无法重载匹配）；M3 看 anthropic SDK 新版是否能去掉。
- **P1** 中文 query 在英文库召回率评估（< 85% 才考虑 SQLite FTS5 派生索引）。来源：`docs/05` M4/M7。
- **P2** 标题含化学式下标（如 `Na2.9Sb0.9W0.1S4`）从 S2/OpenAlex 取回时被拆成带空格的串；YAML 已安全，但 `normalized_title`/展示不完美，暂可接受。
- **环境提示（非代码）**：本机 Windows 跑 `pytest` 需 `--basetemp=.pytest_tmp`（系统临时目录权限报错）；测试中 `test_status_shape_with_auth` 会真连 newapi 触发一条 "access violation" 噪声但不影响结果（沙箱网络所致）。

---

## 6. M3 启动前需要 owner 拍板的事（只列问题，**答案留空**）

> 基于 `docs/05_roadmap.md` M3（每日推送闭环）。新会话开工前请 owner 逐条拍板。

1. DeepAgents 锁哪个具体版本？（5 月发的 0.6.x，M3 启动时需重新看最新 commit/稳定度；按已定"以 deepagents 为约束源"回调 langgraph pin）→ 答：______
2. 用 `create_deep_agent()` 还是降级手写 `StateGraph`？（取决于 deepagents 0.6.x 当前稳定度）→ 答：______
3. APScheduler 跑在哪：`AsyncIOScheduler` 内嵌 api(FastAPI) 进程，还是独立 worker 容器？→ 答：______
4. 10:00 触发如何把"系统消息"注入 agent（固定 `thread_id=daily_push:YYYY-MM-DD`）？具体机制？→ 答：______
5. 失败重试：10:00 失败 → 11:00 补跑，用 APScheduler misfire/第二个 job，还是别的？→ 答：______
6. `lit_agent` 的 system prompt 写在哪个文件/常量？`skills/daily_search.skill.md` 作为 system 注入还是 user message？怎么加载？→ 答：______
7. 邮件：用 `aiosmtplib` + Jinja2（之前登记的 M3 依赖）？SMTP 配置走现有扁平 `.env`（`SMTP_*`）即可，还是要嵌套 settings？→ 答：______
8. `pushes` 审计谁写：应用层钩子，还是 agent 工具？写入时机？→ 答：______
9. M3 的 agent 调用 Anthropic 用 `langchain-anthropic` 的 `ChatAnthropic`，base_url 同样指 newapi 网关？（与 `/status`、scoring 同一通道）→ 答：______
10. 收件人确认固定取 `.env` 的 `SMTP_TO`（当前为空，M3 前需填）？→ 答：______
11. 先验 §4 的「cache_control 透传」再写 M3，还是边写边验？→ 答：______

---

## 7. 启动 M3 的第一条指令（给新会话）

> 你在推进「文献情报 Agent」项目的 M3（每日推送闭环）。唯一事实来源是 `docs/01~05`(v0.4) 与 `CLAUDE.md`；先读 `docs/handover/M2_to_M3.md` 了解 M1/M2 已完成的事实与已拍板决策（尤其 §4 不要再争、§6 待 owner 拍板）。M1（地基）、M2（`search_papers` 工具 + 文件记忆）已完成并端到端验证、已 git 提交（最新 `2c03f2c`，分支 main 干净）。M3 目标见 `docs/05 §4`：APScheduler 10:00 用固定 `thread_id` 叫醒单个 `lit_agent` → 读 `skills/daily_search.skill.md` → 生成检索词 → **调一次** `search_papers` → 写邮件 + 站内 daily-push 会话 + 写 `pushes` 审计。**先按 §6 把待拍板问题问 owner，确认后再写代码**；引入 deepagents/langchain-anthropic/APScheduler/aiosmtplib 等新依赖前先报版本给 owner。遵守减法精神：结构化交代码、模糊判断交 agent、能不加组件就不加。
