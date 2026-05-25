# 文献情报 Agent · API 接口设计

> **文档版本**：v0.4　|　**依赖**：[01_PRD.md](./01_PRD.md) / [02_architecture.md](./02_architecture.md) / [03_data_model.md](./03_data_model.md)　|　**状态**：已对齐 2026-05-20 晚第二轮精简评审

> **v0.4 相对 v0.3 的变更**：
> 1. **接口与 `messages` 表解耦**：会话消息改从 **LangGraph state（按 `session_id` = `thread_id`）** 读取，不再读 PG `messages` 表（已删）。
> 2. **会话列表来自 session md 文件**：`/sessions` 列表扫 `./memory/sessions/` frontmatter，不依赖 PG。
> 3. **删除会话改为删 LangGraph thread + session md 文件**（不再级联删 PG messages）。
> 4. **`/feedback` 写 PG `feedback` 表**（+ 派生 `feedback/*.log`）；不再回写 paper.md。
> 5. **`/admin` 触发的 409 改为"LangGraph thread busy"**（不再 PG `locks`）。
> 6. 端点总数保持 **11 个**（语义解耦，非删接口）。
>
> 其余设计（`/chat` 统一入口、`/memory/*` 暴露文件目录、RFC7807、cursor 分页、SSE）沿用 v0.3。

---

## 目录 (TOC)

