# 文献情报 Agent · Landing Project项目内部分享

> **作者**：lvqingfang
> **项目状态**：M5 主体闭环已 ship，单用户日常运行，未上线公网
> **代码位置**：`D:/paper-agent`

---

## 一、项目背景

### 1.1 一句话定位

**一个跑在本机 / NAS 上的「个人文献情报员」**：每天早上 10:00 自动到 4 个学术源（arXiv / Semantic Scholar / Crossref / OpenAlex）拉取**锂电池 / 固态电解质 / 电池热管理**默认方向的最新论文，经过去重 + LLM 打分，筛出 10 篇精选推送到邮箱，并在 Web 前端界面以会话形式呈现。用户可以在同一会话里**自然语言追问**任意历史推送，agent 自主用 `grep` 翻档案回答。

### 1.2 为什么做这个

- **个人痛点**：实验室每天要刷 4-5 个学术源，时间成本高 + 容易遗漏
- **方向探索**：探索 LLM agent 在单用户科研场景的落地形态：每天定时、自主搜文献、主动推送文献并回答人类问题无限轮对话、持久化上下文、自我更新记忆（感兴趣的文献领域）、技术栈：langgraph，python、轻量化的前端界面、plantfrom接口层
- **技术兴趣**：「**让 agent 长期学习用户偏好**」是个真有意思的工程问题——靠不靠谱、能不能省 token、要不要上向量库

### 1.3 项目范围（**显式声明不做什么**）

| ❌ 不做 | 原因 |
|---|---|
| 不解析 PDF 全文 | MVP 用 title + abstract 已能覆盖 80% 提问，PDF 留 P2 |
| 不做多用户 / 鉴权 / RBAC | 单用户场景，省一堆复杂度 |
| 不接公网 | 仅本机 / 局域网 部署 |
| 不引入向量库 / embedding / Redis | 5 年 ≤ 2 万篇 markdown，grep < 100ms 够用 |
| 不为「中文输入容错」加组件 | 用户输入乱码不该期待正确结果，不为此付复杂度代价 |
| 不自建并发锁、不建对话消息表 | 交给 LangGraph 框架原生能力 |

**边界清晰** > 试图覆盖所有 corner case，这是项目的核心设计哲学之一。

---

## 二、产品形态与效果

### 2.1 三个核心用户场景（对应 PRD §2）

| 场景 | 触发方式 | 用户体验 |
|------|---------|---------|
| **A · 晨间情报** | 10:00 cron 自动 | 邮箱收到 10 篇精选 + 站内出现一条 `daily-push` 会话 |
| **B · 同上下文追问 / 跨日召回** | 用户 chat 提问 | agent 自主决定是否查档案、走哪个 scope，带引用回答 |
| **C · chat 调偏好（M5 强化）** | 用户在 chat 表达「重新检索 / 换一批 / 不满意」 | agent 调统一 push pipeline，重新搜+评分+发邮件+更新前端 |

三场景共用**同一个** `lit_agent`、同一套记忆。

### 2.2 当前真实运行数据

| 指标 | 当前值 |
|------|--------|
| 推送累积天数 | 4 天（demo 阶段，真生产即将开始） |
| 历史 paper.md 档案 | ~180 篇（含跨日去重已生效） |
| chat 会话归档 | 10+ 条 |
| 偏好画像 keyword_weights | **11 个真关键词**（固态电池 +0.40 最高，从 27 条反馈聚合而来） |
| 月度 LLM 成本 dry-run | < $1（预算上限 $5） |
| 单次推送总耗时 | ~180 秒 |
| 容器数 | 3 个（api / frontend / postgres） |

---

## 三、设计哲学：四条方法论

这套方法论从 PRD §1.2 起就明确定义，**贯穿全项目所有设计决策**。

### 方法论 A：**大模型不擅长 for 循环**

凡「逐项处理相同结构数据」的场景**封装进工具**，工具用代码循环，只把最终结果交给 agent。

