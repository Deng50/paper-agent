"""search_papers 的结构化契约（Pydantic）。

设计精神（v0.4 方法论 B）：目标结构定义成 schema，靠框架校验闭环，不靠 prompt。
- `Paper`：工具输出契约，字段对齐 03_data_model §2.2 的 paper.md frontmatter。
- `ScoreItem` / `ScoreBatch`：评分器经 Anthropic tool_use 返回的结构，Pydantic 校验。
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

# 我们支持的 4 个源（vendored 的 "semantic" 归一化为 "s2"）。
Source = Literal["arxiv", "s2", "crossref", "openalex"]


class Paper(BaseModel):
    """归一化后的文献。三锚点 doi/arxiv_id/normalized_title 用于去重。"""

    paper_id: str  # {source}-{external_id}（文件名安全）
    source: Source
    external_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    url: str = ""
    pub_date: dt.date | None = None
    venue: str | None = None

    # 去重三锚点
    doi: str | None = None
    arxiv_id: str | None = None
    normalized_title: str = ""

    # 评分步骤填充（0~10）
    score: float | None = None
    reason: str | None = None


class ScoreItem(BaseModel):
    """单篇评分结果（评分器 tool_use 输出的元素）。"""

    paper_id: str
    score: float = Field(ge=0.0, le=10.0)
    reason: str


class ScoreBatch(BaseModel):
    """一个批次的全部评分（Anthropic tool_use 的入参 schema）。"""

    scores: list[ScoreItem]