- [0. 总览与全局约定](#0-总览与全局约定)
- [1. 鉴权方案](#1-鉴权方案)
- [2. API 资源分组](#2-api-资源分组)
- [3. 系统](#3-系统)
- [4. 对话（统一入口）](#4-对话统一入口)
- [5. 会话](#5-会话)
- [6. 记忆（文件系统目录）](#6-记忆文件系统目录)
- [7. 反馈](#7-反馈)
- [8. 管理端（仅本机）](#8-管理端仅本机)
- [9. SSE 规约](#9-sse-规约)
- [10. OpenAPI / 自动文档](#10-openapi--自动文档)
- [11. 备选方案 & 取舍](#11-备选方案--取舍)

---

## 0. 总览与全局约定

### 0.1 设计原则

1. **一个对话入口**：所有"发消息"——无论首轮还是追问、无论问文献还是调偏好——都走 `POST /api/v1/chat`（SSE）。
2. **记忆即目录**：`/memory/*` 直接映射 `./memory/` 文件系统，不经 PG 检索。
3. **JSON-only**：除 SSE 流外，body 一律 `application/json; charset=utf-8`。
4. **错误统一**：RFC 7807 风格 `application/problem+json`。
5. **流式 first-class**：对话回答用 SSE。
6. **MVP 不做 GraphQL / WebSocket**。

### 0.2 URL / 版本 / 编码

| 项 | 值 |
|----|-----|
| Base URL | `http://localhost:8000` |
| API 前缀 | `/api/v1` |
| 健康检查 | `/health`（不带版本前缀） |
| Content-Type | `application/json; charset=utf-8` |
| 对外资源 ID | `session_id` 用 UUID；`paper_id` 用 `{source}-{external_id}` 业务码 |

### 0.3 通用请求头

| Header | 必需 | 说明 |
|--------|------|------|
| `Authorization` | ✓ | `Bearer <token>` |
| `Content-Type` | 写操作必需 | `application/json` |
| `Accept` | 可选 | SSE 端点需 `text/event-stream` |
| `X-Request-Id` | 可选 | 客户端追踪 ID，服务端回写 |

### 0.4 通用错误响应

```json
{
  "type": "about:blank",
  "title": "Validation Error",
  "status": 422,
  "code": "INVALID_SIGNAL_TYPE",
  "detail": "signal_type must be one of: liked, disliked, asked, skipped, impression",
  "trace_id": "8c6c1a3a-4a5d-4b9a-9b0e-2f6f1c8e5a91"
}
```

| HTTP | code | 含义 |
|------|------|------|
| 401 | `UNAUTHORIZED` | 缺失 / 非法 Token |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `CONFLICT` | 唯一约束 / 重入冲突 |
| 422 | `VALIDATION_ERROR` | 字段校验失败 |
| 429 | `RATE_LIMITED` | 触发限流 |
| 500 | `INTERNAL_ERROR` | 未捕获异常 |
| 503 | `SERVICE_UNAVAILABLE` | 依赖（Anthropic / DB）不可用 |

### 0.5 分页约定

列表接口统一 cursor + limit：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `limit` | int (1–100) | 20 | 单页条数 |
| `cursor` | string | null | 上次响应的 `next_cursor` |

```json
{ "items": [], "next_cursor": "eyJ...", "has_more": true, "limit": 20 }
```

### 0.6 时间与时区

- 所有 timestamp 一律 ISO 8601 + 时区偏移；服务端 UTC 存储，响应带时区。
- 日期字段（`run_date`）用 `YYYY-MM-DD`。

---

## 1. 鉴权方案

### 1.1 MVP：静态 Bearer Token

`.env` 预置 `API_TOKEN`，客户端每次带 `Authorization: Bearer <API_TOKEN>`。Streamlit 启动时从同一 `.env` 读取并自动注入，**用户无感**。

**豁免**：`GET /health`；`GET /docs` / `GET /openapi.json`（仅 `ENV=dev`）。

### 1.2 备选与升级

| 阶段 | 触发条件 | 方案 |
|------|---------|------|
| MVP | 单用户 | 静态 Bearer |
| P1 | 局域网多设备 | 静态 Bearer + Streamlit session_state 缓存 |
| P2 | 上云 / 多用户 | JWT 自签发 |

> 所有路由通过 `Depends(verify_token)`，未来切换鉴权只改这一 dependency。

---

## 2. API 资源分组

| 分组 | 前缀 | 数量 | 说明 |
|------|------|------|------|
| 系统 | `/health`, `/api/v1/status` | 2 | 探活与系统状态 |
| 对话 | `/api/v1/chat` | 1 | **统一对话入口（SSE）** |
| 会话 | `/api/v1/sessions*` | 3 | 会话列表 / 详情 / 删除 |
| 记忆 | `/api/v1/memory/*` | 3 | 文献目录 / 文献详情 / 画像 |
| 反馈 | `/api/v1/feedback` | 1 | 用户信号上报 |
| 管理 | `/api/v1/admin/*` | 1 | 手动触发推送 |

**合计：11 个端点**。

---

## 3. 系统

### 3.1 GET /health

不需鉴权。

```json
{ "status": "ok" }
```

### 3.2 GET /api/v1/status

需鉴权。**检查项去掉 redis / chroma，新增 memory_dir。**

```json
{
  "status": "ok",
  "version": "1.0.0",
  "checks": {
    "postgres":   { "ok": true, "latency_ms": 3 },
    "memory_dir": { "ok": true, "paper_count": 1820, "session_count": 96 },
    "paper_search_mcp": { "ok": true },
    "anthropic":  { "ok": true, "latency_ms": 312 }
  },
  "scheduler": {
    "running": true,
    "next_daily_push_at": "2026-05-21T02:00:00+00:00"
  }
}
```

---

## 4. 对话（统一入口）

### 4.1 POST /api/v1/chat (SSE)

**说明**：**唯一的发消息入口**。发一条用户消息，agent 自主决策（直接答 / `search_memory` 召回 / `search_papers` 重搜 / 改 `profile.md` 调偏好），以 SSE 流式返回。

- `session_id` **即 LangGraph `thread_id`**：传它就在该 thread 上续聊，对话上下文由 LangGraph state 自动恢复。
- **不传 `session_id`** → 服务端生成一个新 thread_id（`trigger=chat`），首个 `meta` 事件回传。
- **传当天 `daily-push` 会话的 `session_id`** → 即"在推送下面自然追问"。

**Request**：

```json
{
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef0123456789",
  "content": "第 3 篇用的是什么测试方法？"
}
```

**Response 200**（`Content-Type: text/event-stream`）：

```
event: meta
data: {"session_id":"a1b2c3d4-...","trace_id":"..."}

event: tool
data: {"name":"search_memory","args":{"query":"硫化物 界面阻抗","scope":"papers"},"hits":2}

event: tool
data: {"name":"read_file","args":{"path":"./memory/papers/2026-05-15/arxiv-2405.01234.md"}}

event: citation
data: {"papers":[{"paper_id":"arxiv-2405.01234","title":"Interface engineering ...","url":"https://arxiv.org/abs/2405.01234"}]}

event: token
data: {"delta":"他们主要用了 EIS、XPS 和 Cryo-EM 三种表征方法。"}

event: done
data: {"finish_reason":"stop","token_usage":{"input":1500,"output":42,"model":"claude-haiku-4-5-20251001","cache_read_tokens":900},"latency_ms":2750}
```

**事件类型清单**：

| event | data | 出现次数 | 说明 |
|-------|------|---------|------|
| `meta` | `session_id`(=thread_id) + trace_id | 1 | 首个事件；新建会话时回传 `session_id` |
| `tool` | agent 调用的工具名 + 参数 + 命中数 | 0..N | 让前端展示"agent 正在 grep / 读文件"，**也是"无路由层"的可视化证据** |
| `citation` | 命中 / 引用的文献 | 0..1 | agent 读过的 paper.md，前端渲染为可点链接 |
| `token` | 增量 token | N | 流式正文 |
| `error` | code + detail | 0..1 | 流中失败 |
| `done` | 完成 + 统计 | 1 | |

> **关键**：当 agent 判断"上下文已有答案"时，整个流里**没有 `tool` 事件**——直接 `token` + `done`。这在前端可见地体现了"没有强制检索 / 没有路由层"。

> **客户端断线重连**：MVP 不支持 Resume（对话 state 已由 LangGraph 持久化，重新发问即可）。

---

## 5. 会话

> v0.4：会话不再有 PG 表。**列表来自 `./memory/sessions/*.md` 的 frontmatter；消息正文来自 LangGraph state（按 `session_id`=`thread_id`）。**

### 5.1 GET /api/v1/sessions

会话列表（侧栏用），扫 `./memory/sessions/` 各 md 的 frontmatter，按 `last_active_at` 倒序。

```json
{
  "items": [
    {
      "id": "a1b2c3d4-...",
      "trigger": "daily-push",
      "title": "今日推送 · 硫化物固态电解质等 8 篇",
      "last_active_at": "2026-05-20T03:42:11+00:00",
      "message_count": 6
    }
  ],
  "next_cursor": "",
  "has_more": false,
  "limit": 20
}
```

### 5.2 GET /api/v1/sessions/{session_id}

会话元信息（来自 session md frontmatter）+ 消息列表（**从 LangGraph state 按 `thread_id=session_id` 读**，含工具调用与引用）。

**Query**：`limit`, `cursor`

```json
{
  "id": "a1b2c3d4-...",
  "trigger": "chat",
  "title": "硫化物界面阻抗追问",
  "related_papers": ["arxiv-2405.01234", "s2-abc123"],
  "topics": ["硫化物固态电解质", "界面阻抗"],
  "messages": [
    {
      "id": 8820, "role": "user",
      "content": "上周推过的那篇硫化物界面阻抗论文用的什么表征方法？",
      "created_at": "2026-05-20T03:41:50+00:00"
    },
    {
      "id": 8821, "role": "assistant",
      "content": "你引用的应该是 Doe 等人 2026（arxiv-2405.01234），主要用了 EIS / XPS / Cryo-EM ...",
      "tool_calls": [
        {"name": "search_memory", "args": {"query": "硫化物 界面阻抗", "scope": "papers"}},
        {"name": "read_file", "args": {"path": "./memory/papers/2026-05-15/arxiv-2405.01234.md"}}
      ],
      "citations": [
        {"paper_id": "arxiv-2405.01234", "title": "Interface engineering ...", "url": "https://arxiv.org/abs/2405.01234"}
      ],
      "token_usage": {"input": 1234, "output": 567, "model": "claude-haiku-4-5-20251001", "cache_read_tokens": 800},
      "latency_ms": 2840,
      "created_at": "2026-05-20T03:42:11+00:00"
    }
  ],
  "next_cursor": "",
  "has_more": false
}
```

> `related_papers` / `topics` 来自 session md frontmatter。`citations` 由该轮 `tool_calls` 里的 `read_file` 路径解析得到（无引用关联表）。消息 `id` 为 LangGraph 内部消息标识，仅用于前端 key。

### 5.3 DELETE /api/v1/sessions/{session_id}

硬删除会话（M4 §6 Q8 owner 拍板，最终一致 + 先 md 后 PG）：

1. **`thread_id` 以 `daily_push:` 开头 → 400 `DAILY_PUSH_NOT_DELETABLE`**
   （PG `pushes` 表是审计 source of truth，不可被本端点删；CLAUDE.md §2
   第 4 条）。
2. **先删 session md**（用户感知层 = 列表立即不可见）。md 文件 IO 失败 → 500。
3. **再删 LangGraph checkpoint**（`AsyncPostgresSaver.adelete_thread(thread_id)`
   清 `checkpoints` / `checkpoint_blobs` / `checkpoint_writes` 三张框架自管表，
   见 `langgraph/checkpoint/postgres/aio.py:340-361`）。
4. **checkpoint 删失败 → log warning + 仍返回 204**（最终一致；thread_id UUID
   不复用 = orphan state 不影响功能；由 M6 运维脚本兜底清理）。

**Response 204**：空 body。

**Response 400**（`code=DAILY_PUSH_NOT_DELETABLE`）：

```json
{
  "type": "about:blank",
  "title": "Bad Request",
  "status": 400,
  "code": "DAILY_PUSH_NOT_DELETABLE",
  "detail": "daily-push 会话不可删（PG pushes 审计需保留）"
}
```

---

## 6. 记忆（文件系统目录）

> 直接暴露 `./memory/` 文件系统，**不经 PG 检索**。底层就是 `list_dir` / `search_memory` / `read_file`。

### 6.1 GET /api/v1/memory/papers

浏览 / 检索推送过的文献。

**Query 参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `q` | string | 关键词（底层 `search_memory(scope="papers")` → ripgrep） |
| `date` | date | 按推送日期目录浏览（`./memory/papers/{date}/`） |
| `source` | string | `arxiv` / `s2` / `crossref` / `openalex` |
| `limit` / `cursor` | | 分页 |

**Response 200**（字段来自 paper.md frontmatter）：

```json
{
  "items": [
    {
      "paper_id": "arxiv-2405.01234",
      "source": "arxiv",
      "doi": "10.1016/j.elec.2026.05.001",
      "title": "Interface engineering of sulfide solid electrolytes for ...",
      "authors": ["Doe, J.", "Smith, A."],
      "pub_date": "2026-05-12",
      "venue": "Nature Energy",
      "url": "https://arxiv.org/abs/2405.01234",
      "first_pushed_at": "2026-05-13T02:00:01+00:00",
      "score": 8.7,
      "md_path": "./memory/papers/2026-05-13/arxiv-2405.01234.md"
    }
  ],
  "next_cursor": "",
  "has_more": false,
  "limit": 20
}
```

### 6.2 GET /api/v1/memory/papers/{paper_id}

单篇文献详情：返回 paper.md 的 frontmatter + 正文（title / abstract / 推荐理由），并内嵌 `cited_in`（哪些对话讨论过它——由 `search_memory(scope="sessions")` grep `related_papers` 得到）。

```json
{
  "paper_id": "arxiv-2405.01234",
  "frontmatter": {
    "source": "arxiv", "doi": "10.1016/...", "title": "Interface engineering ...",
    "authors": ["Doe, J.", "Smith, A."], "pub_date": "2026-05-12",
    "score": 8.7, "feedback": {"liked": 1, "disliked": 0, "asked": 0}
  },
  "body_markdown": "## Title\nInterface engineering ...\n\n## Abstract\nWe report ...",
  "cited_in": [
    {
      "session_id": "a1b2c3d4-...",
      "session_title": "硫化物界面阻抗追问",
      "last_active_at": "2026-05-20T03:42:11+00:00"
    }
  ]
}
```

**Response 404**：`code=NOT_FOUND`（无该 paper.md 文件）。

### 6.3 GET /api/v1/memory/profile

只读返回 `./memory/profile/profile.md`（前端画像页用）。

```json
{
  "updated_at": "2026-05-20T10:05:00+08:00",
  "sample_count": 42,
  "keyword_weights": {"sulfide solid electrolyte": 0.83, "interface resistance": 0.71},
  "seed_queries": ["lithium battery solid electrolyte", "battery thermal management"],
  "summary_markdown": "用户关注硫化物固态电解质的界面阻抗与循环寿命 ..."
}
```

> **如何修改画像？** 不提供 PATCH——用户在 `/chat` 里自然语言说"以后多推固态电解质、少推液态添加剂"，agent 按 `profile_update.skill.md` 改写 `profile.md`（架构 §4.3 流程 C）。这是"用对话调偏好，不用专用接口"的体现。

---

## 7. 反馈

### 7.1 POST /api/v1/feedback

用户隐式 / 显式信号上报。**幂等**：`(paper_id, signal_type, 5-minute bucket)` 内同一信号只记一次。信号写入 **PG `feedback` 表（source of truth）**，并追加一行到派生日志 `./memory/feedback/{date}.log`（供画像更新时 agent grep）。**不回写 paper.md**。

**Request**：

```json
{
  "paper_id": "arxiv-2405.01234",
  "signal_type": "liked",
  "context": { "from": "today_panel" }
}
```

| 字段 | 类型 | 必需 | 取值 |
|------|------|------|------|
| `paper_id` | string | ✓ | 文献业务码 |
| `signal_type` | enum | ✓ | `liked` / `disliked` / `asked` / `skipped` / `impression` |
| `context` | object | ✗ | 自由扩展，不计入权重 |

> **权重不由客户端传**，服务端按 `signal_type` 查映射（写在 `profile_update.skill.md` / 配置），防篡改。

**Response 201**：

```json
{ "paper_id": "arxiv-2405.01234", "signal_type": "liked", "weight": 3.0, "recorded_at": "2026-05-20T03:15:22+00:00" }
```

**Response 409**：`code=DUPLICATE_SIGNAL`。

---

## 8. 管理端（仅本机）

### 8.1 POST /api/v1/admin/trigger/daily-push

手动触发一次每日推送（补跑 / 调试）——等价于调度器发那条系统消息。

**Request**：

```json
{ "run_date": "2026-05-20", "force": false }
```

| 字段 | 说明 |
|------|------|
| `run_date` | 推送日期；缺省为今天 |
| `force` | `true` 时即使当天已推送也强制重跑（见下方语义） |

**`force=true` 语义**（owner 拍方案 A，PR-1 落地）：

1. **清同 thread checkpoint**：`AsyncPostgresSaver.adelete_thread(thread_id)` 删 LangGraph 三张自管表的同 `daily_push:YYYY-MM-DD` 行，破 handover §3.9「同 thread 复用 ToolMessage」屏障，强制 agent 重新调 `search_papers`（不直接复用上次结果）
2. **绕过历史去重**：`search_papers_tool` 内部读 `FORCE_RERUN_DEDUP` ContextVar（PEP 567 async 透传到 LangGraph tool node），force=True 时传 `dedup_against_memory=False`，允许 4 源命中已存 paper_id；deterministic，不依赖 LLM 解析 kickoff prompt
3. **不重写已存 paper.md**：`search_papers.py` 落盘前 `if path.exists(): continue`，保留原内容（含 arxiv v2 → v3 也不覆盖；owner 若要拉新版本须**手动 `rm` 该 paper.md** 再触发 force）；log `search_papers_skip_existing_md`
4. **覆盖 PG pushes 行**：`_claim_run(force=True)` 让 `success` 状态行 reset 到 `running`，跑完写回新 `selected_count` / `selected_papers` / `email_sent`（原行被覆盖，**不新建行**）

**Response 202**：

```json
{ "job_log_id": 88, "status": "running", "started_at": "2026-05-20T04:00:00+00:00" }
```

**Response 409**：`code=ALREADY_RUNNING`（LangGraph 同 `thread_id=daily_push:YYYY-MM-DD` 正在执行，thread busy）。

> 任务历史 / 埋点查询直接查 PG `pushes` 表或看 Streamlit `/status` 页，**不单列 API 端点**（减法优先）。

---

## 9. SSE 规约

**MVP 仅用 SSE，不引入 WebSocket**：

| 维度 | **SSE（选）** | WebSocket |
|------|-------------|-----------|
| 单向流（服务器→客户端） | 天然支持 | 双向 overkill |
| 浏览器原生 | EventSource | WebSocket API |
| 反代友好 | ✓ | 需特殊配置 |
| FastAPI 集成 | `StreamingResponse` / `sse_starlette` | `WebSocketRoute` |

**SSE 心跳**：每 15s 发 `: keepalive\n\n` 注释行，防反代切断。

---

## 10. OpenAPI / 自动文档

- FastAPI 自动生成 OpenAPI 3.1：`GET /openapi.json`
- Swagger UI：`GET /docs`（仅 `ENV=dev`）；ReDoc：`GET /redoc`（同上）
- 所有 endpoint 用 `response_model` + Pydantic v2 严格定义。

---

## 11. 备选方案 & 取舍

| 决策点 | 选定 | 备选 | 取舍理由 |
|--------|-----|------|---------|
| **会话消息读取** | LangGraph state（按 thread_id） | 自建 PG `messages` 表 + 接口 | 不 overwrite 框架数据结构；省一张表与一套接口 |
| **会话列表** | 扫 session md frontmatter | PG `sessions` 表 | 无需建表；md 即归档 |
| **发消息入口** | 单个 `/chat`（SSE） | 会话/消息双套接口 | 推送即对话，统一入口最简 |
| **文献接口** | `/memory/papers*`（读文件目录） | PG 检索 / 向量语义检索 | 无 PG papers / 向量库；直接 grep 文件 |
| **画像修改** | 通过 `/chat` 自然语言 | 专用 PATCH 接口 | 调偏好是对话能力，不需专用接口 |
| **反馈存储** | PG `feedback` 表 | 纯文件 | 要按 paper_id/signal 索引做统计 |
| 分页 | cursor | offset+limit | 永久保留数据，offset 性能退化 |
| 流式 | SSE | WebSocket / 轮询 | 见 §9 |
| 软删除 | 不做（硬删） | `deleted_at` | 永久保留；会话允许主动删 |

---

> **v0.4 已删除 / 解耦清单**：❌ 与 PG `messages` 表耦合的消息读取（改 LangGraph state）　❌ PG `sessions` 表（会话列表改扫 md）　❌ 删会话的 PG 级联（改删 thread + md）　❌ feedback 回写 paper.md（改 PG + 派生 log）　❌ admin 409 的 PG `locks`（改 thread busy）。
> **下一步**：进入 [Step 5：开发路线图](./05_roadmap.md)。
