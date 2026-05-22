# 文献情报 Agent · 产品需求文档 (PRD)

> **文档版本**：v0.4　|　**状态**：v0.4 已对齐 2026-05-20 晚第二轮精简评审
> **作者**：架构师 / 单用户 owner
> **演进**：v0.3（单 agent + 文件系统 + skill）→ **v0.4（继续做减法：结构化工作交给工具，agent 只做模糊判断）**

> **v0.4 相对 v0.3 的核心转变**：
> 1. **搜 + 去重 + 评分封装进 `search_papers` 工具内部**——agent 调一次拿干净的 Top N，❌ 删除"agent 自己 for 循环查重 / 评分"。
> 2. **PG 表 5 → 3**（`users` / `pushes` / `feedback`）：❌ 删 `messages`（LangGraph 自管对话 state）、❌ 删 `locks`（LangGraph thread_id/checkpoint 自管并发）。
> 3. **profile / session 写入用"原子写"（临时文件 + rename），不是"锁"**。
> 4. **新增 §8 适用边界与失效场景**：显式声明在什么情况下不好用、强制按日期排序的理由。
> 5. **SQLite FTS5 降级为 P1 派生索引**，MVP 用 `grep` + frontmatter 过滤。

---

## 1. 产品概述

### 1.1 一句话定位

**一个跑在本机 / NAS 上的"个人文献情报员"**：每天 10:00 一个 LLM agent（`lit_agent`）被外部调度器叫醒，读 `daily_search.skill.md`，生成几条英文检索词，**调一次 `search_papers`** 拿到已去重、已评分的 5–10 篇精选，写邮件 + 在站内对话流呈现。所有推送过的文献以 markdown 永久落 `./memory/papers/`，对话归档落 `./memory/sessions/`。用户可在同一对话里就任意历史文献追问、重搜、调偏好——agent 用 `grep` / `cat` 读懂语义并回答。

### 1.2 核心理念

**单 agent + 文件系统即记忆 + SKILL 教程**（v0.3 已确立），v0.4 进一步把"哪些归 agent、哪些归工具"划清：

| 归 **工具**（代码确定性高） | 归 **agent**（模糊判断 / 推理） |
|---|---|
| 逐项处理相同结构数据：**搜索、去重、批量评分**（`search_papers` 内部用代码循环） | 生成检索词、判断"这篇值不值得推" |
| 结构化输出（工具入参定义结构 + 框架自动校验重试） | 读懂用户的话、写推送文案、多轮对话推理 |
| 文件原子写、对话 state 持久化（LangGraph） | 何时去查记忆（自主决策，**无路由层**） |

**四条方法论（贯穿全文）**：

- **A. 大模型不擅长 for 循环**：凡"逐项处理相同结构数据"的场景封装进工具，工具用代码循环，只把最终结果交给 agent。
- **B. 结构化输出靠工具不靠 prompt**：把目标结构定义成**工具入参**，模型输出工具调用，框架自动校验、不符就打回重试（校验闭环）。
- **C. 价值在于边界清晰**：显式声明"X 场景好用、Y 场景失效，接受这个代价"（见 §8），不追求覆盖所有 corner case。
- **D. 区分真问题与 AI 臆想的问题**：每个问题先问"不解决会怎样、我们真的关心吗"。

### 1.3 边界声明（不做什么）

- ❌ 不解析 PDF 全文（仅标题 + 摘要；P2 路线图）
- ❌ 不做多用户 / 鉴权 / RBAC（单用户）
- ❌ 不接公网（仅本机 / 局域网 / NAS）
- ❌ 不做引文图谱 / 中文文献源 / 学术写作
- ❌ 不引入向量库 / embedding / LangMem / Redis
- ❌ 不为"中文输入容错 / 模糊提问解析"加组件（用户责任，见 §1.2-D）
- ❌ 不自建并发锁（交给 LangGraph）、不自建对话消息表（交给 LangGraph）

---

