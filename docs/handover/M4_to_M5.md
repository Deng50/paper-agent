# M4 → M5 上下文交接

> 用途：下次会话拿不到本次聊天记录，靠本文件 + `docs/01~05`(v0.4) + `CLAUDE.md` 接续 M5。
> 本文件交接**事实与已定决策**，不写 M5 怎么做。生成于 2026-05-26（含 owner demo 真测后的 7 个 bug-fix）。
> 与 M2_to_M3 / M3_to_M4 同惯例：handover 提交到 main，便于跨会话有据可查。

---

## 1. 当前 git 状态（M4 完成时）

```
f9f2787 feat(chat): 历史会话列表 + 切换 thread 继续聊（PR-2 / Bug 2 全套）       ← 最新
75a1a1d fix(force): 撤销绕过 dedup 路径，保留历史去重让 force 真拉新（方案 B / PR-1.1）
3dadf94 fix(force): 破双层 dedup 屏障 + skip-if-exists（Bug 1 方案 A 落地，PR-1.1 部分撤销）
2edafb7 fix(admin): trigger 加 force 参数 + frontend 强制重跑选项 + skill 教引导
e1e29a3 fix(agent): 加 list_dir_tool 修复「回顾全部」类请求幻觉撒谎
72a0537 fix(chat): dangling tool_call 优雅处理 + 友好错误提示
cc0e285 fix(api): chat token 整段 emit + paper_search_mcp 探针改 vendored import
c02fae0 docs(handover): M4 → M5 上下文交接草稿（本文件早期版本）
d845e92 test(eval): cn_recall_gold.yaml 填 10 题候选（A/B/D 三主题）
3fd7278 feat(scripts): rebuild_session_md.py 故障恢复 + 单测（M4 task 6 / Q9）
49fc237 feat(api): DELETE /api/v1/sessions/{thread_id}（M4 Q8 / docs/04 §5.3）
e3351ee feat(frontend): pages/chat.py /chat 流式 UI（M4 task 4）
ab58f03 feat(api): /chat SSE 路由 + session md 派生写 helper（M4 task 1-2）
e13ed49 feat(eval): scripts/eval_cn_recall.py 中文召回率评估骨架
fb5974e test(eval): tests/eval/cn_recall_gold.yaml 中文召回率黄金集骨架
1710f3c feat(skill): skills/memory_recall.skill.md 落盘（Q4 草案字面）
e3a6f55 feat(agent): build_lit_agent skills 参数化 + lit_agent.py format reflow
e3a29a0 docs(M4): 消歧义 session md 派生写 + skill 拼入时序脚注
47f2eb9 feat(scheduler): token-log 加 cache_read/cache_creation 两字段           ← M3 终
```

- 分支：`main`（本地，无 remote）；working tree clean
- 容器：3 个全绿；api + frontend 多次 rebuild + recreate 验证；postgres 全程不动
- scheduler 10:00/11:00 双 cron 已注册（2026-05-26 起每天自动跑）

---

## 2. M4 已实活验证的能力（owner 真 demo 测过）

### 核心能力
- **`POST /api/v1/chat` SSE 流式问答** 跑通：5 event 类型 meta/tool/citation/token/done + 15s keepalive
- **session md 派生写** 自动落 `./memory/sessions/{date}/{HH-MM}-chat.md`（done 后 fire-and-forget asyncio.to_thread）
- **跨日召回** agent 调 `search_memory` / `list_dir` / `read_file` 看 archive 给中文回答
- **`DELETE /api/v1/sessions/{thread_id}`** 最终一致删（先 md 后 PG checkpoint），daily_push 拒删 400
- **强制重跑推送** owner 勾「强制重跑」+ button → 真拉新 batch 10 篇 paper（log 实证 `search_papers_done deduped=301 skipped_existing=0`，PG selected_papers 跟旧 batch 0% 重叠）
- **历史会话管理** `GET /api/v1/chat/sessions` + `/messages` + 前端侧栏列表 + 点击切换 + 二次确认删 + 刷新自动恢复最近
- **故障恢复脚本** `scripts/rebuild_session_md.py --thread-id <uuid> [--dry-run] [--force]`
- **paper_search_mcp 探针** 改 vendored import 检测，`/status` 全绿
- **agent 工具白名单** 4 件套 = `search_papers / read_file / search_memory / list_dir`（只读；M4 不给 `write_file`）

