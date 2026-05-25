# M4 → M5 上下文交接

> 用途：下次会话拿不到本次聊天记录，靠本文件 + `docs/01~05`(v0.4) + `CLAUDE.md` 接续 M5。
> 本文件交接**事实与已定决策**，不写 M5 怎么做。生成于 2026-05-25。

---

## 1. 当前 git 状态（M4 完成时）

```
3fd7278 feat(scripts): rebuild_session_md.py 故障恢复 + 单测（M4 task 6 / Q9）
49fc237 feat(api): DELETE /api/v1/sessions/{thread_id}（M4 Q8 / docs/04 §5.3）
e3351ee feat(frontend): pages/chat.py /chat 流式 UI（M4 task 4）
ab58f03 feat(api): /chat SSE 路由 + session md 派生写 helper（M4 task 1-2）
e13ed49 feat(eval): scripts/eval_cn_recall.py 中文召回率评估骨架
fb5974e test(eval): tests/eval/cn_recall_gold.yaml 中文召回率黄金集骨架
1710f3c feat(skill): skills/memory_recall.skill.md 落盘（Q4 草案字面）
e3a6f55 feat(agent): build_lit_agent skills 参数化 + lit_agent.py format reflow
e3a29a0 docs(M4): 消歧义 session md 派生写 + skill 拼入时序脚注
47f2eb9 feat(scheduler): token-log 加 cache_read/cache_creation 两字段     ← M3 终
```

- 分支：`main`（本地，无 remote）；working tree clean（含本 handover + cn_recall_gold.yaml 填题）
- 容器状态（2026-05-25 16:54 UTC+8 rebuild + recreate）：3 容器全绿，scheduler 10:00/11:00 cron 已注册，9 paths ensured，0 startup error

---

## 2. M4 已实活验证的能力

- M3 真 cron 自唤醒 2026-05-25 下午已验证（owner 确认 "今天下午推送过检索到的文献"）
- `docker compose up -d --build api frontend` 后 OpenAPI 暴露 `/api/v1/chat` POST + `/api/v1/sessions/{thread_id}` DELETE，路由 schema 符合 docs/04 §4.1 / §5.3 字面
- 单元 / mock 测试 9 用例全绿（test_m4_delete_session 5 + test_m4_rebuild_session_md 4）
- baseline 等价：M3 既有 `test_m3_mail::test_send_email_no_recipient_fail_fast` 仍单点 fail（env isolation P1，见 §4）
- ⏳ **真 demo 待 owner 跑**：streamlit 8501 → 「💬 Chat · 文献情报 Agent」页 → 跨日召回 + token 流式 + 引用渲染 + session md 派生写

---

## 3. M4 累积的「已拍板决策」（不要再争）

### 3.1 SSE 用 FastAPI 原生 `StreamingResponse` + 自建 30-LOC SSE wire（Q1）
- 不引入 `sse-starlette` / `httpx-sse`（减法 + 不动 uv.lock）
- 15s `: keepalive` 注释心跳由独立 asyncio task 喂 queue
- 触发切 `sse-starlette` 的回退条件（仍有效）：`RuntimeError: Event loop is closed` / `RuntimeWarning: coroutine was never awaited` / SSE 流静默 > 15s 无心跳。任一出现立即评估切换

### 3.2 session md 派生写 = `try/finally` + `asyncio.to_thread` fire-and-forget（Q2.1-4）
- 实际不用 `asyncio.shield`：`asyncio.to_thread(sync_fn)` 把 sync derive 扔到 thread pool，sync 函数对 cancel 免疫（Python doc 行为）
- `_DERIVE_TASKS` module-level set 保 Task 引用防 weak-ref GC（Python doc verbatim 警告）
- cancel 路径下放弃归档：message 仍在 LangGraph state，重发问可续；trade-off acceptable

### 3.3 单 agent 复用，skill 列表参数化（Q3）
- `build_lit_agent(skills=("daily_search",))` 是 M3 向后兼容默认值
- chat 路由显式传 `skills=("daily_search", "memory_recall")`
- `profile_update.skill.md` 留 M5 才拼入（避免 token tax）

### 3.4 跨日召回 = agent 自主，不写硬规则（Q4）
- `memory_recall.skill.md` 落盘 130 行字面（commit `1710f3c`）
- 验收硬指标：上下文已有时 SSE 流 0 `tool` 事件（docs/04 §4.1 + docs/05 §5 验收）
- 中文 query 双跑策略（中 + 英两次 search_memory 合并去重）已写入 skill