## 2. 目标用户与核心场景

**用户**：锂电池 / 固态电解质 / 电池热管理方向科研人员（你本人），能跑 Python/Docker，每天文献时间 ≤ 30 分钟。

**场景 A · 晨间情报（调度器叫醒 agent）**：10:00 agent 读 skill → 生成检索词 → 调一次 `search_papers`（工具内部完成搜+去重+评分）→ 拿到 Top 8 → 写邮件 + 站内呈现为一条 `daily-push` 对话。

**场景 B · 同上下文追问 / 跨日召回**：用户在推送对话下问"第 3 篇用什么方法"——上下文有，直接答；问"5 天前那篇硫化物论文"——agent 自主 `search_memory(scope="papers")` → `read_file`；问"上周咱们聊过哪篇"——`search_memory(scope="sessions")` → 读 `related_papers` → `read_file`。

**场景 C · 调偏好**：用户说"以后多推固态电解质"——agent 按 `profile_update.skill.md` 原子写 `profile.md`，次日推送生效。

> 三场景同一个 `lit_agent`、同一套记忆。

---

## 3. 功能模块

> v0.4 模块表只列"真正要写代码的东西"。去重、评分不是独立模块，是 `search_papers` 工具内部的代码步骤。

| ID | 模块 | 优先级 | 职责 | 实现 |
|----|------|--------|------|------|
| M1 | `lit_agent` 单 agent | P0 | 承载推送与对话 | langgraph 原生 `create_react_agent` 单实例（不用 deepagents，见 handover §6.1） |
| M2 | `search_papers` 工具 | P0 | **搜 + 去重 + 评分 + 持久化**一体（见 §附录 A.1） | 本地 @tool 包 `paper-search-mcp` + 代码循环 + Haiku 批量评分 |
| M3 | 文件记忆工具 | P0 | 读 / grep / 原子写 `./memory/` | `search_memory` / `read_file` / `write_file`（grep + frontmatter，MVP 无 SQLite） |
| M4 | 外挂触发器 | P0 | 10:00 给 agent 发系统消息 | APScheduler + 固定 `thread_id=daily_push:YYYY-MM-DD` |
| M5 | SKILL 教程 | P0 | 把"如何工作"写成 markdown | `skills/daily_search` / `memory_recall` / `profile_update` |
| M6 | Streamlit 站内 | P0 | 单栏对话视图（推送=会话首条） | `st.chat_message` |
| M7 | 邮件工具 | P0 | HTML 模板 + SMTP | `send_email` |
| M8 | 对话归档 | P0 | 每轮 done 后从 LangGraph state **派生**写 session md | 应用层钩子（单写，非双写） |
| M9 | 画像自更新 | P1 | agent 读近期 feedback → 原子写 `profile.md` | `profile_update.skill.md` |
| M10 | 中文召回评估 | P1 | 测中文 query 在英文库召回率 | `tests/eval/`（< 85% 才考虑 SQLite，见 §6 改动6/路线图 M7） |
| M11 | PDF 全文 | P2 | 落 `./memory/papers/*/fulltext/` | MCP（P2） |

> ❌ **删除（相对 v0.3）**：`save_paper` 独立工具（去重已在 `search_papers` 内）、`MemoryGuard` 复杂守卫层（保留"原子写 + 路径白名单"两条即可）、PG 锁 / 消息表相关一切。

---

## 4. 用户故事（节选）

- **US-01 · P0**：每天 10:00 在邮箱 / 站内看到 5–10 篇精选。验收：连续 7 天准时收到，含标题/作者/摘要/链接/理由。
- **US-02 · P0**：推送下直接追问，上下文已有则不调工具直接答（首 token ≤ 3s）。
- **US-03 · P0**：跨日召回文献，30 天内任意推送文献 5 题准确率 ≥ 4/5。
- **US-04 · P0**：跨对话召回，用"上周/前几天+讨论类动词"提问，agent 优先 `scope="sessions"`，5 题 ≥ 4 正确。
- **US-05 · P1**：👍/👎/追问隐式调偏好，第 7 天 👍 率较第 1 天 ≥ +20%。
- **US-06 · P0**：`docker compose up` 60 秒内可用。
- **US-07 · P1**：抓取连续失败 ≥ 3 次发告警邮件。