### 测试用例覆盖（pytest）
- `test_m4_delete_session.py`：5 用例（daily_push 拒删 / md+PG 双删 / PG fail 最终一致 / 无 md / 鉴权回归）
- `test_m4_rebuild_session_md.py`：4 用例（dry-run / 无 messages abort / 已有 md 拒覆盖 / --force 覆盖）
- `test_m4_chat_sessions.py`：6 用例（列表排序 / 跳过坏 md / 空目录 / 保留 tool_calls / 空 thread / 鉴权）
- **baseline 1 个 fail**：`test_m3_mail.py::test_send_email_no_recipient_fail_fast`（M3 既有 P1，env isolation 缺陷，见 §5 P1）

### M4 末态门禁 baseline（M5 P1 启动前的对比基准）

- **`ruff check .`**：0 errors（M5 P1 把 vendor/paper-search-mcp/ 加入 `pyproject.toml [tool.ruff] extend-exclude` 后；vendored 上游包按 CLAUDE.md §4「锁版本不动」精神不扫，此前 524 errors 全在 vendor）
- **`ruff format --check .`**：0 reformat（同上，此前 53 文件 reformat 全在 vendor）
- **`mypy src`**：Success no issues found in 34 source files
- **Windows 本机全套 pytest**：starlette TestClient + anyio blocking_portal 触发 native crash，无法出 summary；改用「定向验证」策略 = 改动相关文件 pytest，详见 [docs/known_issues/windows_starlette_testclient.md](../known_issues/windows_starlette_testclient.md) Bill 1

---

## 3. M4 累积的「已拍板决策」（不要再争）

### 3.1 SSE 用 FastAPI 原生 `StreamingResponse` + 自建 30-LOC SSE wire（Q1）
不引入 `sse-starlette` / `httpx-sse`；15s keepalive 由独立 asyncio task 喂 queue。
切换回退条件：`RuntimeError: Event loop is closed` / `RuntimeWarning: coroutine was never awaited` / SSE 流静默 > 15s 无心跳。

### 3.2 session md 派生写 = `try/finally` + `asyncio.to_thread` fire-and-forget（Q2.1-4）
- `asyncio.to_thread(sync_fn)` 把 sync derive 扔 thread pool，sync 函数对 cancel 免疫（Python doc 行为）
- `_DERIVE_TASKS` module-level set 保 Task 引用防 weak-ref GC
- cancel 路径不归档：message 仍在 LangGraph state，重发可续

### 3.3 单 agent 复用，skill 列表参数化（Q3）
- `build_lit_agent(skills=("daily_search",))` 默认 = M3 单 skill（向后兼容）
- chat 路由显式传 `skills=("daily_search", "memory_recall")`
- `profile_update.skill.md` 留 M5（见 §5 P1）

### 3.4 跨日召回 = agent 自主，不写硬规则（Q4）
- `memory_recall.skill.md` 落盘 + 加 `list_dir` 应对「回顾全部」类宽泛请求
- 验收硬指标：上下文已有时 SSE 流 0 `tool` 事件

### 3.5 中文召回率黄金集 A/B/D 三主题 10 题（Q5）
- 5 文献题 `expected_paper_ids` 已填（基于 M3 真 corpus 37 篇）
- 5 对话题 `expected_session_ids` 占位待 owner 用 M4 demo 累积的真 chat 历史填
- F 警示项（电池热管理 corpus 仅 1 篇）单独算分

### 3.6 M4 不给 agent `write_file`（Q6）
- agent 工具白名单只读 4 件套（+ M4 新加的 `list_dir`）
- M5 画像自更新里程碑才加 `write_file`，路径白名单严守 `^\./memory/profile/profile\.md$`

### 3.7 frontend chat 用同步 `httpx.Client.stream()` + streamlit native（Q7）
- `st.chat_message` + `st.write_stream`；自建 SSE byte parser；不动 streamlit 版本

### 3.8 DELETE session 最终一致 + daily_push 拒删（Q8）
- `thread_id.startswith("daily_push:")` → 400 `DAILY_PUSH_NOT_DELETABLE`
- 先 md 后 PG checkpoint；PG `adelete_thread` 失败 log warning 仍 204
- `AsyncPostgresSaver.adelete_thread` 源码：`langgraph/checkpoint/postgres/aio.py:340-361`

### 3.9 故障恢复脚本 `scripts/rebuild_session_md.py`（Q9）
- 单 thread `--thread-id`；`--dry-run` / `--force` 护栏；`--all` 留 M6

