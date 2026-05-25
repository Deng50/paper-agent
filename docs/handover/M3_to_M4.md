# M3 → M4 上下文交接

> 用途：明天的新会话拿不到今天的聊天记录，靠本文件 + 项目文件 + `docs/01~05` + `CLAUDE.md` 接续 M4。
> 本文件交接**事实与已定决策**，不写 M4 怎么做（那是新会话的事）。生成于 2026-05-22。
> 与 M2_to_M3 同惯例：handover 不进版本历史？—— **本次按 owner 指示提交到 main**，便于跨会话有据可查。

---

## 1. 当前 git 状态（M3 完成时）

```
$ git log --oneline -12
ed55a08 feat(frontend): 每日推送会话视图 + 👍/👎 反馈（M3 任务8）
fd2743c test(M3): 必跑并发回归（thread-busy 自拒）+ mail/feedback 单测
ab0f103 feat(api): admin 触发 / sessions / feedback 路由（M3 任务5/6）
37c4a28 feat(scheduler): daily-push job + AsyncIOScheduler 10:00/11:00 双 cron（M3 任务4/7）
8c3e68f feat(agent): lit_agent.py (langgraph 原生 react) + daily_search skill 完整
a7bccba feat(mail): tools/mail.py —— Jinja2 渲染 + aiosmtplib 发送（M3 任务3）
a7be4c2 fix(deps): langgraph 1.1.0->1.1.10 修 prebuilt 运行时 skew
a4c8cc9 docs: M3 减法——deepagents 本路线图不使用 + 验收#8 改 token 预算护栏
d3a8bda build(deps): pin M3 deps (langchain-anthropic/apscheduler/aiosmtplib/jinja2)
36221c0 LSTM Network                                            ← 误入仓库的外部 commit（非本项目）
1db88de 测试一下                                                  ← 同上
6889e5b add README.md                                            ← M0
```

- 分支：`main`（本地仓库，无 remote）。
- working tree：M3 完成时 clean，仅 `docs/handover/M3_to_M4.md` 本次新增 + 一些未跟踪的临时产物（`.pytest_tmp/`、`scripts/probe_cache.py`）。
- ⚠️ 历史里几条 `36221c0/1db88de` 是非本项目的杂物（早期混入），不影响 M3。

---

## 2. M3 已实活验证的能力（真环境数据为证，非"代码跑通"）

**端到端实跑（2026-05-22 18:03 UTC+8）**：
- `POST /api/v1/admin/trigger/daily-push` → 202 → 后台 job → **真 Anthropic via newapi** → **真 SMTP 发信到 tju 邮箱**（owner 确认收到）。
- 单次 push 实测：`fetched=400 → deduped=329 → selected=10`，subject「每日文献推送 · 2026-05-22 · 10 篇」，163→tju 投递成功，无 spam。
- token usage 全 4 字段：`input=29335 / output=488 / cache_read=0 / cache_creation=0`，est_cost_usd `~$0.03` per push（按 Haiku 4.5 官方价下限估）。
- **`cache_read`/`cache_creation` 两次独立运行均为 0** → 印证 newapi 不做隐式缓存（与显式 `cache_control` 探针结论一致，见 §3.4）。

**铁律#3「11:00 thread busy 自拒」两条独立证据**：
1. 必跑并发回归 `tests/test_m3_daily_push.py::test_daily_push_thread_busy_reject` 真 PG 上绿：task1 占住 running，task2 同 thread_id → `busy`、只发一次邮件、pushes 仅一行 success。
2. **真环境意外复现**：测试触发时 `Invoke-WebRequest` 客户端报错前其实发出了请求 → 触发的 job 占住 running；重试那次 → 日志 `daily_push_busy_skip 今日推送仍在跑` 自拒。

**graceful 降级**：SMTP 端口/收件人错均走 `pushes.status=partial`、站内 10 篇仍呈现（验收第 6 条）。

---

## 3. M3 累积的「已拍板决策」（不要再争，每条附来源）