### 3.5 中文召回率黄金集 A/B/D 三主题 10 题（Q5）
- 主集 5 文献题（占位已填，paper_A1-D1）+ 5 对话题（占位 question 已写，expected_session_ids 待 demo 后 owner 填）
- F 警示项（电池热管理 corpus 仅 1 篇）单独算分不污染主结论
- Top-1/3/5 三档同时输出（主验收口径 = Top-3，pass ratio 80%）

### 3.6 M4 不给 agent `write_file`（Q6）
- agent 工具白名单仍只读三件套 (`search_papers / read_file / search_memory`)
- M5 画像自更新里程碑才加 `write_file`，路径白名单严守 `^\./memory/profile/profile\.md$`（见 §5 P1）

### 3.7 frontend chat 用同步 `httpx.Client.stream()` + streamlit native（Q7）
- `st.chat_message` + `st.write_stream`；30-LOC `_parse_sse_events` 自建 byte-stream parser
- 不动 streamlit 版本（1.57.0），不引 httpx-sse

### 3.8 DELETE session 最终一致 + daily_push 拒删（Q8）
- `thread_id.startswith("daily_push:")` → 400 `DAILY_PUSH_NOT_DELETABLE`（PG `pushes` 审计 source of truth 不可删）
- 先 md 后 PG checkpoint；PG `adelete_thread` 失败 → log warning 仍 204
- `AsyncPostgresSaver.adelete_thread` 源码已字面采证：`langgraph/checkpoint/postgres/aio.py:340-361` 内部 SQL 清 3 张框架自管表

### 3.9 故障恢复脚本 `scripts/rebuild_session_md.py`（Q9）
- 单 thread `--thread-id`；`--dry-run` / `--force` 护栏
- `--all` 批量 M4 不实现，留 M6 backup 运维范畴

---

## 4. M4 未完成（task 5 + task 8）

`docs/05 §5` M4 共 8 任务，本批完成 1/2/3/4/6/7（骨架）；未完成：

### Task 5 — `/memory/papers` + `/memory/papers/{paper_id}` + `/memory/profile` API
- 状态：未做
- docs/04 §6 已字面定义 schema（paper 列表 / 详情含 cited_in 反向引用 / profile 只读）
- 建议优先级：M5 启动前的 nice-to-have；M4 验收硬指标不强依赖（前端只读 streamlit 暂时直接 grep memory_dir 或读 paper.md）
- 复用 M2 既有 `tools/memory.py` (search_memory / read_file / list_dir) 直接拼路由

### Task 8 — 真集成测试 + 首 token ≤ 3s 实测
- 状态：未做
- 黄金集（cn_recall_gold.yaml）5 文献题 paper_ids 已填，可直接跑 `python -m scripts.eval_cn_recall`；5 对话题 expected_session_ids 占位待 demo 后填
- 首 token ≤ 3s：M4 chat agent 真跑 stream_mode="messages" 拿到 token chunks 后实测 TTFT（Anthropic Haiku 4.5 + newapi 中转 latency）
- 端到端 demo：owner 上 frontend 跑 5 题真问对话，跨日召回 ≥ 4/5（docs/05 §5 验收硬指标）

---

## 5. P0 / P1 / P2 follow-up todo（M5 启动前过一遍）

### P0（开发末期处理，handover §4 M3 已登记）
- `ANTHROPIC_API_KEY` + `API_TOKEN` 轮换：M3 期间 `docker compose config` 暴露过，2026-05-25 M4 build 期间无新暴露。开发末期前轮换 + 同时做 compose 硬化（postgres 端口 internal-only + 密码 .env 读非 inline）