### 3.10 force=True 重跑语义 = 清 checkpoint **+ 保留历史去重**（PR-1.1 方案 B）
- 修过两次：方案 A（绕过 dedup）→ 实测同 query+score 出 ~100% 重叠 top 10 → owner 看像"没换" → 撤回
- 方案 B 字面（owner 拍）：
  1. `adelete_thread(thread_id)` 清 checkpoint，破复用屏障
  2. **保留 `dedup_against_memory=True`**，让 `load_dedup_index` 扣历史 → search 只返真新候选
  3. `skip_if_exists` 保留作防御性安全网
  4. PG pushes 行覆盖（不新建）
- **设计取舍**：当天 4 源无新 publish 时 selected 可能 < 10 或为 0，**如实报而非凑数推旧**
- 真实测试验证：5/25 force 重跑后 selected 10 篇全是 `arxiv-2605.*` 新 paper，旧 batch 0% 重叠

### 3.11 chat agent 接收"现在推送一次"类请求时**礼貌引导**而非沉默
- chat agent system prompt 字面禁止推送（lit_agent.py:45-46），但 M4 改 skill 后 agent 会答「我不能在对话里推送，请点左侧栏『📬 每日推送』tab 的『▶️ 立即触发一次推送』；若今日已推过想重跑则勾选『强制重跑（覆盖今日 success）』」

### 3.12 dangling tool_call hygiene
- chat 路由开始前 `aget_state` 检测「最后一条 = AIMessage with tool_calls 但无 ToolMessage」→ emit `error{code=DANGLING_TOOL_CALL}`
- 前端识别该 code 渲染中文友好提示，**不自动 reset thread**（adelete_thread 不可逆，让用户主动点新建会话）

### 3.13 `paper_search_mcp` 探针改 vendored import
- M2 起 vendored 接入（docs/02 §A.2）；`_check_paper_search_mcp` 改为 try import 4 源模块

---

## 4. M4 完成度（roadmap §5 8 任务）

| Task | 内容 | 状态 |
|------|------|------|
| 1 | `/chat` SSE（meta/tool/citation/token/done + 15s keepalive） | ✅ |
| 2 | session md 派生写 + frontmatter 同步 | ✅ |
| 3 | `memory_recall.skill.md` 落盘 | ✅ |
| 4 | `frontend/pages/chat.py` 流式 + 工具可视化 + 引用渲染 + 历史会话管理 | ✅（PR-2 加历史会话完整版） |
| 5 | `/memory/papers` + `/memory/profile` API | ❌ **未做**；前端直接读 `./memory/papers/` 文件足够，未紧迫；M5 可补 |
| 6 | 故障恢复脚本 | ✅ |
| 7 | 中文召回率 evaluation | ✅ 骨架 + 5 文献题填好；5 对话题占位待真 demo 后填 |
| 8 | 集成测试：跨日召回 ≥ 4/5 + 首 token ≤ 3s | ❌ **未跑**：需要先填 5 对话题 + 跑 `python -m scripts.eval_cn_recall` 出基线 |

**M4 验收**：6 / 8 完成；剩 Task 5 + Task 8 留 M5 启动前补（或 M5 中并行）。

---

## 5. P0 / P1 / P2 follow-up（M5 启动前过一遍）

### P0（开发末期处理）
- `ANTHROPIC_API_KEY` + `API_TOKEN` 轮换：handover §4 M3 已登记；M4 期间 owner 未要求轮换；同时 M6 compose 硬化（postgres 端口 internal-only + 密码 .env 读非 inline）

### P1（M5 启动前必做或可做）

#### 真实测试 + 评估补漏
- **`tests/test_m3_mail.py::test_send_email_no_recipient_fail_fast` env isolation**：M3 commit `fd2743c` 既有缺陷；测试期望 `SMTP_TO=""` 但 `.env` 真 SMTP_TO 被 `get_settings()` 读到 → 发邮件成功而非抛 NoRecipientError。修：`monkeypatch.setattr(settings, "smtp_to", "")`
- **黄金集对话题 expected_session_ids 填写**：M4 demo 已累积 8+ 真实 chat 历史（owner 实测），按主题 A/B/D 各 1-2 题挑出真实 session_id 填进 `tests/eval/cn_recall_gold.yaml`
- **跑 evaluation 出 M4 基线**：`uv run python -m scripts.eval_cn_recall --report report.md`；输出 Top-1/3/5 三档命中率；< 85% 进 M7 SQLite FTS5 评估（docs/02 §5.5）
- **首 token ≤ 3s 实测**：Anthropic Haiku 4.5 + newapi 中转 latency；M4 chat 流式实测整段 emit（非字符级），TTFT 可能略高，要测一下