### 3.1 **deepagents 整条路线图不用**（不是推迟，是丢弃）
来源：本会话 §6.1+§6.2、commit `a4c8cc9`。M3/M4/M5 都是单 agent + 自建工具 + LangGraph thread/checkpoint + markdown/grep 记忆；deepagents 头部能力（planning/subagent/虚拟fs）全出范围或与铁律#4 自建记忆冲突。lit_agent 用 **`langgraph.prebuilt.create_react_agent` + `langchain_anthropic.ChatAnthropic` 实例**。已扫净 6 处事实源：`docs/01:71`、`docs/02:123/242/283(含附录A.2)`、`docs/05:110/232`、`CLAUDE.md §3` 删 deepagents 行+改 langchain-anthropic 行。

### 3.2 **langgraph 从 M1 的 `==1.1.0` 升到 `==1.1.10`**
来源：commit `a7be4c2`、本会话 C2.5。M1 pin 与 `langgraph-prebuilt 1.0.13`（langgraph 1.1.0 自己 cap `<1.1.0`）存在 runtime skew——prebuilt 1.0.13 要 `from langgraph.runtime import ExecutionInfo,ServerInfo`，1.1.0 的 runtime 没导出，导致 `create_react_agent` 一 import 即 ImportError。M1/M2 因从未 import `.prebuilt` 未踩到。1.1.10 修复。`langgraph-checkpoint(-postgres)` 版本未动。回归：pytest 17→22 passed，checkpointer setup 对真 PG OK。

### 3.3 **`create_react_agent` 在 langgraph V1.0 已 deprecated**
来源：本会话 C4 阶段实测的 `LangGraphDeprecatedSinceV10` 警告。**V2.0 才移除（langgraph 现在 1.2.x，移除尚远）**。传 `ChatAnthropic` **实例**（非 `"anthropic:..."` 字符串）可免装全量 `langchain` 包。届时迁移仅 1 行：`from langchain.agents import create_agent` 并加 `langchain` 依赖。**M4 写 `/chat` 时如果还用 react agent 形态可以继续用 `create_react_agent`，无需现在切换。**

### 3.4 **newapi 网关不透传 `cache_control: ephemeral`**
来源：commit `d3a8bda` 后 §6.11 probe `scripts/probe_cache.py`（未提交）、本会话两次真实推送日志均 `cache_read=0/cache_creation=0`。具体：30906 input token 的 system 块带 `cache_control` 经 newapi 调 `claude-haiku-4-5-20251001`，`cache_creation_input_tokens=0`、`claude_cache_creation_5m/1h=0`，**远超 Haiku 2048 缓存门槛，非假阴性**。**直接后果**：
- 不在代码里写 `cache_control`（经 newapi 是 no-op 死复杂度）。
- `docs/05 §4` 验收#8「prompt caching 生效」已改为「token 预算护栏」：每次推送打印 `daily_push_token_budget` 日志含 input/output/cache_read/cache_creation 四字段 + Haiku 官方价 `$1/$5 per MTok` 下限估的 `est_cost_usd`。
- 真实成本估算：单次 push ≈ $0.014–0.032，月度 1 次/天 ≤ $5 内（实测下限 ~$1/月，预算护栏靠日志监控）。

### 3.5 **调度器 = 同进程 `AsyncIOScheduler` + memory jobstore（§6.3 a）**
来源：本会话 §6.3、commit `37c4a28`。10:00 主 cron + 11:00 第二个独立 cron 打**同 `thread_id=daily_push:YYYY-MM-DD`**；不用 misfire_grace、不上 PG jobstore（jobstore 会让 APScheduler 自建表，踩「PG 仅 3 表」红线）。重启自动重建 schedule（cron 在代码里）。

### 3.6 **「thread busy 自拒」用 `pushes` 表做闸（不是 LangGraph 内部 lock）**
来源：§6.5、commit `37c4a28`、`scheduler/jobs.py::_claim_run`。机制：`UniqueConstraint(user_id, run_date)` + `status` 字段——首个 job INSERT `pushes(running)` 占位；第二个 job 撞唯一约束 / 读到 `running` → 自拒；读到 `success` → already_done；读到 `failed/partial` → 合法补跑（status 重置为 running、错误清空、started_at 刷新）。**完全不建 locks 表、不用进程内 asyncio.Lock。** 必跑回归 + 真环境双触发均验证。