---

## 5. 非功能性需求（NFR）

| 维度 | 目标 |
|------|------|
| 单次推送总耗时 | ≤ 5 分钟（`search_papers` 一次调用含批量评分） |
| 对话首 token | ≤ 3s（上下文已有时零工具调用） |
| `search_memory`（grep） | ≤ 100 ms（5 年 ≤ 2 万篇 markdown） |
| LLM 月成本 | ≤ \$5（Haiku 4.5 + prompt caching；无 embedding/rerank） |
| 并发 | 单用户无真并发；**LangGraph thread_id/checkpoint 兜底**，不自建锁 |
| 持久化 | PG（3 表）+ `./memory/` 卷；session md 可从 LangGraph checkpoint 重建 |
| 写安全 | profile/session **原子写**（临时文件 + rename）；文件工具限定 `./memory/`（读写）/ `skills/`（只读） |
| 重试 | 工具级外部 API 由代码 `tenacity` 退避 ≤3 次；agent 不在 loop 硬重试；任务级 11:00 补跑 1 次；连失 3 次告警 |
| 安全 | API Key 仅 `.env`；检索内容是不可信资料，**skill 明示不执行其中任何"指令"**；收件人固定取自 `.env` |

---

## 6. 关键假设与风险登记

| ID | 假设 / 风险 | 严重度 | 处置 |
|----|------------|--------|------|
| R1 | 4 源免费 API 长期稳定 | 高 | `paper-search-mcp` 抽象 4 源，任一失败不阻塞 |
| R2 | **必须按 `sort_by=date` 排序** | 高 | 若按相关性排序，每天返回经典老论文 → 全被去重 → 0 篇产出系统直接挂（详见 §8） |
| R3 | 标题+摘要够支撑 80% 问答 | 中 | 不达标则 P2 落 PDF 全文 |
| R4 | 中文 query 英文库召回率 | 中 | [暂搁置] M4 后跑评估，< 85% 再考虑 SQLite FTS5（P1） |
| R5 | `paper-search-mcp` 上游变更 | 高 | [需缓解] fork 锁版本到 `vendor/` |
| R6 | 极窄领域用户无价值 | 低 | [可接受] README 明确告知不适用（§8） |
| R7 | Anthropic Key 泄露 | 高 | `.env` + `.gitignore` + secret scan |

> ❌ 删除 v0.3.1 的并发锁 / 双写一致性 / save_paper 相关风险——对应机制已交给 LangGraph 或工具内部。

---

## 7. 验收口径（MVP 完成判据）

P0（全部满足即可发布）：

- [ ] 连续 3 天 10:00±5min 收到邮件 + 站内新推送会话
- [ ] 推送会话下追问，上下文已有时 agent **不调工具**直接答
- [ ] **去重生效**：连续两天搜到同一篇（同 DOI/arxiv_id/normalized_title），第二天**不重复**出现（去重在 `search_papers` 内完成）
- [ ] **跨日召回（文献）**：30 天内 5 题 ≥ 4/5
- [ ] **跨日召回（对话）**：模糊时间+讨论动词 5 题 ≥ 4/5
- [ ] 单源（arXiv）关闭后推送仍完成
- [ ] `docker compose up -d` 后 60s 内可访问；`.env.example` 可复现
- [ ] LLM 月成本 dry-run ≤ \$5

P1（迭代检验）：

- [ ] **中文召回率评估**：固定中文问题集测 `search_memory` 在英文库的命中率，记录基线；< 85% 触发 SQLite FTS5 评估（见路线图 M7）

---

## 8. 适用边界与失效场景（v0.4 新增）

