# M5 Phase 1+2+3 ship handover

> 用途：下次会话拿不到本次聊天记录，靠本文件 + `docs/handover/M4_to_M5.md` + `docs/05_roadmap.md §6`
> + `CLAUDE.md` 接续 M5 后续（验收 / phase 4 评估 / 长尾验证）。
> 生成于 2026-05-26（M5 闭环主体 ship 后 + 时区 bug 修复 + cron 23:00 调整后）。

---

## 1. M5 当前状态

**主体闭环 ship 完成**。M4_to_M5 §5 P1 5 项启动前置 + M5 主体 6 commit（C1-C6）+ owner
要求的 3 个收尾改动全部落地，今日共 16 个 commit 进 main。

profile.md 自更新闭环具备能力（前提：容器 rebuild 拉新代码，等下次 cron 触发）：

```
每天 22:55  scheduler cron → derive_feedback_logs(days=30)
            读 PG feedback 表 → 按日期 group → atomic_write
            ./memory/feedback/{YYYY-MM-DD}.log
                  ↓
每天 23:00  scheduler cron → run_profile_update()
            build_lit_agent(skills=("profile_update",))
            → 拼写权 override prompt + 加 write_file_tool
            → agent 按 skill 7 步流程：
                read profile.md → list feedback/ → 读 30 天反馈
                → 对照 paper.md 抽关键词 → 增量改写 keyword_weights
                / negative_keywords / updated_at
            → write_file('./memory/profile/profile.md', new) 一次原子写
                  ↓
明早 10:00  scheduler cron → daily-push
            search_papers + scoring 用新 profile.md 推送
```

## 2. 8 个 A 类决策与 commit 映射（owner 拍板 + 调整后）

| 决策 | 选项 | 落地 commit |
|------|------|------------|
| **A1** profile 更新触发 | Daily cron **23:00**（owner 从 11:30 调整）独立跑，chat skills 不加 | C6 + 后续 chore(scheduler) commit |
| **A2** schema | 加 `negative_keywords: []` 最小够用 | C3 |
| **A3** 更新语义 | 增量改写 read-modify-write | C5 |
| **A4** feedback 派生 | Daily cron **22:55**（owner 从 03:00 调整配套）PG→文件批量 | C4 + 后续 chore(scheduler) commit |
| **A5** skill 字段范围 | 仅 `keyword_weights` / `negative_keywords` / `updated_at` | C5 |
| **A6** prompt 矛盾 | 条件性 prompt：profile_update 激活时拼写权 override | C2 |
| **A7** chat skills | 不加（A1 cron-only 已自动 resolve） | C2 |
| **A8** A/B 验收 | 离线分数对比（**未实现**，C7 留 phase 4） | ⏸️ pending |

## 3. 16 个 commit 时间线

```
907a0a9 chore(scheduler): profile-update cron 11:30 → 23:00 + feedback derive 03:00 → 22:55
8dc185c fix(session_md): 文件名 + frontmatter 时间戳从 UTC 改 Asia/Shanghai（owner bug 报告）
01e515c feat(scheduler): profile-update cron 11:30 触发 lit_agent(skills=("profile_update",))（M5 C6 / A1）
f69f6df feat(skill): profile_update.skill.md 字面填充（M5 C5 / A3+A5）
f4049c4 feat(scheduler): feedback PG → ./memory/feedback/{date}.log 派生 cron 03:00（M5 C4 / A4）
e62a87f feat(profile): schema 加 negative_keywords + scoring/search_papers 适配（M5 C3 / A2）
93f28a7 feat(agent): write_file_tool + build_lit_agent 条件性注册 + 条件性 prompt（M5 C2 / A6）
60219db chore(memory): add _WRITE_WHITELIST regex + 三处字面同步（M5 P1 ⑤ / 决策 A6 前置）
794f094 test(eval): write M5 P1 baseline report cn_recall (M5 P1 ④)
3de029a fix(eval): use query_zh / query_en for grep · align with v2 yaml schema
43b94b5 test(eval): defer expected_session_ids for cn_recall_gold per P1 ③ decision
03e890d fix(agent): ChatAnthropic streaming=True 补齐 docs/02 §A.2 字面要求（M5 P1 ②）
5c1d059 chore(lint): exclude vendor/ from ruff per CLAUDE.md §4 policy
b11a44c docs(known_issues): 登记 M5 P1 范围外的 2 条预存账单
a20837e test(mail): SMTP_TO env isolation 用 model_copy 显式置空（M5 P1 ①）
992d60b docs(handover): M4 → M5 完整版（含 owner demo 真测后的 7 个 bug-fix + PR-2）  ← M4 终
```

## 4. 已拍板决策（不要再争）

### 4.1 不走 M7 SQLite FTS5（owner 改路径，"跳过 M7 直接 M5"）