#### 代码 / 设计补漏
- **`ChatAnthropic streaming=True` flag**：`docs/02 §A.2` 字面要求但 M3 commit `8c3e68f` 漏传；M4 chat 当前用 `stream_mode="updates"` 整段 emit token（非字符级流）。补这一行后可改 chat.py 用 `["updates", "messages"]` multi-mode 拿字符级 chunks
- **Q6 M5 `write_file` 白名单同 PR 三处同步**（M5 hard prerequisite）：
  - `src/lit_agent/tools/memory.py` 加 `_WRITE_WHITELIST = re.compile(r"^\./memory/profile/profile\.md$")`
  - `CLAUDE.md §5` 「文件工具路径白名单」字面加「写白名单：M5 起仅 profile.md」
  - `docs/02 §3.4` 「文件工具路径限定」字面同步
- **task 5 `/memory/papers` + `/memory/papers/{paper_id}` + `/memory/profile` API**：docs/04 §6 字面 schema 已定；M5 启动前 nice-to-have
- **DELETE `/api/v1/sessions/{thread_id}` OpenAPI 400 response 显式声明**：当前 OpenAPI 只列 204 / 422
- **`/chat` OpenAPI 400 / 503 responses 显式声明**：同上模式
- **session md `topics` 字段关键词提取**：M4 字段 = `[]` 占位；M5/M6 可让 agent 自更新或词频 top-3
- **dangling tool_call 自愈机制**：M4 是 emit error + 让 user 主动新建会话；M5/M6 可设计自动注入 fake ToolMessage 补全

### P2（M6 / M7）
- 邮件投递监控（SPF/DKIM 头）
- `scoring.py` system prompt 加评分锚点（9-10/7-8/5-6/0-4 分档）
- test_m3_daily_push / test_m4_* 用独立 test DB（M6 splitting）
- SQLite FTS5 派生索引（M7 触发条件 = cn_recall < 85%）
- PDF 全文 RAG
- `rebuild_session_md.py --all` 批量模式（M6 backup 运维）

---

## 6. 偏好画像（profile.md）现状

**单一 source of truth**：`./memory/profile/profile.md`

当前内容（M1 `init_memory.py` 创建的占位，**M4 全程未更新**）：

```yaml
---
updated_at: 1970-01-01T00:00:00+08:00
keyword_weights: {}
seed_queries:
  - "lithium battery solid electrolyte"
  - "battery thermal management"
---

## 画像摘要
（占位）尚无足够反馈。每日推送先用 seed_queries 兜底，反馈累积后由
profile_update.skill.md 增量改写本文件（M5）。
```

**读路径**（3 处）：
- `tools/search_papers.py:62-72` `_read_profile_summary()` 解析 frontmatter 之后正文
- `tools/scoring.py:71` 拼进 Haiku 评分 prompt 「用户画像摘要：\n{...}」
- `skills/daily_search.skill.md:20` agent 推送第 1 步 `read_file("./memory/profile/profile.md")`

**写路径**：
- `scripts/init_memory.py:96` 首次启动幂等写占位
- **M5 `profile_update.skill.md` 才真自更新**（当前是 `init_memory.py:62-72` 占位）

**M4 / 临时调偏好路径**：owner 手编辑 `D:\paper-agent\memory\profile\profile.md` → 下次 daily-push 立即生效。M5 之前**没有自动写**。

**M3 corpus 实际方向**（基于 37 篇 score≥7 paper.md 高频统计）：
- A 硫化物固态电解质 / argyrodite / Li6PS5Cl —— 12+ 篇
- B 锂金属负极界面工程 / dendrite / interphase —— 10+ 篇
- D 聚合物 / 复合固态电解质 / PEO / PVDF —— 4 篇
- E 正极包覆 / 界面化学 —— 4 篇
- F 电池热管理 —— **仅 1 篇**（CLAUDE.md §1 字面方向但 corpus 严重稀缺，黄金集 F 警示项已登记）

---

## 7. M4 实际工时

- **roadmap §5 估算**：3 人天 = 18h
- **实际**：约 **18-22h**（含 PR-1 + PR-2 + 7 个 bug-fix + 4 次 docker rebuild + handover 重写）
  - 主线 9 commit ≈ 8h
  - owner demo 撞 6 个 bug 修复（chat token / mcp probe / dangling / list_dir / admin force / force fix A→B）≈ 6h
  - PR-2 历史会话列表 + 切换 + 二次确认 + 自动恢复 ≈ 4h
- 在预算内（reroute force fix 方案 A→B 是设计层 trade-off 验证，不计 bug）

---

## 8. 启动 M5 的第一条指令（给新会话）

参考 §9「新对话启动提示词」直接复制粘贴。

---

## 9. 新对话启动提示词（owner 复制此段给新对话开 M5）