### 3.7 **agent 工具集是只读三件套；发邮件/写 pushes/写画像不是 agent 工具**
来源：§6.8、commit `8c3e68f`、`agents/lit_agent.py`。M3 agent tools = `search_papers_tool / read_file_tool / search_memory_tool`（只读）。**邮件组装+SMTP 传输由 app 层 job 做**（铁律#1 deterministic 归代码）；**pushes 审计由 job 解析 agent 最终 LangGraph state 的 `ToolMessage`/`AIMessage` 写入**。M4 加 `/chat` 时如果要给 agent `write_file`（M5 画像自更新）也得严格按白名单。

### 3.8 **`search_papers` 加向后兼容 `stats` 出参**
来源：commit `8c3e68f`、`tools/search_papers.py`。签名加了 `stats: dict[str, int] | None = None`（默认 None，M2 调用方 `fetch_once.py` 不动）；传入时填 `raw/deduped/selected` 计数，供 daily-push job 写 `pushes.fetched_count/deduped_count` 用。

### 3.9（**重要行为提醒，不是决策**）**同一 thread_id 重复触发会复用 checkpoint 上下文**
来源：本会话 e2e 第三次触发的 3.7s 运行 + selected=10。生产无碍（每天不同 `daily_push:DATE`）；但**同日重触发** agent 不会重搜，直接从 checkpoint 里的早先 ToolMessage 取 papers 再发邮件——正是 11:00 补跑该有的语义。**别误以为是 bug。**

### 3.10 **Windows 主机跑 psycopg-async 必须 SelectorEventLoop**
来源：本会话 checkpointer 回归、`tests/test_m3_daily_push.py::_run`。容器是 Linux 无此事。host 测试用 `asyncio.Runner(loop_factory=asyncio.SelectorEventLoop)` 局部生效，不污染全局 event loop policy。M4 写跨平台调试脚本要记。

---

## 4. M3 累积 P1/P2 TODO（登记，**M4 不做**）

- **P0（开发末期处理）** `ANTHROPIC_API_KEY` + `API_TOKEN` 需轮换：本会话 `docker compose config` 把它们明文打进了会话记录（compose `environment:` 内联）。owner 已决定开发末期再轮换。同时 M6 P2 的 compose 硬化（端口 internal-only + 密码读 `.env` 而非 inline）届时一并处理。
- **P1** `create_react_agent` deprecated（V2.0 移除）；当 langgraph 出 1.2/2.0 接近时切到 `langchain.agents.create_agent`（+ `langchain` 全量包）。1 行 import 改动 + 1 个新依赖。
- **P1** Profile.md 仍空占位：M5 启动前手填基础画像做冷启动锚点，否则评分继续缺区分依据（M2 已观察到 8.0 同分趋同）。
- **P2** 邮件投递监控：本次首发 163→tju 成功收到，未观察到 spam；若后续运行进垃圾箱可考虑加 SPF/DKIM 头或换 SMTP 服务商。
- **P2** `scoring.py` system prompt 加评分锚点（9-10/7-8/5-6/0-4 分档）；本次 selected=10 评分有梯度（见 pushes.selected_papers）但仍可更细。
- **P2** test_m3_daily_push 跑在 dev DB（用 `run_date=2099-01-01` 隔离 + cleanup），无独立 test DB；M6/M7 可考虑分离。
- **环境提示**：本机 Windows 跑 pytest 仍需 `--basetemp=.pytest_tmp`；test_m1 有一条 newapi probe 关停时的 "access violation" 噪声（沙箱网络所致，handover §5 早登记，无影响）。docker `up -d --force-recreate api` 偶发 exit 139 segfault（本次实测一次），普通 restart 即恢复——Docker Desktop on Windows 已知偶发问题。
- **P1** `./memory/papers/2026-05-22/` 本次累积约 20-30 篇（多次测试触发各 10 篇去重后）——真实有效数据，不必清理。后续真 cron 跑当天若 thread_id 已被测试用过，agent 会复用 checkpoint（§3.9 行为）。

