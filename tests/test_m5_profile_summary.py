"""M5 C3：_read_profile_summary 渲染 negative_keywords / keyword_weights 测试。

决策 A2：profile.md frontmatter 加 negative_keywords 字段；search_papers 读到后
渲染成 scoring prompt 注入的中文上下文。本测试覆盖 4 个场景。
"""

from __future__ import annotations

from pathlib import Path

from lit_agent.tools.search_papers import _read_profile_summary


def _write_profile(memory_dir: Path, body: str) -> None:
    p = memory_dir / "profile" / "profile.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_profile_missing_returns_empty(tmp_path: Path) -> None:
    """profile.md 不存在 → 返回空串（daily-push 兜底逻辑用 system prompt 默认）。"""
    mem = tmp_path / "memory"
    mem.mkdir()
    assert _read_profile_summary(mem) == ""


def test_m3_legacy_profile_no_negative_keywords(tmp_path: Path) -> None:
    """M3/M4 旧 profile（仅 keyword_weights 无 negative_keywords）→ 第二段不出现。"""
    mem = tmp_path / "memory"
    mem.mkdir()
    _write_profile(
        mem,
        """---
updated_at: 1970-01-01T00:00:00+08:00
keyword_weights: {}
seed_queries:
  - "lithium battery solid electrolyte"
---

## 画像摘要
（占位）尚无足够反馈。
""",
    )
    summary = _read_profile_summary(mem)
    assert "请避开" not in summary
    assert "偏好关键词" not in summary  # keyword_weights 为空也不出现
    assert "画像摘要" in summary
    assert "（占位）尚无足够反馈" in summary


def test_m5_profile_full_schema(tmp_path: Path) -> None:
    """M5 真实场景：keyword_weights 非空 + negative_keywords 非空 → 三段都出现。"""
    mem = tmp_path / "memory"
    mem.mkdir()
    _write_profile(
        mem,
        """---
updated_at: 2026-05-27T11:30:00+08:00
keyword_weights:
  argyrodite: 0.8
  PVDF: 0.6
negative_keywords:
  - 液态添加剂
  - 钠电池
seed_queries:
  - "lithium battery"
---

## 画像摘要
最近 7 天偏好硫化物固态电解质。
""",
    )
    summary = _read_profile_summary(mem)
    # 三段都在
    assert "偏好关键词：" in summary
    assert "argyrodite (+0.80)" in summary
    assert "PVDF (+0.60)" in summary
    assert "请避开（用户明示）：" in summary
    assert "液态添加剂" in summary
    assert "钠电池" in summary
    assert "画像摘要：" in summary
    assert "最近 7 天偏好硫化物固态电解质" in summary


def test_profile_yaml_corrupt_graceful_degradation(tmp_path: Path) -> None:
    """frontmatter yaml 语法损坏 → 静默降级仅保留正文，不抛崩 daily-push。"""
    mem = tmp_path / "memory"
    mem.mkdir()
    _write_profile(
        mem,
        """---
this is not: valid: yaml: at all: :
keyword_weights: }{}{
---

## 画像摘要
应急正文。
""",
    )
    summary = _read_profile_summary(mem)
    # frontmatter 解析失败 → 偏好/避开两段不出现，正文段仍在
    assert "偏好关键词" not in summary
    assert "请避开" not in summary
    assert "应急正文" in summary
