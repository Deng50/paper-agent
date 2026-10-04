# Paper Agent：个人论文检索与每日推荐助手

面向本机或 NAS 部署的**单用户文献情报助手**。基于 LangGraph、FastAPI、Streamlit 和 PostgreSQL，从多个论文源获取元数据，自动去重、评分和保存，每日生成站内推荐与邮件；支持对历史论文继续追问、重新检索以及通过反馈调整研究偏好。

默认研究方向为锂电池、固态电解质和电池热管理，可在初始画像中修改。适合持续有新论文的较宽研究领域；当前接入以英文元数据为主，未提供中文文献源或 PDF 全文问答。

## 功能概况

| 功能 | 当前能力 |
| --- | --- |
| 多源检索 | 接入 arXiv、Semantic Scholar、Crossref、OpenAlex 四个来源 |
| 精选与去重 | 规范 DOI/arXiv 标识，跨来源与历史记忆去重，批量模型评分并校验结果完整性 |
| 每日推送 | 按配置时区定时执行，可手动触发与强制重跑；站内会话、Markdown 归档和 SMTP 邮件 |
| 对话追问 | 模型流式回答，读取论文与历史会话记忆，支持对话中重新检索 |
| 文件记忆 | 论文、会话、画像与反馈日志分目录保存；并发原子写入、会话标题和归档恢复 |
| 论文浏览接口 | 论文筛选、游标分页、详情及关联会话 `cited_in` 查询 |
| 偏好反馈 | 点赞/点踩、反馈类型与原因；定时派生反馈日志并更新画像，前端提供只读画像页 |
| 运行诊断 | 身份认证、依赖状态、调度状态及推送成功/部分成功/失败记录 |

### 2026-10-04 完善内容

- 补齐论文记忆 API、画像读取 API 和只读画像页面。
- 修复中文 SSE 跨块解码、非即时输出及工具中断识别问题。
- 修复并发文件写入、同分钟归档覆盖、检查点重建残留，以及聊天内重跑破坏当前会话的问题。
- 完善推送重试领取、邮件失败后站内内容保留、评分结果完整性与来源故障传播。
- 修复连接串驱动、配置时区和部分可选上游解析问题。详见 [完整审查报告](docs/audit-2026-10-04.md)。

## 架构与数据位置

```text
Streamlit 页面 → FastAPI → LangGraph 对话/推送流程
                             ├─ 四源搜索 → 去重 → 评分 → 论文 Markdown
                             ├─ 历史记忆与流式回答
                             └─ 站内推送 / SMTP 邮件

PostgreSQL：用户、推送记录、反馈、LangGraph 检查点
memory/：papers/、sessions/、profile/、feedback/
skills/：每日检索、历史召回、画像更新的流程说明
```

当前没有 Redis、向量数据库或独立 MCP 服务依赖。`vendor/paper-search-mcp` 作为本地 Python 包复用，主项目只启用上述四源的元数据搜索能力。

## 快速开始：Docker Compose

需要 Docker 与 Compose v2、可访问的论文源和有效模型/搜索凭据。项目**没有可替代真实服务的完整 Fake 演示模式**。以下配置命令使用 Windows PowerShell；Linux/macOS 可将 `Copy-Item` 替换为 `cp`。

### 1. 获取项目并配置环境

```powershell
git clone https://github.com/Deng50/paper-agent.git
cd paper-agent
Copy-Item .env.example .env
```

已有仓库时跳过克隆；已有 `.env` 时直接编辑，不要覆盖原配置。按 [.env.example](.env.example) 填写：

