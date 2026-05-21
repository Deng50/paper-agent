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

## 同步上游（如需）

上游一年未发版，预计低频。需要时：
1. `git clone` 上游新 commit；
2. `diff` 对比本目录，重打上述两个 `PATCH(lit-agent)`；
3. 更新本文件的「锁定 commit」并在 git 提交说明变更。
