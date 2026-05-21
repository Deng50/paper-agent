# 本地 patch 清单（paper-search-mcp vendored fork）

> 上游：https://github.com/openags/paper-search-mcp　锁定 commit `d438222`（2026-05-17）
> 全部改动在源码中以 `PATCH(lit-agent)` 标记，`grep -rn "PATCH(lit-agent)"` 可一次定位。
> 同步上游时：对照本文件逐条重打 patch，更新 [VENDOR.md](VENDOR.md) 的锁定 commit。

---

## P1 · Semantic Scholar 按日期排序

- **文件**：`paper_search_mcp/academic_platforms/semantic.py`
- **改动**：`SemanticSearcher.search()` 新增 `sort: Optional[str] = None` 形参；
  当传入 `sort` 时，从 relevance 端点 `paper/search` 改走 **bulk 端点 `paper/search/bulk`**
  （后者支持 `sort=publicationDate:desc`），响应结构同为 `{"data": [...]}`，下游解析不变。
- **为什么**：v0.4 PRD §8 / 架构硬约束要求**强制按发表日期降序**（否则经典老论文反复占据
  Top N → 全被去重 → 每天 0 篇产出 → 系统挂）。而 S2 的 `paper/search` relevance 端点
  **不支持任何排序参数**。
- **上游对应**：无专门 issue；属上游能力缺口（relevance 端点设计如此）。上游若未来在
  `paper/search` 加 sort，可简化本 patch。
- **调用方传参**：`search(query, sort="publicationDate:desc", max_results=20)`。

## P2 · OpenAlex 按日期排序

- **文件**：`paper_search_mcp/academic_platforms/openalex.py`
- **改动**：`OpenAlexSearcher.search()` 新增 `sort: Optional[str] = None` 形参；
  传入时透传到 OpenAlex API 的 `sort` 查询参数。
- **为什么**：同 P1。OpenAlex 原版 `search()` **完全没有排序参数**，但 OpenAlex API
  本身支持 `sort=publication_date:desc`，仅是上游未暴露。
- **上游对应**：无 issue；上游未暴露已有的 API 能力。
- **调用方传参**：`search(query, sort="publication_date:desc", max_results=20)`。

## P3 · pypdf 惰性导入（不强制 PDF 依赖）

- **文件**：`paper_search_mcp/academic_platforms/arxiv.py`、`.../semantic.py`
- **改动**：把模块顶层的 `from pypdf import PdfReader` 移入 `read_paper()` 方法内部（惰性导入）。
- **为什么**：v1 **不解析 PDF**（CLAUDE.md / PRD 明确）。本项目只调 `search()` 取 metadata，
  从不调用 `read_paper()` / `download_pdf()`。原版顶层导入会把 `pypdf` 变成**强制依赖**，
  且把 PDF 解析代码加载进我们的检索路径。改为惰性后：`pypdf` 不再是必装依赖，
  检索路径零 PDF 代码；只有显式调 `read_paper()`（我们不会）才会触发导入。
- **上游对应**：无 issue；纯属本项目的依赖收敛 + 设计约束落地。
- **行为影响**：无（`search()` 行为不变；`read_paper()` 若被调仍可用，前提是装了 pypdf）。

---

## 未改但需知的源行为

- **arXiv**：`search(sort_by, sort_order)` 原样透传 arXiv API 的 `sortBy/sortOrder`。
  传 `sort_by="submittedDate", sort_order="descending"` 即日期降序。**未改**。
- **Crossref**：`search(query, max_results, **kwargs)`，`sort`/`order` 经 kwargs 透传
  Crossref API。传 `sort="published", order="desc"` 即日期降序。**未改**。
- **S2 无 key 回退**：`SemanticSearcher.get_api_key()` 在无 key 时回退匿名访问（限流重）。
  **本项目不 patch 它**——改为在我方 `Settings` 层强制 `SEMANTIC_SCHOLAR_API_KEY`
  必填（fail-fast），运行时始终注入 key，使该回退分支成为死代码。
