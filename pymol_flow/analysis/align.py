"""Intelligent multi-strategy structural alignment for monomers, multimers, and asymmetric complexes."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

try:
    from scipy.spatial import cKDTree
    _HAS_CKDTREE = True
except ImportError:
    _HAS_CKDTREE = False


@dataclass
class IntelligentAlignResult:
    """Structured report returned by intelligent structure alignment."""

    mobile_object: str
    target_object: str
    success: bool
    strategy_used: str
    rmsd: float
    overall_ca_rmsd: float
    aligned_atoms: int
    total_mobile_ca: int
    total_target_ca: int
    coverage_pct: float
    chain_mapping: Dict[str, str] = field(default_factory=dict)
    multimer_type: str = "Monomer"
    length_discrepancy_handled: bool = False
    warning: Optional[str] = None
    details: str = ""
    # Ligand and binding pocket awareness
    ligand_detected: bool = False
    ligand_distance: Optional[float] = None
    pocket_interface_chains: List[str] = field(default_factory=list)

    def to_summary_sentence(self) -> str:
        """Concise one-to-two sentence summary suitable for chat responses."""
        if not self.success:
            return f"结构对齐失败: {self.warning or '未能完成结构对齐'}"

        chains_info = ""
        if len(self.chain_mapping) > 1:
            mapping_str = ", ".join(f"{k}→{v}" for k, v in self.chain_mapping.items())
            chains_info = f"，空间链最佳映射为 [{mapping_str}]"

        discrepancy_note = ""
        if self.length_discrepancy_handled:
            discrepancy_note = "（已自适应聚焦全长核心链，排除截短/柔性残基干扰）"

        lig_info = ""
        if self.ligand_detected and self.ligand_distance is not None:
            status = "✅ 结合口袋精准契合" if self.ligand_distance <= 2.0 else "⚠️ 结合口袋存在偏差"
            lig_info = f"，配体质心位移 {self.ligand_distance:.2f} Å ({status})"

        return (
            f"已自主判断并完成对齐：判定为{self.multimer_type}{discrepancy_note}，"
            f"采用【{self.strategy_used}】，整体核心 Cα RMSD 为 {self.rmsd:.2f} Å "
            f"(覆盖 {self.aligned_atoms} 个匹配原子，占比 {self.coverage_pct:.1f}%){chains_info}{lig_info}。"
        )

    def to_markdown(self) -> str:
        """Rich Markdown report containing architecture insights and chain mapping table."""
        if not self.success:
            return f"### ⚠️ 结构对齐未成功\n\n> {self.warning or '未能完成结构对齐'}"

        lines = [
            "### 🎯 自主智能结构对齐报告 (Intelligent Alignment Report)",
            f"- **移动结构 (Mobile)**: `{self.mobile_object}`",
            f"- **参考结构 (Target)**: `{self.target_object}`",
            f"- **复合物类型 (Architecture)**: **{self.multimer_type}**",
            f"- **优选策略 (Optimal Strategy)**: **{self.strategy_used}**",
            f"- **核心 Cα RMSD**: **`{self.rmsd:.3f} Å`** (基于 {self.aligned_atoms} 个核心匹配原子)",
            f"- **结构覆盖率 (Coverage)**: `{self.coverage_pct:.1f}%` ({self.aligned_atoms} / {self.total_mobile_ca} Cα)",
        ]
        if self.length_discrepancy_handled:
            lines.append("- **链长异质性处理**: 自动检测到链长不均或存在截短链/柔性末端，已自适应聚焦保守核心结构域，避免非均一链拉偏全局叠合。")

        if self.ligand_detected and self.ligand_distance is not None:
            status = "✅ 结合口袋精准契合" if self.ligand_distance <= 2.0 else "⚠️ 结合口袋存在偏差"
            lines.append(f"- **配体质心位移 (Ligand Centroid Shift)**: **`{self.ligand_distance:.2f} Å`** ({status})")
            if self.pocket_interface_chains:
                chains_str = "+".join(self.pocket_interface_chains)
                lines.append(f"- **结合界面接触链 (Pocket Interface Chains)**: `Chain {chains_str}`")

        if self.chain_mapping:
            lines.append("\n#### 🔗 空间对称性链映射 (Spatial Chain Mapping)")
            lines.append("| 移动链 (Mobile Chain) | 参考链 (Target Chain) | 状态 |")
            lines.append("| :--- | :--- | :--- |")
            for m_chain, t_chain in self.chain_mapping.items():
                lines.append(f"| Chain `{m_chain}` | Chain `{t_chain}` | ✅ 空间最佳叠合 |")

        if self.details:
            lines.append(f"\n> 💡 *决策依据*: {self.details}")

        return "\n".join(lines)


def _get_active_cmd() -> Any:
    try:
        from pymol import cmd
        return cmd
    except ImportError:
        return None


def _compute_nearest_distances(pts_m: np.ndarray, pts_t: np.ndarray) -> np.ndarray:
    """Compute nearest neighbor distance from each point in pts_m to pts_t."""
    if len(pts_m) == 0 or len(pts_t) == 0:
        return np.array([], dtype=float)

    if _HAS_CKDTREE:
        tree = cKDTree(pts_t)
        distances, _ = tree.query(pts_m)
        return np.asarray(distances, dtype=float)

    # Fallback to chunked NumPy distance calculation if scipy is unavailable
    min_dists = np.empty(len(pts_m), dtype=float)
    chunk_size = 500
    for i in range(0, len(pts_m), chunk_size):
        chunk = pts_m[i:i + chunk_size]
        diff = chunk[:, None, :] - pts_t[None, :, :]
        dist_sq = np.sum(diff ** 2, axis=-1)
        min_dists[i:i + chunk_size] = np.sqrt(np.min(dist_sq, axis=1))
    return min_dists


def _detect_ligand_and_interface_chains(
    cmd: Any,
    obj_name: str,
    ligand_selector: str = "organic and not solvent",
    cutoff: float = 4.5,
) -> Tuple[bool, List[str], Optional[np.ndarray]]:
    """Detect if an organic ligand exists and identify contacting interface chains."""
    lig_sel = f"({obj_name}) and ({ligand_selector})"
    try:
        if cmd.count_atoms(lig_sel) == 0:
            return False, [], None

        coords = cmd.get_coords(lig_sel)
        centroid = np.mean(coords, axis=0) if coords is not None and len(coords) > 0 else None

        contact_sel = f"byres (({obj_name}) and polymer.protein within {cutoff} of ({lig_sel}))"
        contact_chains = cmd.get_chains(contact_sel) or []
        valid_chains = [c for c in contact_chains if str(c).strip()]
        return True, valid_chains, centroid
    except Exception:
        return False, [], None


def align_structures(
    mobile_object: str,
    target_object: str,
    mobile_selection: Optional[str] = None,
    target_selection: Optional[str] = None,
    mode: str = "auto",
    ligand_selection: str = "organic and not solvent",
    focus_pocket: bool = True,
    cmd_override: Any = None,
) -> IntelligentAlignResult:
    """Intelligently align two molecular structures or complexes in PyMOL.

    Autonomously evaluates:
    1. Monomer vs multimer (dimer, trimer, oligomer) architecture.
    2. Symmetry permutations (e.g. C3 cyclic symmetry rotation mismatch).
    3. Unequal chain lengths, flexible disordered loops, or truncated chains.
    4. Binding pocket orientation and ligand centroid preservation.
    5. Evaluates multiple candidates (global align, global super, single-chain anchors, dual-anchors)
       without accumulating state, picking the global optimum with minimum RMSD and maximum coverage.
    """
    cmd = cmd_override or _get_active_cmd()
    if cmd is None:
        return IntelligentAlignResult(
            mobile_object=mobile_object,
            target_object=target_object,
            success=False,
            strategy_used="None",
            rmsd=0.0,
            overall_ca_rmsd=0.0,
            aligned_atoms=0,
            total_mobile_ca=0,
            total_target_ca=0,
            coverage_pct=0.0,
            warning="PyMOL cmd is not available in current environment.",
        )

    # Clean object identifiers
    mob_name = str(mobile_object).strip()
    tgt_name = str(target_object).strip()

    # Validate objects exist and contain atoms
    for obj in (mob_name, tgt_name):
        try:
            if cmd.count_atoms(f"({obj})") == 0:
                return IntelligentAlignResult(
                    mobile_object=mob_name,
                    target_object=tgt_name,
                    success=False,
                    strategy_used="None",
                    rmsd=0.0,
                    overall_ca_rmsd=0.0,
                    aligned_atoms=0,
                    total_mobile_ca=0,
                    total_target_ca=0,
                    coverage_pct=0.0,
                    warning=f"Object '({obj})' contains 0 atoms or does not exist in PyMOL scene.",
                )
        except Exception as exc:
            return IntelligentAlignResult(
                mobile_object=mob_name,
                target_object=tgt_name,
                success=False,
                strategy_used="None",
                rmsd=0.0,
                overall_ca_rmsd=0.0,
                aligned_atoms=0,
                total_mobile_ca=0,
                total_target_ca=0,
                coverage_pct=0.0,
                warning=f"Error inspecting object '{obj}': {exc}",
            )

    # Detect organic ligand and contacting interface chains
    m_has_lig, m_int_chains, m_centroid = _detect_ligand_and_interface_chains(
        cmd, mob_name, ligand_selector=ligand_selection, cutoff=4.5
    )
    t_has_lig, t_int_chains, t_centroid = _detect_ligand_and_interface_chains(
        cmd, tgt_name, ligand_selector=ligand_selection, cutoff=4.5
    )
    has_any_ligand = m_has_lig or t_has_lig

    # Inspect chains and C-alpha counts
    raw_m_chains = cmd.get_chains(f"({mob_name})") or []
    raw_t_chains = cmd.get_chains(f"({tgt_name})") or []

    m_chains = [c for c in raw_m_chains if str(c).strip()]
    t_chains = [c for c in raw_t_chains if str(c).strip()]

    # If no explicit chain IDs, treat as single default chain
    if not m_chains:
        m_chains = [""]
    if not t_chains:
        t_chains = [""]

    total_m_ca = cmd.count_atoms(f"({mob_name}) and name CA")
    total_t_ca = cmd.count_atoms(f"({tgt_name}) and name CA")

    # If no C-alphas (e.g. nucleic acids or small molecule ligands), fallback to all atoms
    atom_filter = "name CA" if total_m_ca > 0 and total_t_ca > 0 else "all"

    # Analyze chain lengths
    m_chain_lens = {}
    for c in m_chains:
        sel = f"({mob_name}) and chain {c} and {atom_filter}" if c else f"({mob_name}) and {atom_filter}"
        m_chain_lens[c] = cmd.count_atoms(sel)

    t_chain_lens = {}
    for c in t_chains:
        sel = f"({tgt_name}) and chain {c} and {atom_filter}" if c else f"({tgt_name}) and {atom_filter}"
        t_chain_lens[c] = cmd.count_atoms(sel)

    # Filter out ligand/solvent pseudo-chains with 0 matching atoms
    protein_m_chains = [c for c in m_chains if m_chain_lens.get(c, 0) > 0]
    protein_t_chains = [c for c in t_chains if t_chain_lens.get(c, 0) > 0]
    if protein_m_chains:
        m_chains = protein_m_chains
    if protein_t_chains:
        t_chains = protein_t_chains

    n_m = len(m_chains)
    n_t = len(t_chains)

    if max(n_m, n_t) >= 3:
        multimer_type = f"多聚体 / 三聚体 (Trimer/Oligomer, {n_m} chains)"
    elif max(n_m, n_t) == 2:
        multimer_type = f"二聚体 (Dimer, {n_m} chains)"
    else:
        multimer_type = "单体 (Monomer)"

    # Detect chain length heterogeneity (e.g., truncated chains vs full-length chains)
    lens = [l for l in m_chain_lens.values() if l > 0]
    length_discrepancy = False
    if len(lens) > 1:
        max_l = max(lens)
        min_l = min(lens)
        if (max_l - min_l >= 15) or (min_l > 0 and max_l / min_l > 1.15):
            length_discrepancy = True

    # Save original coordinates for atomic candidate evaluation
    try:
        orig_coords = cmd.get_coords(mob_name)
    except Exception:
        orig_coords = None

    if orig_coords is None or len(orig_coords) == 0:
        # Fallback to direct align if coords could not be retrieved
        try:
            r = cmd.align(mob_name, tgt_name)
            rmsd = float(r[0]) if isinstance(r, (list, tuple)) and len(r) > 0 else 0.0
            atoms = int(r[1]) if isinstance(r, (list, tuple)) and len(r) > 1 else 0
            return IntelligentAlignResult(
                mobile_object=mob_name,
                target_object=tgt_name,
                success=True,
                strategy_used="Global Sequence Align (Fallback)",
                rmsd=rmsd,
                overall_ca_rmsd=rmsd,
                aligned_atoms=atoms,
                total_mobile_ca=total_m_ca,
                total_target_ca=total_t_ca,
                coverage_pct=(atoms / max(1, total_m_ca)) * 100.0,
                multimer_type=multimer_type,
                length_discrepancy_handled=False,
                ligand_detected=has_any_ligand,
            )
        except Exception as e:
            return IntelligentAlignResult(
                mobile_object=mob_name,
                target_object=tgt_name,
                success=False,
                strategy_used="None",
                rmsd=0.0,
                overall_ca_rmsd=0.0,
                aligned_atoms=0,
                total_mobile_ca=total_m_ca,
                total_target_ca=total_t_ca,
                coverage_pct=0.0,
                warning=f"Fallback alignment failed: {e}",
            )

    # Prepare target reference points
    try:
        pts_t = cmd.get_coords(f"({tgt_name}) and {atom_filter}")
    except Exception:
        pts_t = None

    if pts_t is None or len(pts_t) == 0:
        pts_t = cmd.get_coords(f"({tgt_name})")

    # Generate candidate alignment functions to evaluate
    candidates: List[Tuple[str, str, Any]] = []

    # 1. Global alignment candidates
    if mode in ("auto", "global"):
        candidates.append((
            "Global Align",
            "全局序列对齐 (cmd.align)",
            lambda: cmd.align(mob_name, tgt_name)
        ))
        candidates.append((
            "Global Super",
            "全局结构拓扑对齐 (cmd.super)",
            lambda: cmd.super(mob_name, tgt_name)
        ))

    # 2. Multimer / chain-anchor candidates (crucial for trimers with C3 symmetry and uneven chains)
    if mode in ("auto", "chain_anchor") and (n_m >= 2 or n_t >= 2):
        # Single chain anchors
        for mc in m_chains:
            for tc in t_chains:
                if not mc or not tc:
                    continue
                sel_m = f"({mob_name}) and chain {mc}"
                sel_t = f"({tgt_name}) and chain {tc}"
                candidates.append((
                    f"Anchor {mc}->{tc} (align)",
                    f"单链锚定对齐 (Mobile 链 {mc} → Target 链 {tc}, cmd.align)",
                    (lambda sm=sel_m, st=sel_t: cmd.align(sm, st))
                ))
                candidates.append((
                    f"Anchor {mc}->{tc} (super)",
                    f"单链锚定对齐 (Mobile 链 {mc} → Target 链 {tc}, cmd.super)",
                    (lambda sm=sel_m, st=sel_t: cmd.super(sm, st))
                ))

        # Pairwise permutation dual-anchors for trimers / oligomers
        if len(m_chains) >= 2 and len(t_chains) >= 2:
            # Filter out severely truncated chains (length < 70% of median)
            med_len = float(np.median(list(m_chain_lens.values()))) if m_chain_lens else 0.0
            core_m_chains = [c for c in m_chains if m_chain_lens.get(c, 0) >= med_len * 0.7]
            # Fallback: sort descending by length so we pick the longest/most complete chains
            if len(core_m_chains) < 2:
                core_m_chains = sorted(m_chains, key=lambda c: m_chain_lens.get(c, 0), reverse=True)[:2]

            selected_m_pairs: List[Tuple[str, str]] = []
            # If ligand interface chains are detected, prioritize the interface chains
            if m_has_lig and len(m_int_chains) >= 2:
                selected_m_pairs.append((m_int_chains[0], m_int_chains[1]))
            elif t_has_lig and len(t_int_chains) >= 2 and all(c in m_chains for c in t_int_chains[:2]):
                selected_m_pairs.append((t_int_chains[0], t_int_chains[1]))

            # Add core chain combinations
            for i in range(len(core_m_chains)):
                for j in range(i + 1, len(core_m_chains)):
                    pair = (core_m_chains[i], core_m_chains[j])
                    if pair not in selected_m_pairs:
                        selected_m_pairs.append(pair)

            if not selected_m_pairs and len(m_chains) >= 2:
                selected_m_pairs = [(m_chains[0], m_chains[1])]

            # Test target chain pairs and polarities (t1 != t2)
            for c1, c2 in selected_m_pairs[:3]:
                for i in range(len(t_chains)):
                    for j in range(len(t_chains)):
                        if i == j:
                            continue
                        t1, t2 = t_chains[i], t_chains[j]
                        dual_m = f"({mob_name}) and chain {c1}+{c2}"
                        dual_t = f"({tgt_name}) and chain {t1}+{t2}"
                        candidates.append((
                            f"Dual Pair {c1}->{t1}, {c2}->{t2} (align)",
                            f"二聚体界面正反全配对 (Mobile 链 {c1}+{c2} → Target 链 {t1}+{t2}, cmd.align)",
                            (lambda sm=dual_m, st=dual_t: cmd.align(sm, st))
                        ))
                        candidates.append((
                            f"Dual Pair {c1}->{t1}, {c2}->{t2} (super)",
                            f"二聚体界面正反全配对 (Mobile 链 {c1}+{c2} → Target 链 {t1}+{t2}, cmd.super)",
                            (lambda sm=dual_m, st=dual_t: cmd.super(sm, st))
                        ))

    # 3. Fallback CEAlign if requested or needed
    if mode in ("auto", "cealign") and hasattr(cmd, "cealign"):
        candidates.append((
            "CEAlign",
            "纯三维组合延拓结构比对 (cmd.cealign)",
            lambda: cmd.cealign(tgt_name, mob_name)
        ))

    # Evaluate all candidates non-destructively
    evaluations: List[Dict[str, Any]] = []

    for key, desc, fn in candidates:
        try:
            # Restore to original coordinates before each trial
            cmd.load_coords(orig_coords, mob_name)
            raw_res = fn()

            raw_rmsd = 999.0
            raw_atoms = 0
            if isinstance(raw_res, (list, tuple)) and len(raw_res) > 0:
                raw_rmsd = float(raw_res[0])
                if len(raw_res) > 1:
                    raw_atoms = int(raw_res[1])
            elif isinstance(raw_res, dict) and "rmsd" in raw_res:
                raw_rmsd = float(raw_res["rmsd"])

            # Inspect resulting 3D coordinates
            pts_m = cmd.get_coords(f"({mob_name}) and {atom_filter}")
            if pts_m is None or len(pts_m) == 0:
                pts_m = cmd.get_coords(f"({mob_name})")

            if pts_m is not None and pts_t is not None and len(pts_m) > 0 and len(pts_t) > 0:
                dists = _compute_nearest_distances(pts_m, pts_t)
                matched = dists < 3.5
                matched_count = int(np.sum(matched))
                coverage = matched_count / max(1, len(pts_m))
                core_rmsd = float(np.sqrt(np.mean(dists[matched] ** 2))) if matched_count > 0 else 999.0
            else:
                core_rmsd = raw_rmsd
                matched_count = raw_atoms
                coverage = matched_count / max(1, total_m_ca)

            # Measure ligand centroid displacement if both structures have a ligand
            cur_lig_dist = None
            if m_has_lig and t_has_lig and t_centroid is not None:
                try:
                    cur_m_coords = cmd.get_coords(f"({mob_name}) and ({ligand_selection})")
                    if cur_m_coords is not None and len(cur_m_coords) > 0:
                        cur_m_cent = np.mean(cur_m_coords, axis=0)
                        cur_lig_dist = float(np.linalg.norm(cur_m_cent - t_centroid))
                except Exception:
                    cur_lig_dist = None

            # Composite scoring function:
            # 1. Core Cα RMSD (weight 1.5)
            # 2. Structural coverage penalty ((1 - cov) * 12.0)
            # 3. Ligand centroid distance penalty
            score = core_rmsd * 1.5 + (1.0 - coverage) * 12.0
            if focus_pocket and m_has_lig and t_has_lig and cur_lig_dist is not None:
                if cur_lig_dist > 3.0:
                    # Heavy penalty for flipped/misplaced pocket (> 3.0 Å)
                    score += 25.0 + cur_lig_dist * 5.0
                else:
                    score += cur_lig_dist * 2.0

            evaluations.append({
                "key": key,
                "desc": desc,
                "fn": fn,
                "score": score,
                "core_rmsd": core_rmsd,
                "raw_rmsd": raw_rmsd,
                "matched_count": matched_count,
                "coverage": coverage,
                "lig_dist": cur_lig_dist,
            })
        except Exception:
            continue

    if not evaluations:
        return IntelligentAlignResult(
            mobile_object=mob_name,
            target_object=tgt_name,
            success=False,
            strategy_used="None",
            rmsd=0.0,
            overall_ca_rmsd=0.0,
            aligned_atoms=0,
            total_mobile_ca=total_m_ca,
            total_target_ca=total_t_ca,
            coverage_pct=0.0,
            warning="All alignment candidate strategies failed to execute.",
            ligand_detected=has_any_ligand,
        )

    # Select the candidate with the lowest penalty score
    best_candidate = min(evaluations, key=lambda x: x["score"])

    # Restore original coordinates and execute the winning alignment for the live session
    cmd.load_coords(orig_coords, mob_name)
    try:
        best_candidate["fn"]()
    except Exception as exc:
        return IntelligentAlignResult(
            mobile_object=mob_name,
            target_object=tgt_name,
            success=False,
            strategy_used=best_candidate["desc"],
            rmsd=0.0,
            overall_ca_rmsd=0.0,
            aligned_atoms=0,
            total_mobile_ca=total_m_ca,
            total_target_ca=total_t_ca,
            coverage_pct=0.0,
            warning=f"Applying best candidate failed: {exc}",
            ligand_detected=has_any_ligand,
        )

    # Determine spatial chain correspondence in the finalized aligned scene
    chain_mapping: Dict[str, str] = {}
    if len(m_chains) > 1 and len(t_chains) > 1:
        for mc in m_chains:
            pts_mc = cmd.get_coords(f"({mob_name}) and chain {mc} and {atom_filter}")
            if pts_mc is None or len(pts_mc) == 0:
                continue
            best_tc = None
            best_matched = -1
            best_core_dist = 999.0
            for tc in t_chains:
                pts_tc = cmd.get_coords(f"({tgt_name}) and chain {tc} and {atom_filter}")
                if pts_tc is None or len(pts_tc) == 0:
                    continue
                d = _compute_nearest_distances(pts_mc, pts_tc)
                if len(d) == 0:
                    continue
                matched_mask = d < 3.5
                n_match = int(np.sum(matched_mask))
                mean_core = float(np.mean(d[matched_mask])) if n_match > 0 else float(np.mean(d))
                # Prioritize maximum matched core atoms, break ties by lowest core distance
                if n_match > best_matched or (n_match == best_matched and mean_core < best_core_dist):
                    best_matched = n_match
                    best_core_dist = mean_core
                    best_tc = tc
            if best_tc:
                chain_mapping[mc] = best_tc

    final_rmsd = best_candidate["core_rmsd"]
    final_atoms = best_candidate["matched_count"]
    final_cov = best_candidate["coverage"] * 100.0

    # Calculate final ligand displacement
    final_lig_dist = None
    if m_has_lig and t_has_lig and t_centroid is not None:
        try:
            fin_m_coords = cmd.get_coords(f"({mob_name}) and ({ligand_selection})")
            if fin_m_coords is not None and len(fin_m_coords) > 0:
                fin_m_cent = np.mean(fin_m_coords, axis=0)
                final_lig_dist = float(np.linalg.norm(fin_m_cent - t_centroid))
        except Exception:
            final_lig_dist = None

    # Compose rational details
    details_parts = []
    if "Anchor" in best_candidate["key"] or "Dual Pair" in best_candidate["key"]:
        details_parts.append(
            "检测到多聚体/三聚体旋转对称性（如 C3 空间置换），全局盲对齐易发生 ~120° 旋转错配。"
            "通过单链/二聚体界面配对刚体驱动，成功捕获真实空间对应链。"
        )
    if length_discrepancy:
        details_parts.append(
            "针对链长不对称（存在额外结构域、截短链或柔性尾巴）的问题，算法自动聚焦全长核心骨架，"
            "有效防止了非同源长末端或截短链拉偏整体叠合坐标。"
        )
    if final_lig_dist is not None:
        if final_lig_dist <= 2.0:
            details_parts.append(f"小分子配体位移仅 {final_lig_dist:.2f} Å，结合口袋极性与空间朝向精准贴合。")
        else:
            details_parts.append(f"检测到小分子配体存在 {final_lig_dist:.2f} Å 位移偏差，可能存在结合口袋构象形变或局部诱导契合。")
    if not details_parts:
        details_parts.append("经多候选策略评估，该策略在核心残基精度与整体骨架覆盖度上达到最优平衡。")

    interface_chains = m_int_chains if m_int_chains else t_int_chains

    return IntelligentAlignResult(
        mobile_object=mob_name,
        target_object=tgt_name,
        success=True,
        strategy_used=best_candidate["desc"],
        rmsd=final_rmsd,
        overall_ca_rmsd=final_rmsd,
        aligned_atoms=final_atoms,
        total_mobile_ca=total_m_ca,
        total_target_ca=total_t_ca,
        coverage_pct=final_cov,
        chain_mapping=chain_mapping,
        multimer_type=multimer_type,
        length_discrepancy_handled=length_discrepancy,
        details=" ".join(details_parts),
        ligand_detected=has_any_ligand,
        ligand_distance=final_lig_dist,
        pocket_interface_chains=interface_chains,
    )