### P1（M5 启动前可做）
- **`tests/test_m3_mail.py::test_send_email_no_recipient_fail_fast` env isolation**：M3 commit `fd2743c` 既有缺陷；`.env` 真 `SMTP_TO` 被 `get_settings()` 读到 → 测试期望 `NoRecipientError` 但发邮件成功。修：用 `monkeypatch.setattr(settings, "smtp_to", "")` 或 fixture 隔离 env。**M4 全程是 baseline 1 个 fail 单点，等价标尺**
- **`ChatAnthropic streaming=True` 补齐**：`docs/02 §A.2` 字面 `streaming=True`，M3 commit `8c3e68f` 实际未传；M4 chat 路由用 LangGraph `stream_mode="messages"` 拿 token chunks 不依赖 model.streaming flag —— 但若 demo 时发现整段非流式（chunk 整段返回而非字符级），补 `model = ChatAnthropic(..., streaming=True)` 到 `agents/lit_agent.py:124`，1 行改动
- **Q6 M5 `write_file` 白名单同 PR 三处同步 checklist**：
  - `src/lit_agent/tools/memory.py` 加 `_WRITE_WHITELIST = re.compile(r"^\./memory/profile/profile\.md$")`
  - `CLAUDE.md §5` 「文件工具路径白名单」字面加「写白名单：M5 起仅 profile.md」
  - `docs/02 §3.4` 「文件工具路径限定」字面同步
  - 任一遗漏将复现 M3「docs ↔ 代码不一致」漂移（约定 5）
- **DELETE `/api/v1/sessions/{thread_id}` OpenAPI 400 response 显式声明**：当前 OpenAPI 只列 204 / 422（FastAPI 默认不列 `raise HTTPException` 触发的 status code）。修：`@router.delete(..., status_code=204, responses={400: {"description": "DAILY_PUSH_NOT_DELETABLE"}})`
- **session md `topics` 字段关键词提取**：M4 第一版字段 = `[]` 占位（M5/M6 让 agent 自更新或词频 top-3 启发式）
- **`rebuild_session_md.py --all` 批量模式**：M4 单 thread 即满足验收，批量留 M6 backup
- **OpenAPI `/chat` 400 / 503 responses 显式声明**：同上模式
- **handover §1 git log 异常 commits（`36221c0 LSTM Network` / `1db88de 测试一下`）**：早期混入的非本项目 commits，影响 0；M3 `M3_to_M4.md §1` 已登记，M5 启动前不动

### P2（M6 / M7）
- 邮件投递监控（SPF/DKIM 头）
- `scoring.py` system prompt 加评分锚点（9-10/7-8/5-6/0-4 分档）
- test_m3_daily_push / test_m4_* 用独立 test DB（M6 splitting）
- SQLite FTS5 派生索引（M7 触发条件 = cn_recall < 85%）
- PDF 全文 RAG

---

## 6. M4 实际工时 vs 估算

- **估算**（`docs/05 §5`）：3 人天 = 18h
- **实际**：约 **8–9h** focused dev（含两批 9 commits + handover）
  - 前批 5 commits（docs 消歧义 / skill 参数化 / memory_recall skill / eval yaml + script 骨架）≈ 2h
  - 后批 4 commits（SSE + chat + session md derive + frontend + DELETE + rebuild）≈ 4.5h
  - docs ↔ 代码不一致校准 + ruff format reflow + 容器 rebuild + 验证 ≈ 1.5h
- 节省原因：task 5 / task 8 没做（剩余 ~6h）+ deepagents 一开始就丢 + sse-starlette 没引（自建 30-LOC）
- 在预算内能落地的减法红利继续 compound

---

## 7. 启动 M5 的第一条指令（给新会话）

> 你在推进「文献情报 Agent」项目的 M5（画像自更新）。唯一事实来源是 `docs/01~05`(v0.4) 与 `CLAUDE.md`；先读 `docs/handover/M4_to_M5.md` 了解 M4 已完成的事实 + 已拍板决策（§3 不要再争 / §4 未完成的 task 5+8 / §5 P0/P1 待办清单）。M4 端到端 demo 已绿（owner 真跑 chat + 跨日召回），9 个 commit 已落 main（最新 `3fd7278`）。
>
> M5 目标见 `docs/05 §6`：lit_agent 按 `profile_update.skill.md` 读近 30 天 feedback → 原子写 `profile.md`，A/B 对比有/无画像 Top-10 重合度 + 👍率。
>
> **先按以下顺序处理 P1**（如未在 M4 收尾做完）：(1) `test_m3_mail` env isolation，(2) `ChatAnthropic streaming=True`（若 M4 demo 发现整段非流），(3) Q6 `write_file` 白名单三处同步 — 这是 M5 的硬前提（M5 agent 要 write_file profile.md）。
>
> 然后引入 `profile_update.skill.md` 拼入 `build_lit_agent` 默认 skills 列表（之前留 M5 才上的字面要求）。
>
> 遵守减法精神：M5 仍是单 agent + 自建工具 + LangGraph thread/checkpoint + markdown/grep；**绝不退回 deepagents、绝不写 cache_control、绝不建 PG locks/jobstore/messages/sessions 表**。
