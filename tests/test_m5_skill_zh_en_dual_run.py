"""M5 P1 ④ 归因强化：memory_recall.skill.md 加强制中英双跑 + 对照词表。

owner 提议落地（路径 c 变体）：让 chat agent 自己做中英翻译 + 并跑 search_memory，
0 工程改动，仅 skill prompt 加硬约束。本测试 grep 风防回归 —— 编辑 skill 不慎
删掉关键 mapping 或硬约束段时立即捕到。

真 agent 行为验证由 owner 在 chat 里手测（输入中文 query，看 SSE 流是否真有
2-3 次 search_memory 工具调用）。
"""

from __future__ import annotations

from pathlib import Path


def _skill() -> str:
    return (Path(__file__).resolve().parent.parent / "skills" / "memory_recall.skill.md").read_text(
        encoding="utf-8"
    )


def test_skill_has_dual_run_hard_constraint_section() -> None:
    """skill 含「中英双跑硬约束」段 + 4 步流程 + 「必须执行」字面（agent 才会真跑）。"""
    s = _skill()
    assert "中英双跑硬约束" in s
    assert "必须执行" in s
    # 4 步流程关键词
    assert "提取核心 token" in s
    assert "生成 2-3 条等价英文 query" in s
    # 必须跑多次 search_memory
    assert "N+1 次工具调用" in s or "都跑一次" in s


def test_skill_has_lithium_metal_variants() -> None:
    """锂金属：覆盖 lithium metal / lithium-metal / Li-metal 3 个英文变体。"""
    s = _skill()
    assert "lithium metal" in s
    assert "lithium-metal" in s
    assert "Li-metal" in s
    # 中文也要在
    assert "锂金属" in s


def test_skill_has_polymer_pvdf_chemistry_variants() -> None:
    """聚合物 / PVDF 跨语言 + 化学全名变体（owner 关注的 polymer ⇄ Poly(Vinylidene Fluoride)）。"""
    s = _skill()
    assert "polymer" in s
    assert "聚合物" in s
    assert "PVDF" in s
    assert "Poly(Vinylidene Fluoride)" in s


def test_skill_has_dendrite_variants() -> None:
    """枝晶：覆盖 dendrite/dendrites/dendrite-free 多形态（FTS5 stemming 同等覆盖）。"""
    s = _skill()
    assert "枝晶" in s
    assert "dendrite" in s
    assert "dendrites" in s
    assert "dendrite-free" in s


def test_skill_has_sulfide_argyrodite_mapping() -> None:
    """硫化物 → sulfide + argyrodite（专业矿石名同义）。"""
    s = _skill()
    assert "硫化物" in s
    assert "sulfide" in s
    assert "argyrodite" in s


def test_skill_preserves_chemistry_formula_rule() -> None:
    """化学式 / 缩写保留原样规则（Li6PS5Cl / NCM811 / LLZO 等单 token 跑一次即可）。"""
    s = _skill()
    assert "化学式" in s and "保留" in s
    # 几个高频化学式 / 缩写要在对照表里出现以便 agent 识别
    for sym in ["Li6PS5Cl", "NCM811", "LLZO", "PVDF", "PEO"]:
        assert sym in s, f"化学式 / 缩写 {sym!r} 缺失对照表（agent 会误翻译）"


def test_skill_has_thermal_management_safety() -> None:
    """电池热管理 / 安全方向（CLAUDE.md §1 字面 3 大方向之一）。"""
    s = _skill()
    assert "电池热管理" in s
    assert "battery thermal management" in s
    assert "thermal runaway" in s


def test_skill_has_standard_template_examples() -> None:
    """标准模板代码块（owner 例子字面：硫化物固态电解质 / PVDF 聚合物 / 锂枝晶）。"""
    s = _skill()
    # 模板应该至少 3 个例子
    assert "硫化物 固态电解质" in s
    assert "sulfide solid electrolyte" in s
    assert "PVDF 聚合物 电解质" in s
    assert "PVDF polymer electrolyte" in s
    assert "锂金属 枝晶" in s
    assert "lithium metal dendrite" in s


def test_skill_has_failure_evidence_motivation() -> None:
    """skill 头部解释了为什么必须双跑（任务 A 归因报告 67% 跨语言失败）。"""
    s = _skill()
    # 强 motivation 让 agent 不省略步骤
    assert "M5 P1 ④ 归因" in s or "67%" in s
    # 具体例子
    assert "锂金属" in s and "lithium-metal" in s