| 变量 | 用途与要求 |
| --- | --- |
| `API_TOKEN` | 前后端共用的 Bearer Token，替换示例值 |
| `ANTHROPIC_API_KEY` | 对话、评分及画像任务所用模型凭据 |
| `SEMANTIC_SCHOLAR_API_KEY` | 必填搜索源密钥，也兼容 `S2_API_KEY` |
| `DATABASE_URL` | Compose 内使用 `postgresql+psycopg://lit:lit@postgres:5432/lit_agent`；本机进程改为 `localhost` |
| `USER_EMAIL` | 单用户身份配置 |
| `TIMEZONE` | 默认 `Asia/Shanghai`，必须是合法 IANA 时区 |
| `DAILY_PUSH_HOUR` | 默认每天 10 点执行推送 |
| `DAILY_PUSH_RETRY_HOUR` | 默认 11 点重试失败推送，可自行添加到 `.env` |
| `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`、`SMTP_TO` | 接收邮件时配置；收件人固定从配置读取，多个地址以逗号分隔 |
| `ANTHROPIC_BASE_URL` | 可选兼容网关根地址，不带 `/v1`；留空使用默认服务 |

这些凭据必须在实际服务中有效，仅填非空占位文字无法完成检索和模型调用。模型请求、评分和状态探针可能产生服务费用。

### 2. 启动与检查

```powershell
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 api
```

Compose 会启动 `postgres`、`api` 和 `frontend`。API 启动命令会先初始化记忆目录并运行 Alembic 迁移，数据保存在 PostgreSQL 卷与宿主机 `./memory/`。

