# Vendored: paper-search-mcp

> 本目录是 **vendored 副本**（完整 fork + 锁 commit），不是 git submodule。
> 决策依据见对话记录与 [CLAUDE.md](../../CLAUDE.md) §3 / PRD R5。

## 来源与锁定

| 项 | 值 |
|----|----|
| 上游仓库 | https://github.com/openags/paper-search-mcp |
| 锁定 commit | `d438222d3e30e4721c9fa721d4275bda681a9117`（main，2026-05-17，合并 PR #75） |
| 拷入日期 | 2026-05-21 |
| 拷入方式 | `git clone --depth 1` → 删 `.git` → 移入此处（无 submodule） |

## 为什么 vendored 而非 uvx / PyPI

- PyPI 最新 `0.1.3`（2025-04-29）**停更一年**，且 arXiv 排序修复未进发布（上游 issue #73）。
- `uvx` / `uv tool install` 被缺失的 console_scripts 入口打断（上游 issue #64 / #46）。
- 本项目硬约束（v0.4 §8：强制按发表日期排序）需要给 Semantic Scholar / OpenAlex **补排序**，必须能改源码。
- 我们只用 25 个源里的 4 个：**arXiv / Semantic Scholar / Crossref / OpenAlex**。

## 本地 patch（搜索 `PATCH(lit-agent)` 可定位全部改动）

| 文件 | 改动 | 原因 |
|------|------|------|
| `paper_search_mcp/academic_platforms/semantic.py` | `search()` 加 `sort` 形参；有 sort 时改走 `paper/search/bulk` 端点（支持 `sort=publicationDate:desc`） | relevance 端点 `paper/search` 不支持排序 |
| `paper_search_mcp/academic_platforms/openalex.py` | `search()` 加 `sort` 形参，透传 OpenAlex 原生 `sort`（如 `publication_date:desc`） | 原版完全无排序参数 |

arXiv（`sortBy/sortOrder` 原样透传）、Crossref（`sort/order` kwargs）**原生支持日期排序，未改**。

## 我们使用的排序映射（date_desc → 各源）

| 源 | 调用参数 |
|----|---------|
| arXiv | `sort_by="submittedDate", sort_order="descending"` |
| Crossref | `sort="published", order="desc"` |
| Semantic Scholar | `sort="publicationDate:desc"`（经 patch 走 bulk 端点） |
| OpenAlex | `sort="publication_date:desc"`（经 patch） |

## 依赖裁剪决策（重要 · 6 个月后翻代码先看这节）

**结论**：不 `pip install` 这个 vendored 包，改用主项目 `pyproject.toml` 的
`[tool.hatch.build] packages` 把 `paper_search_mcp` 暴露为顶层包，**只装 3 个真依赖**。

**为什么不直接装 vendored 包**：它的 `pyproject.toml` 列了 8 个依赖，其中 5 个我们用不到——
装它=白白拖入 MCP 服务器栈 + PDF 解析栈（约 50MB）。我们选了「直接 import 4 个 source 类」
而非「跑 MCP 子进程」，所以 MCP 那套完全多余。

| vendored 声明的 8 依赖 | 我们的处置 | 理由 |
|---|---|---|
| `requests` | ✅ 装（`>=2.32`） | 4 个 source 的 `search()` 都用它发请求 |
| `feedparser` | ✅ 装（`>=6.0`） | arXiv 解析 Atom feed |
| `beautifulsoup4` | ✅ 装（`>=4.12`） | semantic.py 顶层 `from bs4 import BeautifulSoup` |
| `fastmcp` | ❌ 跳过 | MCP 服务器框架；我们直接 import，不跑服务器 |
| `mcp[cli]>=1.6.0` | ❌ 跳过 | 同上，MCP 协议栈无用 |
| `pypdf` | ❌ 跳过 | v1 不解析 PDF；已 P3 patch 改惰性导入，`search()` 路径不触发 |
| `lxml>=4.9.0` | ❌ 跳过 | 我们走 JSON/Atom 路径，bs4 用 stdlib parser 即可 |
| `httpx[socks]>=0.28.1` | ❌ 跳过 | 4 个 source 用 requests；项目主用的 httpx 已在主依赖里（无需 socks 额外组件） |

**风险与兜底**：
- 风险：vendored 内部若有**漏检的动态 / try-except 包裹的 import**（grep 抓不到），
  运行时才会 `ModuleNotFoundError`。
- 兜底：`tests/` 里有**冷启动 import 测试**（`test_vendor_import.py`）—— import + 实例化 4 个
  source 类、跑通 mock 4 源流程；任何漏检依赖在 CI/pytest 阶段即暴露，不等线上。
- 若哪天确实缺包：先确认是不是我们用到的 `search()` 路径所需；是 → 加进主 `pyproject`
  3 依赖清单（并更新本表）；不是（如某 download 路径）→ 不加，因为我们不该走那条路径。

**调用边界硬约束**：`search_papers` 包装器只调 4 个 source 的 `search()`，
**绝不调 `download_pdf()` / `read_paper()` / 任何 PDF 处理函数**（代码顶部注释明示）。
源类名备忘：`ArxivSearcher` / `SemanticSearcher` / `CrossRefSearcher`(大写 R) / `OpenAlexSearcher`。

## 同步上游（如需）

上游一年未发版，预计低频。需要时：
1. `git clone` 上游新 commit；
2. `diff` 对比本目录，重打 `PATCHES.md` 记录的全部 `PATCH(lit-agent)`；
3. 更新本文件的「锁定 commit」并在 git 提交说明变更；
4. 重跑冷启动 import 测试，确认裁剪后的依赖仍然足够。