P1 ④ baseline 60% < 80% 触发了 owner 自己定的「立即停 M5 转 M7」灰区规则，但任务 A 归因
复核显示 **67% 失败属桶 2「跨语言同义词」（"锂金属" vs "lithium metal"）**，FTS5 单装解决
不了。owner 重审后认定 M5 主体跟 search_memory 召回率没有强依赖：

| 功能 | 是否依赖 search_memory | 60% 召回的影响 |
|------|----------------------|---------------|
| daily-push 推送主流程 | ❌ search_papers + scoring 与 search_memory 平行 | 0 |
| profile.md 读 | ❌ read_file 按已知路径 | 0 |
| profile.md 写（M5 主体） | ❌ read_file feedback log + atomic write | 0 |
| Haiku scoring 用 profile | ❌ 直接拼 prompt | 0 |
| chat 「我之前问过什么」类 | ✅ search_memory(scope=sessions) | 受 60% 拖累 |
| M5 验收硬指标「少推 X 次日生效」 | ❌ profile 直接生效到 search_papers | 0 |

→ M7 进 backlog，不阻塞 M5。等 M5 跑 7 天 / chat 用户痛点累积后再评估。

### 4.2 时区统一 Asia/Shanghai（owner bug 报告后修复，commit 8dc185c）

历史现存的 UTC 命名 session md（如 `2026-05-26/05-03-chat.md` 实为北京 13:03）
**不动**，留作历史归档。新会话从今天起：
- 路径：`./memory/sessions/{本地日期}/{本地HH-MM}-{trigger}.md`
- frontmatter：`started_at` / `last_active_at` 带 `+08:00` 后缀

`find_existing_by_thread` 按 thread_id 内容查找，不受路径命名变更影响。混合状态自然消化。

### 4.3 write_file 白名单严守 profile.md 单文件（M5 P1 ⑤，commit 60219db）

```python
_WRITE_WHITELIST = re.compile(r"^\./memory/profile/profile\.md$")
```

三处字面同步：
- `src/lit_agent/tools/memory.py::_WRITE_WHITELIST` 常量
- `CLAUDE.md §5` 写白名单段
- `docs/02 §3.4` 路径限定段

两层校验：`_resolve` 校 memory root（PathNotAllowed）→ canonical 绝对路径比对 profile.md
（PathNotWhitelistedError，PathNotAllowed 子类）。

基础设施代码（paper_md.atomic_write 写 paper.md / session.md / feedback log）直接绕过白名单
**专管 agent 写入口**。

### 4.4 条件性 prompt 解锁写权（A6，commit 93f28a7）

`_BASE_SYSTEM_PROMPT` 默认声明「你没有写文件的能力」。`build_lit_agent` 检测 skills 含
`profile_update` 时，prompt 末尾追加 `_PROFILE_UPDATE_WRITE_OVERRIDE` 段：
- 唯一允许 `write_file('./memory/profile/profile.md', new_content)`
- 必须 read-modify-write，绝不全量重写丢失累积偏好
- 字段限 `keyword_weights` / `negative_keywords` / `updated_at`
- 一会话至多写 1 次

daily-push / chat 主路径 skills 不含 profile_update → tools 仍是 M4 4 件套只读、prompt 仍
是默认禁写状态。

## 5. M4_to_M5 §5 P1 5 项清算

| # | task | 状态 | commit |
|---|------|------|--------|
| P1 ① | `tests/test_m3_mail.py::test_send_email_no_recipient_fail_fast` SMTP_TO env isolation | ✅ | a20837e |
| P1 ② | `ChatAnthropic streaming=True` 补齐 | ✅ | 03e890d |
| P1 ③ | 黄金集对话题 `expected_session_ids` 填写 | ✅ Option 1 留空 + 撂着 | 43b94b5 |
| P1 ④ | 跑 evaluation 出 M4 基线 | ✅ 60% paper Top-3 | 3de029a + 794f094 |
| P1 ⑤ | `write_file` 白名单三处同步 | ✅ 救活作为 M5 C1 | 60219db |

## 6. 验收路径（owner 手测，明日开始）

### 6.1 容器 rebuild（必须）

容器代码用 `uv sync --no-dev` 装的（Dockerfile:21），新代码要 rebuild 才进容器：

```powershell
cd D:/paper-agent
docker compose build api
docker compose up -d api
docker compose logs -f api  # 看 scheduler 启动日志，应看到 4 个 cron 注册
```

应该看到（structlog 输出）：
```
... scheduler_started jobs=4  ← daily_push, daily_push_retry, feedback_derive, profile_update
```

### 6.2 时区 fix 验证（最简单先验）

容器 rebuild 后任意 chat → 检查新 session md：

