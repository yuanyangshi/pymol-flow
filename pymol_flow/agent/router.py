"""Cognitive routing and thinking mode decision engine for PyMOL Chat Agent."""

from __future__ import annotations

import re


def should_enable_thinking(user_text: str, mode: str | bool = "auto") -> bool:
    """Intelligently determine whether deep reasoning/thinking should be triggered.

    Grounded in Kahneman's Dual-Process Cognitive Architecture (System 1 vs System 2)
    and intent disambiguation from industrial agent routers (Oracle US20250094390A1,
    Du et al. 2025, Kassenaar et al. arXiv:2608.20256):

    - If mode is True or 'on': always True.
    - If mode is False or 'off': always False.
    - If mode is 'auto':
      1. Tier 1 (Explicit Meta-Commands): User explicitly commands deliberate reasoning
         ("一步步", "详细推导", "think step by step", "深入思考") -> True.
      2. Tier 2 (Imperative Operational Exclusion): Direct procedural commands
         (e.g., "把突变位点标红", "将差异残基显示为sticks", "zoom to ligand", "对齐结构")
         without analytical interrogatives -> False (System 1, sub-2s execution).
      3. Tier 3 (Scientific Epistemic Reasoning): Causal questions, comparative analysis,
         chemical mechanisms, selectivity, mutation impact, and compound intent
         ("为什么", "分析差异并高亮", "选择性如何", "SAR", "why", "mechanism") -> True (System 2).
      4. Default: Fast operational mode (False).
    """
    if isinstance(mode, bool):
        return mode
    mode_str = (mode or "auto").lower().strip()
    if mode_str in {"on", "true", "always_on", "always", "1"}:
        return True
    if mode_str in {"off", "false", "always_off", "never", "0"}:
        return False

    text = user_text.strip().lower()
    if not text:
        return False

    # Tier 1: Explicit user directives for deliberate reasoning
    explicit_triggers = [
        "思考", "深思", "深入", "仔细", "详细推导", "一步步", "详细分析",
        "think", "reason", "step by step", "deliberate", "ponder",
    ]
    if any(t in text for t in explicit_triggers):
        return True

    # Tier 2: Disambiguate pure imperative directives vs analytical interrogatives
    analytical_markers = [
        "为什么", "为何", "怎么看", "评价", "评估", "分析", "预测", "机理", "机制",
        "原因", "差异在哪", "有何差异", "哪个好", "哪个更", "哪个", "更有利", "优于", "优选", "有何不同", "推测", "推断", "优劣",
        "是否可能", "会怎样", "依据", "如何解释", "情况", "状态", "差异在哪", "看一下", "帮我看看", "帮我看",
        "区别", "如何", "怎样", "对比", "比较", "看看", "怎么样",
        "why", "how come", "explain", "compare", "evaluate", "assess", "hypothesize",
        "rationale", "which is better", "difference between", "impact of", "consequence",
        "inspect", "examine", "what about", "how about",
    ]
    has_analytical_intent = any(marker in text for marker in analytical_markers)

    is_imperative_directive = (
        re.search(
            r"^(把|将|给|让|为|帮|请把|请将|请为|请帮).*?(标|变|设|显|改|染|画|涂|展示|放大|缩小|对齐|隐藏|显示|居中|旋转|加载|下载|选中|选择|聚焦|定位)",
            text,
        ) is not None
        or re.search(
            r"^(对齐|对准|重置|放大|缩小|旋转|居中|显示|隐藏|高亮|标红|标绿|染色|下载|加载|选中|选择|聚焦|定位|查看|设置|调整|清除|删除|切换|缩放|保存|导出|居中对齐|居中聚焦|显示为|设为|标出)",
            text,
        ) is not None
        or re.search(
            r"^(align|super|cealign|color|show|hide|zoom|orient|center|reset|fetch|select|label|turn|move|delete|remove|set)\b",
            text,
        ) is not None
    )

    if is_imperative_directive and not has_analytical_intent:
        return False

    # Tier 3: Scientific epistemic & relational reasoning
    # In auto mode, deliberate reasoning is only engaged when there is an explicit analytical question
    # (e.g. asking "为什么", "机理", "比较差异", "评估选择性") about scientific domain concepts.
    # Procedural commands, state feedback, or scene descriptions without analytical interrogatives
    # stay in Fast Mode (False).
    if not has_analytical_intent:
        return False

    domain_reasoning_concepts = [
        "选择性", "差异", "耐药", "构效关系", "sar", "亲和力", "结合力",
        "构象", "变构", "热力学", "动力学", "自由能", "ic50", "ec50", "kd", "ki",
        "位阻", "氢键网络", "结合模式", "药效团", "结合口袋", "活性口袋", "活性中心",
        "不同蛋白", "不同受体", "不同构象", "多蛋白", "复合物", "同源模建", "突变",
        "相互作用", "相互作用力", "键合", "氢键", "盐桥", "疏水", "π-π", "pi-pi",
        "selectivity", "affinity", "conformation", "allosteric", "thermodynamic",
        "pharmacophore", "binding mode", "clash", "steric", "pocket", "interaction",
    ]
    return any(concept in text for concept in domain_reasoning_concepts)
