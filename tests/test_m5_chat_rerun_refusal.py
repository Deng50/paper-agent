"""M5 bug fix：chat 里说「重新检索/重新搜/重新跑/再找一批」时 agent 应拒绝，引导按钮。

owner 报告 bug：用户在 chat 说「这批不好，重新检索」→ agent 没拒绝 → 偷偷调 search_papers
→ paper.md 落本地，但 pushes 表无记录、邮箱无邮件、前端「每日推送」看不到。

Path A 修复（不反转 M4 §3.11「chat agent 禁推送」决策）：
- 仅扩 memory_recall.skill.md 拒绝启发式从「推送」字面 → 同义词表达
- 0 架构变动 / 0 schema 变动 / 0 新 tool / 0 反转 §3.11

测试是 grep 风的硬 fact check：skill 文件含必要的同义词触发词 + 拒绝引导文本。
防止后续编辑意外删除导致 bug 复发。真实 agent 行为验证由 owner 在 chat 里手测。
"""

from __future__ import annotations

from pathlib import Path


def _skill_text() -> str:
    skill_path = Path(__file__).resolve().parent.parent / "skills" / "memory_recall.skill.md"
    return skill_path.read_text(encoding="utf-8")


def test_skill_contains_rerun_synonym_triggers() -> None:
    """同义词触发词必须全在 skill prompt 里，让 agent 看得见。"""
    text = _skill_text()
    required_phrases = [
        "重新检索",
        "重新搜",
        "重新跑",
        "再找一批",
        "换一批",
        "重推",
    ]
    missing = [p for p in required_phrases if p not in text]
    assert not missing, f"refusal trigger synonyms 缺失（bug 会复发）: {missing}"


def test_skill_contains_refusal_guidance_text() -> None:
    """拒绝时引导用户去按钮的字面话术必须保留。"""
    text = _skill_text()
    assert "立即触发一次推送" in text
    assert "强制重跑" in text
    # 关键警告：让 agent 知道偷调 search_papers 的具体后果
    assert "不一致" in text


def test_skill_explicitly_forbids_silent_search_papers() -> None:
    """skill 必须明示「绝不擅自调 search_papers」，防止 agent 走 search_papers 分支。"""
    text = _skill_text()
    assert "绝不擅自调" in text and "search_papers" in text


def test_skill_distinguishes_new_topic_vs_redo_intent() -> None:
    """区分启发式段必须保留：找新主题 → search_papers OK；重做当前 → 拒绝。"""
    text = _skill_text()
    assert "区分启发式" in text
    # 保留新主题 search_papers 合法分支（不能误伤）
    assert "search_papers ✅" in text
    # 重做意图走拒绝
    assert "拒绝" in text
