"""paper.md 渲染/解析、去重锚点计算、原子写（M2）。

- `normalize_title`：去标点 / 转小写 / 去停用词（03_data_model §2.2 去重末位键）。
- `make_paper_id` / `extract_arxiv_id`：派生文件名安全 id 与 arxiv 锚点。
- `render_paper_md`：严格按 §2.2 frontmatter 渲染（YAML 安全序列化，防摘要控制字符炸 YAML）。
- `load_dedup_index`：扫 ./memory/papers/ 历史 md，取 doi/arxiv_id/normalized_title 三锚点集合。
- `atomic_write`：临时文件 + os.replace（不是锁）。
"""

from __future__ import annotations

import datetime as dt
import os
import re
import tempfile
import time
from pathlib import Path

from lit_agent.tools.schemas import Paper

# 轻量英文停用词（够 normalized_title 去重用，不引 nltk）。
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "for",
        "and",
        "or",
        "to",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "into",
        "via",
        "using",
        "based",
        "study",
        "novel",
        "new",
        "toward",
        "towards",
        "approach",
        "method",
        "analysis",
        "investigation",
    ]
)
_PUNCT_RE = re.compile(r"[^a-z0-9\s]+")
_WS_RE = re.compile(r"\s+")
_UNSAFE_ID_RE = re.compile(r"[^a-z0-9.-]+")
# 所有 C0 控制字符（含 \t \n \r）—— frontmatter 标量必须单行，否则炸 YAML。
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_ARXIV_IN_DOI = re.compile(r"10\.48550/arxiv\.(?P<id>[\w./-]+)", re.IGNORECASE)


def normalize_doi(doi: str | None) -> str:
    """DOI identity is case-insensitive and may arrive as a doi.org URL."""
    return re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", (doi or "").strip(), flags=re.IGNORECASE
    ).lower()


def normalize_arxiv_id(arxiv_id: str | None) -> str:
    value = re.sub(
        r"^(?:https?://arxiv\.org/abs/|arxiv:\s*)",
        "",
        (arxiv_id or "").strip(),
        flags=re.IGNORECASE,
    )
    return re.sub(r"v\d+$", "", value.lower())


def normalize_title(title: str) -> str:
    """转小写 → 去标点 → 去停用词 → 折叠空白。用于标题级去重。"""
    low = _PUNCT_RE.sub(" ", title.lower())
    tokens = [t for t in _WS_RE.sub(" ", low).strip().split() if t and t not in _STOPWORDS]
    return " ".join(tokens)


def make_paper_id(source: str, external_id: str) -> str:
    """{source}-{slug}，slug 限定 [a-z0-9.-]（文件名安全，防路径穿越）。"""
    slug = _UNSAFE_ID_RE.sub("_", external_id.lower()).strip("_")
    return f"{source}-{slug}"


def extract_arxiv_id(source: str, external_id: str, doi: str | None) -> str | None:
    if source == "arxiv":
        return normalize_arxiv_id(external_id)
    if doi:
        m = _ARXIV_IN_DOI.search(doi)
        if m:
            return normalize_arxiv_id(m.group("id"))
    return None


def _yaml_str(value: str | None) -> str:
    """安全的 YAML 双引号标量：去控制字符 + 转义反斜杠/双引号。"""
    if value is None:
        return '""'
    s = _CTRL_RE.sub(" ", value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _yaml_list(items: list[str]) -> str:
    return "[" + ", ".join(_yaml_str(i) for i in items) + "]"


def render_paper_md(paper: Paper, first_pushed_at: dt.datetime) -> str:
    """按 03_data_model §2.2 渲染 paper.md（frontmatter + 正文）。"""
    fm = [
        "---",
        f"paper_id: {paper.paper_id}",
        f"source: {paper.source}",
        f"external_id: {_yaml_str(paper.external_id)}",
        f"doi: {_yaml_str(paper.doi)}",
        f"arxiv_id: {_yaml_str(paper.arxiv_id)}",
        f"normalized_title: {_yaml_str(paper.normalized_title)}",
        f"title: {_yaml_str(paper.title)}",
        f"authors: {_yaml_list(paper.authors)}",
        f"pub_date: {paper.pub_date.isoformat() if paper.pub_date else ''}",
        f"venue: {_yaml_str(paper.venue)}",
        f"url: {_yaml_str(paper.url)}",
        f"first_pushed_at: {first_pushed_at.isoformat()}",
        f"score: {paper.score if paper.score is not None else ''}",
        f"reason: {_yaml_str(paper.reason)}",
        "---",
        "",
        "## Title",
        paper.title.strip(),
        "",
        "## Abstract",
        paper.abstract.strip(),
        "",
        "## 为什么推荐你",
        (paper.reason or "").strip(),
        "",
    ]
    return "\n".join(fm)


def atomic_write(path: Path, content: str) -> None:
    """原子写：临时文件 + os.replace（要么旧内容、要么新内容，不留半截）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    # 独立临时文件避免两个写者共享 *.tmp，造成交叉覆盖/replace 后找不到文件。
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                # Windows 同时 replace 同一目标可能短暂返回 sharing/access violation。
                if os.name != "nt" or attempt == 2:
                    raise
                time.sleep(0.01 * (attempt + 1))
    finally:
        tmp.unlink(missing_ok=True)


def _read_frontmatter_keys(md_path: Path, keys: set[str]) -> dict[str, str]:
    """轻量读取 frontmatter 指定键（不引 pyyaml；只取需要的去重锚点）。"""
    out: dict[str, str] = {}
    try:
        lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, val = line.partition(":")
        if sep and key.strip() in keys:
            out[key.strip()] = val.strip().strip('"')
    return out


class DedupIndex:
    """./memory/papers/ 历史去重锚点集合。"""

    def __init__(self) -> None:
        self.dois: set[str] = set()
        self.arxiv_ids: set[str] = set()
        self.norm_titles: set[str] = set()

    def contains(self, paper: Paper) -> bool:
        if paper.doi and normalize_doi(paper.doi) in self.dois:
            return True
        if paper.arxiv_id and normalize_arxiv_id(paper.arxiv_id) in self.arxiv_ids:
            return True
        return bool(paper.normalized_title) and paper.normalized_title in self.norm_titles

    def add(self, paper: Paper) -> None:
        if paper.doi:
            self.dois.add(normalize_doi(paper.doi))
        if paper.arxiv_id:
            self.arxiv_ids.add(normalize_arxiv_id(paper.arxiv_id))
        if paper.normalized_title:
            self.norm_titles.add(paper.normalized_title)


def load_dedup_index(memory_dir: Path) -> DedupIndex:
    """扫 ./memory/papers/**/*.md 的三锚点，建去重索引。"""
    idx = DedupIndex()
    papers_dir = memory_dir / "papers"
    if not papers_dir.is_dir():
        return idx
    keys = {"doi", "arxiv_id", "normalized_title"}
    for md in papers_dir.rglob("*.md"):
        fm = _read_frontmatter_keys(md, keys)
        if fm.get("doi"):
            idx.dois.add(normalize_doi(fm["doi"]))
        if fm.get("arxiv_id"):
            idx.arxiv_ids.add(normalize_arxiv_id(fm["arxiv_id"]))
        if fm.get("normalized_title"):
            idx.norm_titles.add(fm["normalized_title"])
    return idx