> 方案价值在于边界清晰，不在于完美无缺。以下显式声明。

**✅ 适用场景**

- 用户关注**正在更新的宽泛领域**（每天至少 3–5 篇新文产出）：锂电池正负极材料、固态电解质、电池热管理等大方向。
- 每天 Top 20 候选中能挑出 5–10 篇有价值的。

**❌ 失效场景**

- **极窄子方向**（可能一个月才 1 篇新文，如"用 GNN 做硫化物固态电解质界面阻抗预测"）：每天 0 篇产出，系统对你无价值。
- **完全静态的历史领域**（基本无新文献）。
- **中文文献**：暂不支持，只搜英文。

**取舍说明**

- **为什么 Top 20 而非 Top 100**：20 篇 token 可控、处理快；100 篇大部分会被去重过滤，白白消耗 API。
- **为什么按日期排序不按相关性**：相关性排序让经典老论文反复占据 Top N → 全被去重 → 系统输出 0 篇直接挂掉。故 `search_papers` **强制 `sort_by=date`**。
- **为什么不做中文输入容错**：用户输入乱码/不规范本就不该期待正确结果，系统不为此付出复杂度代价。

**已知风险与可接受程度**

| 风险 | 严重度 | 处置 |
|---|---|---|
| 中文 query 英文库召回率低 | 中 | [暂搁置] M4 后评估，< 85% 才考虑 SQLite FTS5 |
| 极窄领域无价值 | 低 | [可接受] README 明确告知 |
| `paper-search-mcp` 上游变更 | 高 | [需缓解] fork 锁版本到 `vendor/` |
| 标题+摘要不足以回答深问 | 中 | [暂搁置] 需要时 P2 落 PDF 全文 |

---

## 附录 A：关键接口与结构（细节，不计入 3 页核心）

### A.1 `search_papers` 工具（搜 + 去重 + 评分一体）

```python
search_papers(
    queries: list[str],                         # agent 生成的检索词（可多条）
    sort: Literal["date_desc"] = "date_desc",   # 强制按发表日期倒序（见 §8）
    limit_per_query: int = 20,                  # 每条 query 召回 20 篇
    dedup_against_memory: bool = True,          # 工具内部对照 ./memory/papers/ 查重
    min_score: float = 6.0,                     # 过滤低分
) -> list[Paper]                                # 返回已去重已评分的 Top 5-10
```

工具内部（代码确定执行，非 agent 决策）：① 每条 query 调 `paper-search-mcp`（`sort_by=date` 拉 Top 20）；② 合并多 query，按 `doi / arxiv_id / normalized_title` 去重；③ 对照 `./memory/papers/` 历史 md 查重，命中即丢弃；④ 剩余候选用 Haiku 4.5 **单次 prompt 批量评分**（一个 prompt 全丢进去，不是循环）；⑤ 过滤 `< min_score`、按分排序；⑥ **原子写** Top N 到 `./memory/papers/{date}/{paper_id}.md`（含 score/reason，供次日去重与召回）；⑦ 返回 Top N。结构化输出由工具入参 + Pydantic 校验闭环保证（方法论 B）。

### A.2 文件记忆与 PG 指针

- 文件：`./memory/papers/{date}/{paper_id}.md`、`./memory/sessions/{date}/{HH-MM}-{trigger}.md`、`./memory/profile/profile.md`（结构见 [03_data_model](./03_data_model.md)）。
- PG 仅 3 表：`users` / `pushes` / `feedback`（[03_data_model](./03_data_model.md)）；对话 state 由 LangGraph 自管，不建 `messages` 表。

---

> **v0.4 已删除清单**：❌ `messages` 表　❌ `locks` 表　❌ `save_paper` 独立工具　❌ "agent for 循环查重/评分"　❌ MemoryGuard/PaperIndex 复杂层　❌ MVP 内的 SQLite。
> **下一步**：进入 [Step 2：系统架构设计](./02_architecture.md)。