**实战**：`search_papers` 工具（`src/lit_agent/tools/search_papers.py`）内部一次性完成「搜 → 去重 → 评分 → 落盘」4 步，agent **只调一次**拿干净结果。**绝不让 agent 自己 for 循环逐篇查重 / 评分**——既烧 token 又容易幻觉。

**去重**：批内去重（同次搜索内）：4 源会返回同一篇 paper 多次（DOI 一致），先合并去重；   历史去重（跨日，关键防昨天推过的今天再推）：读每个 paper.md 的 frontmatter 取 3 锚点（doi / arxiv_id / normalized_title）

### 方法论 B：**结构化输出靠工具不靠 prompt**

把目标结构定义成**工具入参 schema** + **Pydantic 校验**，模型输出工具调用，框架自动校验、不符就把错误打回重试（**校验闭环**）。

**实战**：评分工具 `tools/scoring.py` 用 Anthropic `tool_use` + Pydantic `ScoreBatch` schema 校验输出，**不靠 prompt 逼模型吐 JSON**。

### 方法论 C：**价值在于边界清晰**

显式声明「X 场景好用、Y 场景失效，接受这个代价」，不追求覆盖所有 corner case。

**实战**：PRD §8 显式列出失效场景（极窄子方向 / 静态历史领域 / 中文文献源），README 明确告知不适用。**不为低价值场景付出工程复杂度**。

### 方法论 D：**区分真问题与 AI 臆想的问题**

每个新需求 / 新组件先问：「不解决会怎样？这种失败能接受吗？」答案是「能接受」就不加。

**实战**：v0.4 相对 v0.3 删除清单——`save_paper` 独立工具 / `MemoryGuard` 守卫层 / PG `locks` 表 / PG `messages` 表 / MVP 内的 SQLite。**每一个删除都对应一次「不加会怎样失败」的拷问**。

---

## 四、系统架构

### 4.1 分层

```
┌─────────────────────────────────────────────────────────┐
│  用户 ｜ 邮箱 ｜ 调度器（APScheduler 4 个 cron）          │
└───────────────────────┬─────────────────────────────────┘
                        ↓
                 lit_agent（单 agent）
                ┌───────┴───────┐
                ↓               ↓
          SKILL 教程         工具（4 件套）
       （markdown 文件）  search_papers / read_file /
                         search_memory / list_dir
                +条件性工具：write_file / trigger_push_pipeline
                                ↓
        ┌───────────────┬───────┴───────┬─────────────┐
        ↓               ↓               ↓             ↓
  ./memory/*.md   PostgreSQL 3 表    LangGraph     外部 API
  （文件即记忆）  users/pushes/      自管表        Anthropic /
                feedback           （checkpoint） 4 学术源 / SMTP
```

### 4.2 部署拓扑（3 容器）

| 容器 | 服务 | 端口 |
|------|------|------|
| `paper-agent-api` | FastAPI + APScheduler + paper-search-mcp 子进程 | 8000 |
| `paper-agent-frontend` | Streamlit 单栏对话视图 | 8501 |
| `paper-agent-postgres` | PostgreSQL 17 | 5432 |

`docker compose up -d` 一键启动，60 秒内可用。

### 4.3 4 个核心 cron 任务

| 时间 | 任务 | 作用 |
|------|------|------|
| 10:00 | `daily_push` | 主推送（agent 调 search_papers → 邮件 + 写 pushes） |
| 11:00 | `daily_push_retry` | 10:00 失败时补跑 |
| 22:55 | `feedback_derive` | PG `feedback` 表派生为 `./memory/feedback/{date}.log` |
| 23:00 | `profile_update` | agent 读近 30 天反馈 → 增量改写 `./memory/profile/profile.md` |

**为什么 22:55 → 23:00 错峰**：今天反馈 22:55 落 log，23:00 进画像，**明早 10:00 推送直接用新画像**。整个反馈→生效链路约 11 小时。