````
我们在推进「文献情报 Agent」项目的 M5（画像自更新）。项目在 D:\paper-agent。

事实来源 + 必读顺序：
1. 先读 docs/handover/M4_to_M5.md —— M4 已完成的事实（§2）+ 已拍板决策（§3
   不要再争）+ M5 启动前的 P0/P1/P2 待办清单（§5）+ 偏好画像现状（§6）
2. 再读 docs/01~05(v0.4) + CLAUDE.md —— 项目宪法
3. M5 目标见 docs/05 §6：lit_agent 按 profile_update.skill.md 读近 30 天
   feedback（PG 派生 feedback/*.log）→ 原子写 profile.md；A/B 对比有/无画
   像 Top-10 重合度 + 👍率

M4 端到端 demo 已绿（owner 真测过：/chat SSE 流式 + 跨日召回 + 历史会话切换
+ force 重跑真拉新 10 篇邮件 163→tju 已收）。18 个 M4 commit 已落 main
（最新 f9f2787 PR-2 历史会话列表）。

【M5 启动前的 P1 硬前提清单】按以下顺序处理（M4_to_M5 §5 P1 字面）：
1. tests/test_m3_mail.py SMTP_TO env isolation 修（baseline 1 个 fail 单点）
2. ChatAnthropic streaming=True 补齐到 agents/lit_agent.py:124（让 chat token
   字符级流，docs/02 §A.2 字面要求；当前整段 emit 不影响功能但 TTFT 体验差）
3. 黄金集对话题 expected_session_ids 填写（M4 demo 累积 8+ chat 历史，owner 挑）
4. 跑 evaluation 出 M4 基线：uv run python -m scripts.eval_cn_recall
   --report report.md；目标 Top-3 ≥ 80%；< 85% 进 M7 SQLite FTS5
5. Q6 write_file 白名单三处同步（M5 hard prerequisite，agent 要写 profile.md）：
   - src/lit_agent/tools/memory.py 加 _WRITE_WHITELIST regex
   - CLAUDE.md §5 字面同步
   - docs/02 §3.4 字面同步

【M5 工作核心】
- 引入 profile_update.skill.md 拼入 build_lit_agent 默认 skills 列表
  （之前留 M5 才上的字面要求；M4 既有 skills=("daily_search", "memory_recall")
  → M5 改为 ("daily_search", "memory_recall", "profile_update")）
- 让 agent 调 search_memory(scope="feedback") + read_file 看 30 天反馈 →
  生成新 profile.md 内容 → 调 write_file（M4 后加的新工具）原子写
- A/B 对比脚本验证画像生效

【M4 已拍板决策不要争】见 §3，13 条。最常被新会话误读的 3 条：
- 3.10 force=True 保留 dedup（方案 B；方案 A 已撤回，绝不再"绕过 dedup"）
- 3.6 agent 工具默认只读 4 件套，M5 才加 write_file
- 3.12 dangling tool_call 不自动 reset thread，让用户主动新建

【绝不退回的硬约束】
- 不退回 deepagents（handover §3.1 M3→M4 字面）
- 不写 cache_control（newapi 不透传）
- 不建 PG locks/jobstore/messages/sessions 表（3 表铁律）
- agent 不做 for 循环

【4 类硬护栏】每次重要决策都要过：
1. 动摇 3 容器/3 表/agent 不写 4 件套 → 停下问
2. 不可逆操作（装新依赖 / 改 PG schema / 删表） → 先报回滚命令
3. 事实性结论（库版本 / API 行为 / 源码细节） → 贴命令原文（pip index versions /
   uv add --no-sync lock diff / docker exec / WebFetch 引用）
4. 方向性决策（架构形态 / 模块边界 / 新增或放宽铁律） → 停下问

【优先级】减法 > LangGraph 原生 > agent 自主 > 工程严谨

【开干顺序】
1. 5 句话复述 M5 目标 + P1 前提 + 不要争的决策（等我确认）
2. 按 §5 P1 顺序逐条做 + 同 PR 改 docs（约定 5：docs ↔ 代码一致）
3. 每 commit 过 ruff/mypy/pytest 三关 + baseline 等价（M3 既有 mail test
   fail 是单点；修了它就全绿）
4. M5 涉及画像 state 的代码 PR 前跑「画像更新 + 推送对齐」端到端
````

---

> v0.4 已删除 / 改写清单（与 M3→M4 同惯例）：详见 §3 拍板决策表，含 PR-1.1
> force fix 方案 A → B 撤销路径作为单独 case study 在 §3.10 留存。
> 下一步：进入 M5 启动指令（§9 新对话提示词）。