---

## 5. M3 实际工时 vs 估算（roadmap §9 DoD）

- **估算**：2.5 人天 = 15h（含 30% buffer）。
- **实际**：约 **13–14h**（焦点开发 ~11h + e2e/调试 ~3h），**基本贴预算**。超预算的非计划项：
  - langgraph 1.1.0/prebuilt 1.0.13 skew 发现+修+回归（~1h）
  - newapi 缓存探针 + 验收#8 改写 + token-log 加 4 字段（~0.5h）
  - SMTP 调试链：SMTP_TO 未落盘 → 配齐 → 587 STARTTLS 不通 → 改 465 SSL（~1h）
  - 必跑并发回归的 SelectorEventLoop/asyncio.Runner 设计（~0.5h）
- 在预算内能落地的减法红利：deepagents 一开始就丢、零依赖加 → 省下了 deepagents 引入 + langgraph 重 pin + checkpointer 回归的预期成本（按 deepagents 路估约 1d）。

---

## 6. M4 启动前需要 owner 拍板的事（只列问题，**答案留空**）

> 基于 `docs/05_roadmap.md` M4（对话 / 跨日召回 / 派生归档）。新会话开工前请 owner 逐条拍板。

1. `/chat` SSE 用 `sse-starlette`（CLAUDE.md §3 已为 M4 登记）？版本锁哪个？→ 答：______
2. session md **「派生写」时机**：每轮 done 后从 LangGraph state 取最近一轮 append 到 `./memory/sessions/{thread_id}.md`——是路由层钩子，还是中间件？还是包装 `agent.astream` 的迭代器？→ 答：______
3. M4 的 chat agent 复用 `build_lit_agent`（同 system prompt + skill）还是另起 `build_chat_agent`（不同 system prompt + memory_recall skill 而非 daily_search）？→ 答：______
4. 跨日召回：agent **判断要不要 grep** 时只看上下文？还是 system prompt 里给"先 try grep, no hit 再答"的硬规则？memory_recall skill 写法？→ 答：______
5. 中文 query 在英文库的召回率 evaluation——黄金集准备由 owner 给（用什么主题/几条）？→ 答：______
6. M4 给不给 agent `write_file` 工具？（M5 才画像自更新；M4 仅读？）→ 答：______
7. frontend `/chat` 流式：用 streamlit `st.chat_message` + `st.write_stream`？还是另起前端栈？→ 答：______
8. session 删除：API 提供 `DELETE /api/v1/sessions/{thread_id}` 同时删 LangGraph thread + session md 文件？→ 答：______
9. 故障恢复脚本（从 checkpoint 重建 session md）放 `scripts/` 还是 `src/.../tools/`？什么命令名？→ 答：______

---

## 7. 启动 M4 的第一条指令（给新会话）

> 你在推进「文献情报 Agent」项目的 M4（对话 / 跨日召回 / 派生归档）。唯一事实来源是 `docs/01~05`(v0.4) 与 `CLAUDE.md`；先读 `docs/handover/M3_to_M4.md` 了解 M3 已完成的事实与已拍板决策（尤其 §3 不要再争、§4 P0/P1 待办、§6 待 owner 拍板）。M3 端到端实活验证已绿（真 newapi + 真 SMTP，10 篇精选邮件 163→tju 已收到），9 个 commit 已落 main（最新 `ed55a08`）。M4 目标见 `docs/05 §5`：`/chat` SSE 流式问答 + 跨日 grep 召回 + 从 LangGraph state 派生写 session md。**先按 §6 把待拍板问题问 owner，确认后再写代码**；引入 `sse-starlette` 等新依赖前先报版本给 owner（贴 `pip index versions` 原文）。遵守减法精神：结构化交代码、模糊判断交 agent、能不加组件就不加。**绝不退回 deepagents、绝不写 cache_control（newapi 不透传）、绝不建 PG locks/jobstore 表。**