---

## 五、关键设计决策

### 5.1 文件系统即记忆，不上向量库

**论点**：单用户场景 5 年累积 ≤ 2 万篇 markdown，`grep` < 100ms 已够用。markdown 既是存储又是 agent 能读懂的语义载体，还能手改、git diff、肉眼可读。

**取舍**：放弃语义近义召回能力（如「argyrodite ⇄ 硫银锗矿」），但获得：
- 零外部依赖
- 数据归用户所有（markdown 文件可直接备份）
- 调试和审计容易（cat 一下就知道 agent 看到什么）

**SQLite FTS5 备选**：仅当中文召回率 < 85% 才考虑作为「派生索引」启用，非数据库。

### 5.2 PostgreSQL 只 3 张表（铁律）

仅 `users` / `pushes` / `feedback`，**故意省略**：
- ~~`messages`~~ → 对话状态由 LangGraph checkpoint 自管
- ~~`locks`~~ → 并发隔离由 LangGraph thread_id + `UniqueConstraint(user_id, run_date)` 保证
- ~~`sessions`~~ → 会话归档落 `./memory/sessions/*.md`
- ~~`events` / `job_logs`~~ → structlog 输出到容器 log

**3 表保留的理由**：关系数据库擅长**日期范围、状态过滤、按 paper_id / signal_type 索引统计**。文件系统不擅长这些。其它能力都不需要表。

### 5.3 单 agent + SKILL 教程模式

整个项目只有**一个** `lit_agent`（基于 `langgraph.prebuilt.create_react_agent` + `ChatAnthropic`）。推送、对话、画像自更新**共用同一个 agent**，仅通过传入不同 `skills` 列表激活不同行为：

```python
# 每日推送 cron
agent = build_lit_agent(skills=("daily_search",))

# /chat 路由
agent = build_lit_agent(skills=("daily_search", "memory_recall"), chat_session_id=...)

# 23:00 profile_update cron
agent = build_lit_agent(skills=("profile_update",))
```

**SKILL = `skills/*.skill.md`**，是 markdown 文件而非 Python 代码。agent 启动时把对应 skill 全文拼入 system prompt，**改逻辑 = 改 markdown，不改代码**。

**为什么不用 deepagents**：deepagents 引入 planning agent、子 agent、虚拟文件系统。我们这只有一个用户、一个 agent、真文件系统，**所有概念都映射不上**。用框架原生 `create_react_agent` 反而更简洁。

### 5.4 条件性 tool 注册 + 条件性 prompt（M5 P1 ⑤ 安全护栏）

agent 默认 4 件套**只读**（`search_papers / read_file / search_memory / list_dir`）。
仅在特定 skill 激活时**有条件解锁写权**：

| 触发条件 | 解锁工具 | 路径白名单 |
|---------|---------|----------|
| `skills` 含 `profile_update` | `write_file_tool` | 仅 `^\./memory/profile/profile\.md$` |
| `chat_session_id` 非 None | `trigger_push_pipeline_tool` | 触发完整 push pipeline |

**两层校验防 agent 越权**：
1. `_resolve()` 校 memory root → `PathNotAllowed`
2. canonical 绝对路径比对 → `PathNotWhitelistedError`（`PathNotAllowed` 子类）

任何超出白名单的写操作 → raise 异常 → tool 返回 error → agent 收到反馈知道做错了。

### 5.5 原子写 ≠ 锁

`profile.md` 和 session md 用 POSIX 原子语义写：

```python
def atomic_write(path, content):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)   # 原子 rename
```

**要么完整旧文件、要么完整新文件，绝不留半截损坏文件**。单用户场景无真并发，根本不需要锁。

---

## 六、开发节奏：5 个里程碑