- [页面入口](http://localhost:8501)：每日推送、系统状态，以及侧边栏聊天和画像页面。
- [API 文档](http://localhost:8000/docs)：仅 `ENV=dev` 时开放。
- [存活检查](http://localhost:8000/health)：存活不代表模型、数据库和搜索源全部可用，请同时检查页面“系统状态”。

## 第一次使用

1. 在“系统状态”检查数据库、模型和调度器状态；如有失败，先检查 `.env` 和 API 日志。
2. 初次初始化后，可编辑 `memory/profile/profile.md` 的 `seed_queries` 为自己的英文研究方向，保留 YAML 格式。默认内容是电池方向的起始画像。
3. 在“每日推送”点击“立即触发一次推送”，等待后台检索、去重和评分，然后刷新查看结果。
4. 阅读精选论文并提交点赞/点踩，可以补充原因；在聊天页面继续提问，例如“总结今天推荐的固态电解质论文”。
5. 在画像页查看当前关键词权重、排除方向和初始检索词。该页面只读；反馈由晚间任务用于更新后续推荐。

“强制重跑”会重新搜索、评分并可能再次发邮件。邮件发送失败时，已生成的摘要与会话可保留为部分成功，应查看具体状态和错误，而不是只检查是否收到邮件。

## 定时任务

以下时间按 `TIMEZONE` 解释：

| 时间 | 行为 |
| --- | --- |
| 10:00（可配置） | 每日论文推送 |
| 11:00（可配置） | 推送失败重试 |
| 22:55 | 将数据库反馈派生为文件日志 |
| 23:00 | 基于反馈更新偏好画像，供次日检索使用 |

调度器运行在 API 进程内，API 必须持续运行。当前不保证断电或进程被硬杀后自动补齐所有遗漏任务，也不应直接以多个 API 实例重复运行同一调度器。

## 本地开发：Python 3.12 + uv

在仓库根目录配置好 `.env`，将 `DATABASE_URL` 的主机改为 `localhost`。仅启动数据库，然后安装锁定依赖：

```powershell
docker compose up -d postgres
python -m pip install uv
uv sync --locked --extra dev
uv run python scripts/init_memory.py
uv run alembic upgrade head
uv run uvicorn lit_agent.api.main:app --reload --port 8000
```

在第二个终端进入同一仓库启动界面：

```powershell
$env:API_BASE_URL = "http://localhost:8000"
uv run streamlit run src/lit_agent/frontend/app.py --server.port 8501
```

前端会读取 `.env` 中的 `API_TOKEN`。不要同时启动占用相同端口的容器 API/前端与本机 API/前端。

只想手动检索一次，可运行：

```powershell
uv run python -m scripts.fetch_once --queries "solid electrolyte" "battery thermal management" --limit 10
```

该命令真实调用论文源和模型评分，并将精选保存到 `memory/papers/`，不会代替完整每日邮件推送流程。

## 常用 API

除公开健康接口外，业务请求需附带 `Authorization: Bearer <API_TOKEN>`。

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/status` | 服务依赖与调度状态 |
| `POST /api/v1/admin/trigger/daily-push` | 触发每日推送，可传 `{"force": true}` 强制重跑 |
| `GET /api/v1/sessions`、`GET /api/v1/sessions/{run_date}` | 每日推送列表与详情 |
| `POST /api/v1/chat` | 流式对话 |
| `GET /api/v1/chat/sessions`、`GET /api/v1/chat/sessions/{thread_id}/messages` | 聊天会话与消息 |
| `POST /api/v1/feedback` | 保存偏好反馈 |
| `GET /api/v1/memory/papers` | 按关键词、日期、来源筛选，使用游标分页 |
| `GET /api/v1/memory/papers/{paper_id}` | 论文正文记忆与关联会话 |
| `GET /api/v1/memory/profile` | 只读画像 |

更多字段和会话管理接口见运行后的 API 文档。

## 项目目录

```text
src/lit_agent/api/          HTTP API、鉴权与异常处理
src/lit_agent/agents/       对话和任务 Agent
src/lit_agent/tools/        搜索、评分、文件记忆及模型工具
src/lit_agent/scheduler/    定时推送、反馈派生和画像任务
src/lit_agent/frontend/     Streamlit 页面
alembic/                   数据库迁移
scripts/                   初始化、单次检索、探针及归档恢复
skills/                    Agent 流程说明
vendor/paper-search-mcp/    固定的上游元数据连接器及本地补丁
tests/                     主项目回归用例
memory/                    本地论文、会话、画像和反馈
docs/                      需求、架构、路线图和审查报告
```

## 测试与质量检查

```powershell
uv sync --locked --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

2026-10-04 审查时：主测试 **121 项通过、4 项跳过**，额外上游离线测试 **16 项通过**；静态、格式、类型和 135 个 Python 文件语法检查通过。跳过项为 3 项真实 PostgreSQL 测试和 1 项需要 Windows 符号链接权限的测试。

数据库测试必须显式设置 `TEST_DATABASE_URL`，且数据库名以 `_test` 结尾。不要将开发或生产数据库作为测试库。

## 常见问题与当前限制

- **401**：检查前端和 API 是否使用同一个 token；容器修改 `.env` 后需重新创建相关服务以载入新变量。
- **数据库连接失败**：容器使用主机名 `postgres`，本机程序使用 `localhost`，并确认已运行迁移。
- **没有推荐结果**：检查源服务错误、限流和检索范围；全部来源失败会明确报错，不再被当成正常空结果。
- **站内有结果但没有邮件**：检查 SMTP 配置和推送状态；站内归档与邮件成功是两件不同的事。
- **新画像没有立即影响结果**：默认反馈与画像在晚间处理，次日推送使用更新后的画像。
- 当前为单用户项目，未实现多租户管理、PDF 全文 RAG、中文文献源及全部上游连接器；ACM/IEEE 等可选模块仍有占位实现。
- A/B 画像评估、自动备份/恢复演练、持续失败告警和硬中断任务自动恢复尚未完整实现。
- 真实 PostgreSQL/SMTP/模型、四源网络调用、浏览器交互和长期调度仍需部署验收。备份应同时保存数据库和 `memory/`，仅推送 Git 不能备份运行数据。

详细设计见 [CLAUDE.md](CLAUDE.md)、[需求](docs/01_PRD.md)、[路线图](docs/05_roadmap.md)。当前实现与验证边界以 [2026-10-04 审查报告](docs/audit-2026-10-04.md) 为补充依据，历史里程碑勾选不等于所有外部服务已验收。