```powershell
ls D:/paper-agent/memory/sessions/2026-05-26/  # 看新文件名 = 北京 HH-MM
cat D:/paper-agent/memory/sessions/2026-05-26/<new-file>.md  # frontmatter +08:00
```

### 6.3 M5 闭环验证（等明日 23:00）

```powershell
# 明日 22:55 后
ls D:/paper-agent/memory/feedback/
# 应出现 2026-05-26.log（含 owner 今日所有 👍/👎 反馈）

# 明日 23:00 后
cat D:/paper-agent/memory/profile/profile.md
# 应看到：
# - updated_at: 从 1970-01-01 变成 2026-05-26T23:00:xx+08:00
# - keyword_weights: 从 {} 变成 {argyrodite: 0.XX, ...}
# - negative_keywords: 若 ≥ 3 篇 down 反馈累积触发，有新项
# - seed_queries / 画像摘要原样保留（A5 字段范围限定）
```

### 6.4 M5 长尾验收（7 天后）

docs/05 §6 字面硬指标：
- 30 条反馈后 `profile.md` 关键词/摘要更新到位（diff 可见）
- 有/无画像 Top-10 重合 ≤ 60%（A/B 评估，需 C7 脚本）
- 第 7 天 👍 率较第 1 天 +20%
- 用户说"少推液态添加剂"→次日生效

## 7. 未做事项（明确登记，不假装做了）

| 项 | 何时做 | 备注 |
|----|--------|------|
| **C7 A/B 离线评估脚本（A8）** | 后续 phase 4 | owner B5.2 拍今日不做；M5 跑几天有数据后再上 |
| **`frontend/pages/profile.py`** 只读展示页 | 任意时点独立 | docs/05 §6 task 3 字面要求 |
| **M7 SQLite FTS5** | M5 跑 7 天后评估 | owner 跳过；任务 A 归因报告显示 FTS5 单装救不了主因 |
| **历史 UTC session md 文件迁移** | 不做 | 4.2 决策留作历史归档；find_existing 按 thread_id 不受影响 |
| **handover `M5_to_M7_pivot.md`** | 不做 | owner 改路径「跳过 M7」后此 doc 作废，本文件替代 |
| **chat.py:14-19 stale comment 清理** | 任意时点独立 | P1 ② 后 stale，scope creep 单独立账 |

## 8. 已知未修预存账单（docs/known_issues/）

[docs/known_issues/windows_starlette_testclient.md](../known_issues/windows_starlette_testclient.md)
登记 2 条：

- **Bill 1**：Windows 本机 pytest native crash（starlette TestClient + anyio）→ M5 P1 用「定向验证」绕过
- **Bill 2**：`tests/test_m3_mail.py:68` `_Call | None` mypy union-attr 警告 → M3 既有，mypy src 全库不触发

新出现但未登记的：
- `scripts/eval_cn_recall.py:181` `sys.stdout.reconfigure  # type: ignore[union-attr]` 在 mypy 1.18+ 变 unused-ignore（仅 mypy 单查触发，mypy src 不触发）

## 9. 启动下次会话提示词

```
继续 M5 长尾验收 + 收尾。项目在 D:\paper-agent。

事实来源 + 必读顺序：
1. 先读 docs/handover/M5_phase_1_2_3_shipped.md —— 今日 ship 的 16 个 commit 事实 +
   决策 + 未做事项 + 验收路径
2. 再读 docs/handover/M4_to_M5.md —— M4 末态 + M5 启动前 P1 ⑤ 项处理记录
3. 再读 CLAUDE.md + docs/05 §6 —— 项目宪法 + M5 spec

今日（2026-05-26）状态：
- M5 闭环主体已 ship（16 个 commit 落 main，最新 907a0a9）
- 容器需 rebuild 拉新代码：docker compose build api && docker compose up -d api
- 等 22:55 + 23:00 cron 跑一轮看 profile.md 是否被自动更新
- A/B 评估脚本（C7）未做，留给本会话或后续

【绝不退回的硬约束】
- 不走 M7（owner 跳过；任务 A 归因报告说 FTS5 单装救不了主因）
- 写 profile.md 必须 read-modify-write 增量改写，禁全量重写
- agent 写白名单严守 ^\./memory/profile/profile\.md$
- 时间戳 / 文件名统一 Asia/Shanghai
- 3 表铁律 / chat 不加 profile_update / cron 23:00 不动

【今日可能要做】
- 看 22:55 + 23:00 cron 真跑后 profile.md 内容，确认 agent 按 skill 7 步流程跑通
- 如果跑通 → 开 C7 A/B 离线评估脚本，出第一份「有/无画像 Top-10 重合度」
- 如果跑不通 → 看 docker logs api 的 profile_update_failed 错误，debug
```

---

> v0.4 后续 / M5 ship 后的下一步：M5 长尾验收 + C7 A/B 评估 + M5 跑 7 天后再评估 M7。