| ID | 名称 | 估算 | 状态 | 关键产出 |
|----|------|------|------|---------|
| **M1** | 地基与最小链路 | 1d | ✅ | docker compose / 3 表 / `/status` 健康检查 |
| **M2** | search_papers 工具 + 文件记忆 | 2d | ✅ | 4 源抓取 + 3 锚点去重 + Haiku 批量评分 + 原子写 |
| **M3** | 每日推送闭环 | 2.5d | ✅ | 10:00 cron / 邮件 / pushes 审计 |
| **M4** | 对话 / 跨日召回 / 派生归档 | 3d | ✅ | `/chat` SSE / session md / 历史会话切换 |
| **M5** | 画像自更新 | 1d 估算 → 实际 2d | ✅ | feedback 派生 + 23:00 cron + agent 增量改写 profile + chat-rerun 通路 |
| **M6** | 鲁棒 / 可观测 / 备份 | 2d | ⏸️ 待启动 | tenacity 退避 / 告警邮件 / pg_dump / Runbook |
| **M7** | P2 探索（PDF / SQLite FTS5）| — | ⏸️ Backlog | 视触发条件评估 |

**先骨头后肉**原则：每个里程碑先 end-to-end 跑通，再回填实现细节。

---

## 七、几个有意思的踩坑

### 坑 1：中文召回率 60%，但**不是技术问题，是「中英语言鸿沟」**

跑评估脚本 `scripts/eval_cn_recall.py`：用户中文 query「上周那篇硫化物固态电解质用什么表征」能不能找到对应 paper.md？结果 **paper Top-3 = 60%**，离 80% 阈值差 20 个百分点。

按预设规则触发「上 SQLite FTS5 全文索引」工程方案，预估 1 人天。**但没立即动工**，先做了 1 小时归因复核：

**归因结论**（4 桶分类）：

- 桶 1 词项失配（FTS5 强项）：**0/3 = 0%**
- 桶 2 跨语言同义词（FTS5 救不了）：**2/3 = 67% ← 主导**
- 桶 3 嵌入弱：0%
- 桶 4 黄金集数据 bug：33%

**具体证据**：
- 用户问「锂金属」（中文连写），corpus 写 `lithium metal` / `lithium-metal`（英文带空格/连字符）→ 字面对不上 → grep 0 命中
- 用户问「聚合物」，corpus 写 `polymer` / `Poly(Vinylidene Fluoride)` → 跨语言对不上

**FTS5 装上去能解决多少**：仅救 EN query 那侧的桶 1，对主口径 ZH query 几乎无帮助。**1 人天投下去召回率涨 5-10 个百分点就到顶**。

**最终采用方案 = 0 代码改动**：仅在 `skills/memory_recall.skill.md` 加**中英对照词表 + 强制双跑硬约束**，让 agent 收到中文 query 时自动生成 2-3 条英文 query，并跑 `search_memory`。
- 成本：+200 input + 50 output tokens/chat ≈ **+$0.14/月（可忽略）**
- 预估效果：60% → 80%+

**学到的事**：**指标过线想 RUSH 工程方案前，先 1 小时归因**。归因发现工程方案打不准靶心，省下的 1 天 = 净赚。

### 坑 2：所有时间戳差 8 小时

某次在北京时间 15:20 跟 agent 聊天，归档文件名是 `07-20-chat.md` —— **整整差 8 小时**。

排查到根因：

```python
# src/lit_agent/tools/session_md.py:198 (修复前)
now = now or dt.datetime.now(dt.UTC)
# ...
hm_str = now.strftime("%H-%M")   # ← UTC 时间写文件名
```

**bug 隐藏得深**：
- 本地开发 `datetime.now()` 默认 naive，看起来正常
- 跑进容器后才走 UTC（容器默认 UTC）
- 文件名 `07-20-chat.md` 看起来像「真有人凌晨 7:20 跟我聊过」，**不会立即觉得是 bug**

修复 1 行：

```python
now_local = now.astimezone(ZoneInfo(settings.timezone))
```

