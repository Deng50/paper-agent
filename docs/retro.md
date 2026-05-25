# 里程碑回顾（retro）

> 每个里程碑一行：**实际工时 vs 估算**，超/欠的非计划项。
> 本文件自 M3 起开始填——M1/M2 完成时未记录，只回填已知事实。

---

## M1 · 地基与最小链路

- **估算**：1d。**实际**：未记录。
- **完成于**：commit `7b0d006`（`M1: 地基与最小链路 ...`）。
- **交付**：3 容器（postgres/api/frontend）+ PG 3 表（users/pushes/feedback）+ LangGraph 4 checkpoint 表 + `/health` `/status`（PG/memory/anthropic 三项绿、mcp degraded 待 M2）+ 401 RFC7807。Anthropic 经 newapi 中转接入。
- **遗留发现**（M3 才暴露）：M1 pin `langgraph==1.1.0` 与 `langgraph-prebuilt 1.0.13` runtime skew —— M1/M2 因从未 import `.prebuilt` 没踩到，M3 写 agent 时一 import 即 ImportError。M3 commit `a7be4c2` 升 1.1.10 修复。

## M2 · `search_papers` 工具 + 文件记忆

- **估算**：2d。**实际**：未记录。
- **完成于**：commits `8d3a17c → 2c03f2c`（vendor + tool + file memory + fetch_once）。
- **交付**：vendored `paper-search-mcp` 锁 `d438222`（3 个 patch）+ 4 源真实命中 + 三锚点去重 + 历史去重 + Haiku 批量评分 + 原子写 paper.md + 文件记忆 4 件（search_memory/read/write/list 含路径白名单）+ 17 passed。

## M3 · 每日推送闭环

- **估算**：2.5d = 15h。**实际**：约 **13–14h**，**贴预算**。
- **完成于**：commits `d3a8bda → ed55a08`（共 9 个，main 上）。
- **端到端实跑（2026-05-22）**：trigger 202 → 真 newapi Haiku → 10 篇精选 → 163→tju 邮件已收到。`pushes id=3` status=success、email_sent=t。token usage `in=29335/out=488/cache_read=0/cache_creation=0`，est_cost `$0.032`/次。
- **质量门禁**：`ruff` + `mypy src`（30 files）+ `pytest 22 passed`（M1/M2 的 17 无回归 + M3 新增 5；含必跑并发回归）。
- **超预算的非计划项**（约 +3h）：
  - langgraph/prebuilt skew 发现+修+回归（~1h）。
  - newapi 缓存不透传探针 + 验收#8 改 token 预算护栏 + token-log 加 cache 4 字段（~0.5h）。
  - SMTP 调试链：SMTP_TO 未落盘 → 配齐 → 587 STARTTLS 不通（163 不支持）→ 改 465 SSL（~1h）。
  - 必跑并发回归的 `SelectorEventLoop` + `asyncio.Runner` 设计（~0.5h）。
- **省下的预期成本**（减法红利约 -1d）：deepagents 一开始就丢、零依赖加；省下了 deepagents 引入 + langgraph 重 pin（按 deepagents 路径会顶 langchain 1.x 级联）+ checkpointer 回归的预期成本。
- **关键决策**（详见 `docs/handover/M3_to_M4.md §3`）：deepagents 整条路线图不用、`pushes` 表做 thread-busy 闸（无 locks 表）、邮件归 app 层（agent 工具只读三件套）、newapi 无缓存→不写 `cache_control`。
- **遗留 P0**：`ANTHROPIC_API_KEY` + `API_TOKEN` 待轮换（compose config 暴露事故；owner 决定开发末期处理）。