**学到的事**：**任何处理时间的代码第一行必须显式声明时区**，naive datetime 在「本地开发 vs 容器」跨环境一定会出事。

### 坑 3：架构反转——从「Path A 拒绝」到「Path B 完整 pipeline」

owner 报告：chat 里用户说「这批不感兴趣，重新检索一批」时，agent 偷偷调 `search_papers` 落 paper.md 到 memory，**但邮件没发、pushes 表没写、前端「每日推送」看不到** → 状态严重不一致。

**我第一版修复方向（Path A）**：扩拒绝启发式，让 agent 看到「重新检索 / 重新搜 / 换一批」就拒绝调用工具，引导用户去前端按钮触发。

**owner 反驳**：这个方向是错的。**砍掉合理用户体验**——「在 chat 里说就能完成」本身是产品意图，不该强制走按钮。bug 真正的根因是「**search_papers 工具不写 pushes 不发邮件**」，不是「agent 不该被调」。

**第二版修复（Path B 正确方向）**：
1. 加新工具 `trigger_push_pipeline(topic_override)`，**复用既有 `run_daily_push`**
2. 修改 `run_daily_push` 加 `topic_override` 参数，把用户在 chat 提的方向注入 kickoff prompt
3. chat 收到 rerun 意图 → agent 调新工具 → 走完整 pipeline：清当天 checkpoint → 重搜 → 覆盖 pushes 行 → 发邮件 → 落 paper.md → 返回给 chat
4. 3 个入口（10:00 cron / 前端按钮 / chat-rerun）**收敛到同一个 pipeline**，trigger 字段区分

**学到的事**：**解决症状不解决根因 = 错方向**。「禁止 agent 行动」是用 prompt 约束 LLM，不可靠；「补完 agent 调的 pipeline 让它一致」是用工程约束 LLM，可靠。

---

## 八、项目数据

| 维度 | 数字 |
|------|------|
| **代码量** | ~5000 行 Python + ~30 个测试文件 |
| **commit 数** | 50+ 个（M1-M5 全部产出） |
| **依赖数** | 主依赖 < 20 个（langgraph / langchain-anthropic / fastapi / sqlalchemy / streamlit / apscheduler / aiosmtplib / pydantic 等）|
| **PG 表数** | 3 张（铁律）|
| **agent 工具数** | 4 默认 + 2 条件性 |
| **skill 文件数** | 3 个（daily_search / memory_recall / profile_update） |
| **月度 LLM 成本** | dry-run < $1（上限 $5） |
| **容器数** | 3 个 |
| **部署成本** | 单机 Docker，无云服务，0 月费 |
| **当前画像关键词数** | 11 个真实关键词（从 27 条反馈聚合） |
| **依赖 vendored 包** | `paper-search-mcp` fork 锁版本 |

---

## 附：演示路径（如需现场 demo）

1. **看推送**：打开 `http://localhost:8501` → 「📬 每日推送」tab → 选今天那期，展开 10 篇精选卡片，每张可点 👍 / 👎
2. **看 chat**：「💬 chat」tab → 输入「之前关于硫化物固态电解质的论文」→ 看 SSE 流，agent 自主调 `search_memory` 中英双跑，带引用回答
3. **触发 chat-rerun**：「这批不感兴趣，帮我搜固态电池的」→ agent 调 `trigger_push_pipeline(topic_override="固态电池")` → 30-60 秒后回复，邮箱收到新一批，前端「每日推送」状态更新为 `chat_rerun`
4. **看画像**：`cat D:/paper-agent/memory/profile/profile.md` → 看 11 个真关键词 + 权重
5. **看一条 paper.md**：`cat D:/paper-agent/memory/papers/2026-05-26/<某 paper_id>.md` → 看 frontmatter 含 3 锚点（doi / arxiv_id / normalized_title）+ 中文 reason

---

**感谢倾听 / Q&A** ✌️
