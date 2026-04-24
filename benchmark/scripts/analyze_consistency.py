"""Consistency analysis over the benchmark's repeated runs.

For every (paper, mode, question) triple with N repeats, compute:

QUICK CHECK (verdict is the primary output)
-------------------------------------------
- verdict_agreement       : fraction of repeats whose verdict equals the modal verdict
- fleiss_kappa            : Fleiss' kappa on {confirmed, refuted, unclear}
                            across all QC questions for a paper (one per mode)
                            — measures above-chance agreement beyond the
                            majority baseline.
- evidence_file_jaccard   : mean pairwise Jaccard on cited `file` paths across
                            repeats (captures "did the runs look at the same
                            code?").
- evidence_line_jaccard   : mean pairwise Jaccard on (file, line) tuples.
- confidence_mean / sd    : mean and sample SD of self-reported confidence
                            across repeats.
- tool_calls_mean / sd    : scalar dispersion on tool count per question.
- cost_mean / sd          : dispersion on USD cost per question.
- duration_mean / sd      : dispersion on wall-clock.

DEEP INVESTIGATION (dossier is the primary output)
--------------------------------------------------
- top_hypothesis_agreement : fraction of repeats whose highest-confidence
                             verdict's hypothesis *name* matches the modal
                             hypothesis (strings are normalized).
- fix_files_jaccard        : mean pairwise Jaccard on `files_changed`.
- metric_delta_recorded    : fraction of repeats that emitted at least one
                             metric_delta.
- metric_delta_mean / sd   : mean and sample SD of the FIRST metric delta's
                             absolute magnitude (|after - before|), when
                             recorded. Highly paper-specific; treat with
                             care.
- dossier_completeness     : fraction of repeats emitting all 5 canonical
                             sections.
- validator_overall_mode   : modal `overall` label across repeats.
- validator_pass_fraction  : mean (pass_count / 7) across repeats.
- cost / tool_calls / duration : same as QC.

Writes `benchmark/results/consistency.json`.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
BENCH_ROOT = ROOT / "benchmark"
RUNS_DIR = BENCH_ROOT / "runs"
RESULTS_DIR = BENCH_ROOT / "results"


# ------------------------- helpers -------------------------

def _safe_sd(xs: list[float]) -> float:
    xs = [x for x in xs if x is not None]
    return float(statistics.stdev(xs)) if len(xs) >= 2 else 0.0


def _safe_mean(xs: list[float]) -> float:
    xs = [x for x in xs if x is not None]
    return float(statistics.mean(xs)) if xs else 0.0


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _mean_pairwise_jaccard(sets: list[set]) -> float:
    if len(sets) < 2:
        return 1.0 if sets else 0.0
    vals = [_jaccard(a, b) for a, b in combinations(sets, 2)]
    return float(statistics.mean(vals)) if vals else 0.0


def _fleiss_kappa(ratings_per_item: list[list[str]], categories: list[str]) -> float:
    """Fleiss' kappa for multiple raters with nominal categories.

    `ratings_per_item[i]` is the list of N rater labels for item i (here:
    N repeats for question i). All items must have the same N.
    Returns 0.0 when undefined (e.g. only one item, zero variance).
    """
    if not ratings_per_item:
        return 0.0
    N = len(ratings_per_item[0])
    if N < 2 or any(len(r) != N for r in ratings_per_item):
        return 0.0
    n_items = len(ratings_per_item)
    k = len(categories)

    # n_ij = number of raters who assigned item i to category j
    n_ij = [[row.count(c) for c in categories] for row in ratings_per_item]
    # p_j = overall proportion assigned to category j
    col_totals = [sum(row[j] for row in n_ij) for j in range(k)]
    total_ratings = n_items * N
    if total_ratings == 0:
        return 0.0
    p_j = [col_totals[j] / total_ratings for j in range(k)]

    # P_i = per-item agreement
    def _P_i(row: list[int]) -> float:
        return (sum(nij * nij for nij in row) - N) / (N * (N - 1))

    P_bar = sum(_P_i(row) for row in n_ij) / n_items
    P_e = sum(pj * pj for pj in p_j)
    if math.isclose(P_e, 1.0):
        return 1.0
    return (P_bar - P_e) / (1.0 - P_e)


# ------------------------- loaders -------------------------

def _load_groups() -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """Return {(paper, mode, question_id): [run_meta dicts for each repeat]}."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    if not RUNS_DIR.exists():
        return groups
    for meta_path in RUNS_DIR.rglob("run_meta.json"):
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            continue
        # Attach the dir path for locating validity_report.json alongside.
        meta["_dir"] = str(meta_path.parent)
        key = (meta.get("paper"), meta.get("mode"), meta.get("question_id"))
        if None in key:
            continue
        groups[key].append(meta)
    # Sort each group by repeat index for stable output.
    for k in groups:
        groups[k].sort(key=lambda m: m.get("repeat_idx", 0))
    return groups


def _load_validity(run_dir: str) -> dict[str, Any] | None:
    p = Path(run_dir) / "validity_report.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


# ------------------------- per-group analysis -------------------------

def _analyze_quick_check_group(runs: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts: list[str | None] = []
    confidences: list[float] = []
    costs: list[float] = []
    durations_s: list[float] = []
    tool_calls: list[int] = []
    file_sets: list[set] = []
    line_sets: list[set] = []
    crashed = 0

    for r in runs:
        qc = r.get("quick_check_verdict") or {}
        verdict = qc.get("verdict") if qc else None
        if not r.get("reached_session_end") or not qc:
            crashed += 1
        verdicts.append(verdict)
        if qc.get("confidence") is not None:
            try:
                confidences.append(float(qc["confidence"]))
            except (TypeError, ValueError):
                pass
        costs.append(float(r.get("cost_usd") or 0.0))
        durations_s.append(float(r.get("duration_ms") or 0) / 1000.0)
        tool_calls.append(int(r.get("tool_calls") or 0))

        files = set()
        lines = set()
        for e in qc.get("evidence") or []:
            f = e.get("file")
            if f:
                files.add(f)
                if e.get("line") is not None:
                    lines.add((f, int(e["line"])))
        file_sets.append(files)
        line_sets.append(lines)

    # Verdict agreement = fraction matching the modal non-None verdict.
    non_none = [v for v in verdicts if v]
    if non_none:
        modal_verdict, modal_count = Counter(non_none).most_common(1)[0]
        agreement = modal_count / len(verdicts)
    else:
        modal_verdict, agreement = None, 0.0

    return {
        "n_repeats": len(runs),
        "crashed": crashed,
        "verdicts": verdicts,
        "modal_verdict": modal_verdict,
        "verdict_agreement": round(agreement, 3),
        "evidence_file_jaccard_pairwise_mean": round(_mean_pairwise_jaccard(file_sets), 3),
        "evidence_line_jaccard_pairwise_mean": round(_mean_pairwise_jaccard(line_sets), 3),
        "confidence_mean": round(_safe_mean(confidences), 3) if confidences else None,
        "confidence_sd": round(_safe_sd(confidences), 3) if len(confidences) >= 2 else None,
        "tool_calls_mean": round(_safe_mean([float(x) for x in tool_calls]), 2),
        "tool_calls_sd": round(_safe_sd([float(x) for x in tool_calls]), 2),
        "cost_mean_usd": round(_safe_mean(costs), 4),
        "cost_sd_usd": round(_safe_sd(costs), 4),
        "duration_mean_s": round(_safe_mean(durations_s), 1),
        "duration_sd_s": round(_safe_sd(durations_s), 1),
    }


def _analyze_deep_group(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze repeats of one Deep Investigation question."""
    top_hypo_names: list[str | None] = []
    fix_file_sets: list[set] = []
    metric_deltas_magnitude: list[float] = []
    # Semantic conclusion per run. Four mutually exclusive buckets:
    #   bug_confirmed   = a verdict was emitted with a fix + metric delta
    #   bug_plausible   = verdict emitted but no fix (cap hit, or sandbox limit)
    #   no_bug          = no verdict, dossier complete, no fix (clean-baseline behaviour)
    #   incomplete      = dossier not complete (truncated run)
    conclusion_types: list[str] = []
    dossier_complete_count = 0
    canonical_sections = {
        "claim_tested", "evidence_gathered", "root_cause",
        "fix_applied", "remaining_uncertainty",
    }
    costs: list[float] = []
    durations_s: list[float] = []
    tool_calls: list[int] = []
    validator_overalls: list[str] = []
    validator_pass_fracs: list[float] = []
    validator_mean_conf: list[float] = []

    for r in runs:
        # Pick the highest-confidence verdict as the "root cause finding"
        verdicts = r.get("verdicts") or []
        hypos = r.get("hypotheses") or []
        top = None
        if verdicts:
            top = max(
                verdicts,
                key=lambda v: (v.get("confidence") if v.get("confidence") is not None else -1),
            )
        top_name = None
        if top and top.get("hypothesis_id"):
            for h in hypos:
                if h.get("id") == top.get("hypothesis_id"):
                    top_name = (h.get("name") or "").strip().lower()
                    break
        top_hypo_names.append(top_name)

        fix = r.get("fix_applied") or {}
        files = set(fix.get("files_changed") or [])
        fix_file_sets.append(files)

        mds = r.get("metric_deltas") or []
        if mds:
            md0 = mds[0]
            try:
                mag = abs(float(md0["after"]) - float(md0["before"]))
                metric_deltas_magnitude.append(mag)
            except (TypeError, ValueError, KeyError):
                pass

        sections = set(r.get("dossier_section_keys") or [])
        dossier_complete = canonical_sections.issubset(sections)
        if dossier_complete:
            dossier_complete_count += 1

        # Classify the run's conclusion for the conclusion-level metric.
        # The agent's own criterion for "actionable bug" (investigator.md
        # constraint 6, "PR only when the fix is real") is: fix applied AND
        # metric delta recorded. Absent that, the run is "no actionable bug"
        # regardless of whether intermediate verdict envelopes were emitted.
        has_fix = bool(files)
        has_delta = bool(mds)
        if not dossier_complete:
            conclusion_types.append("incomplete")
        elif has_fix and has_delta:
            conclusion_types.append("actionable_bug")
        else:
            conclusion_types.append("no_actionable_bug")

        costs.append(float(r.get("cost_usd") or 0.0))
        durations_s.append(float(r.get("duration_ms") or 0) / 1000.0)
        tool_calls.append(int(r.get("tool_calls") or 0))

        v = _load_validity(r["_dir"])
        if v and v.get("ok"):
            payload = v.get("payload") or {}
            overall = str(payload.get("overall") or "").lower()
            if overall:
                validator_overalls.append(overall)
            checks = payload.get("checks") or []
            if checks:
                passes = sum(1 for c in checks if (c.get("mark") or "").lower() == "pass")
                validator_pass_fracs.append(passes / max(len(checks), 1))
            try:
                validator_mean_conf.append(float(payload.get("confidence") or 0.0))
            except (TypeError, ValueError):
                pass

    non_none = [n for n in top_hypo_names if n]
    if non_none:
        modal_name, modal_count = Counter(non_none).most_common(1)[0]
        hypo_agreement = modal_count / len(top_hypo_names)
    else:
        modal_name, hypo_agreement = None, 0.0

    # Conclusion-level agreement: how often did repeats land in the SAME bucket?
    # This treats unanimous "no bug" as 1.0 (which the top-hypothesis metric
    # cannot express because there's no hypothesis to name).
    modal_conclusion, modal_conclusion_count = Counter(conclusion_types).most_common(1)[0]
    conclusion_agreement = modal_conclusion_count / len(conclusion_types) if conclusion_types else 0.0

    validator_modal = None
    if validator_overalls:
        validator_modal, _ = Counter(validator_overalls).most_common(1)[0]

    n = len(runs)
    return {
        "n_repeats": n,
        "top_hypothesis_names": top_hypo_names,
        "modal_top_hypothesis": modal_name,
        "top_hypothesis_agreement": round(hypo_agreement, 3),
        "conclusion_types": conclusion_types,
        "modal_conclusion": modal_conclusion,
        "conclusion_agreement": round(conclusion_agreement, 3),
        "fix_files_jaccard_pairwise_mean": round(_mean_pairwise_jaccard(fix_file_sets), 3),
        "any_fix_applied_fraction": round(
            sum(1 for s in fix_file_sets if s) / n, 3
        ),
        "metric_delta_recorded_fraction": round(
            len(metric_deltas_magnitude) / n, 3
        ) if n else 0.0,
        "metric_delta_magnitude_mean": round(_safe_mean(metric_deltas_magnitude), 4)
            if metric_deltas_magnitude else None,
        "metric_delta_magnitude_sd": round(_safe_sd(metric_deltas_magnitude), 4)
            if len(metric_deltas_magnitude) >= 2 else None,
        "dossier_completeness_fraction": round(dossier_complete_count / n, 3),
        "validator_overall_mode": validator_modal,
        "validator_overalls": validator_overalls,
        "validator_pass_fraction_mean": round(_safe_mean(validator_pass_fracs), 3)
            if validator_pass_fracs else None,
        "validator_pass_fraction_sd": round(_safe_sd(validator_pass_fracs), 3)
            if len(validator_pass_fracs) >= 2 else None,
        "validator_confidence_mean": round(_safe_mean(validator_mean_conf), 3)
            if validator_mean_conf else None,
        "cost_mean_usd": round(_safe_mean(costs), 4),
        "cost_sd_usd": round(_safe_sd(costs), 4),
        "duration_mean_s": round(_safe_mean(durations_s), 1),
        "duration_sd_s": round(_safe_sd(durations_s), 1),
        "tool_calls_mean": round(_safe_mean([float(x) for x in tool_calls]), 2),
        "tool_calls_sd": round(_safe_sd([float(x) for x in tool_calls]), 2),
    }


def _paper_level_fleiss(groups: dict[tuple[str, str, str], list[dict[str, Any]]],
                        paper: str, mode: str) -> dict[str, Any]:
    """Fleiss' kappa across all questions of one (paper, mode) pair.

    Only makes sense for Quick Check (verdict labels). For Deep mode, we
    return None: "top hypothesis name" is an unbounded category space.
    """
    items: list[list[str]] = []
    for (p, m, _q), runs in groups.items():
        if p != paper or m != mode:
            continue
        labels: list[str] = []
        for r in runs:
            qc = r.get("quick_check_verdict") or {}
            v = qc.get("verdict")
            if v is None:
                v = "unclear"
            labels.append(v)
        if labels:
            items.append(labels)
    if not items:
        return {"applicable": False}
    # Pad to same length with the modal-per-item value.
    n_max = max(len(row) for row in items)
    padded: list[list[str]] = []
    for row in items:
        if len(row) < n_max:
            fill = Counter(row).most_common(1)[0][0]
            row = row + [fill] * (n_max - len(row))
        padded.append(row)
    kappa = _fleiss_kappa(padded, categories=["confirmed", "refuted", "unclear"])
    return {
        "applicable": True,
        "n_questions": len(padded),
        "n_repeats": n_max,
        "kappa": round(kappa, 3),
    }


# ------------------------- main -------------------------

def main() -> None:
    groups = _load_groups()
    if not groups:
        print("[analyze] No run_meta.json files found under benchmark/runs/.")
        return

    per_group: dict[str, dict[str, Any]] = {}
    for key, runs in sorted(groups.items()):
        paper, mode, q_id = key
        label = f"{paper}/{mode}/{q_id}"
        if mode == "check":
            per_group[label] = _analyze_quick_check_group(runs)
        elif mode == "investigate":
            per_group[label] = _analyze_deep_group(runs)
        else:
            per_group[label] = {"error": f"unknown mode: {mode}"}

    # Aggregate per (paper, mode)
    aggregates: dict[str, Any] = {}
    papers = sorted({k[0] for k in groups})
    for paper in papers:
        for mode in ("check", "investigate"):
            sub_keys = [k for k in groups if k[0] == paper and k[1] == mode]
            if not sub_keys:
                continue
            label = f"{paper}/{mode}"
            sub = {f"{k[2]}": per_group[f"{paper}/{mode}/{k[2]}"] for k in sub_keys}
            agg: dict[str, Any] = {"n_questions": len(sub_keys)}
            if mode == "check":
                agg["mean_verdict_agreement"] = round(_safe_mean(
                    [v["verdict_agreement"] for v in sub.values()]), 3)
                agg["mean_evidence_file_jaccard"] = round(_safe_mean(
                    [v["evidence_file_jaccard_pairwise_mean"] for v in sub.values()]), 3)
                agg["mean_evidence_line_jaccard"] = round(_safe_mean(
                    [v["evidence_line_jaccard_pairwise_mean"] for v in sub.values()]), 3)
                agg["mean_confidence_sd"] = round(_safe_mean(
                    [v["confidence_sd"] for v in sub.values() if v.get("confidence_sd") is not None]), 3)
                agg["fleiss_kappa"] = _paper_level_fleiss(groups, paper, mode)
            else:
                agg["mean_top_hypothesis_agreement"] = round(_safe_mean(
                    [v["top_hypothesis_agreement"] for v in sub.values()]), 3)
                agg["mean_conclusion_agreement"] = round(_safe_mean(
                    [v["conclusion_agreement"] for v in sub.values()]), 3)
                agg["modal_conclusions"] = [v.get("modal_conclusion") for v in sub.values()]
                agg["mean_fix_files_jaccard"] = round(_safe_mean(
                    [v["fix_files_jaccard_pairwise_mean"] for v in sub.values()]), 3)
                agg["dossier_completeness_fraction"] = round(_safe_mean(
                    [v["dossier_completeness_fraction"] for v in sub.values()]), 3)
                agg["mean_validator_pass_fraction"] = round(_safe_mean(
                    [v["validator_pass_fraction_mean"] for v in sub.values()
                     if v.get("validator_pass_fraction_mean") is not None]), 3)
            agg["mean_cost_usd"] = round(_safe_mean(
                [v["cost_mean_usd"] for v in sub.values()]), 4)
            agg["mean_duration_s"] = round(_safe_mean(
                [v["duration_mean_s"] for v in sub.values()]), 1)
            aggregates[label] = agg

    out = {
        "schema_version": 1,
        "per_group": per_group,
        "aggregates": aggregates,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "consistency.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"[analyze] wrote {path}")
    print(f"[analyze] {len(per_group)} groups, {len(aggregates)} (paper, mode) aggregates")


if __name__ == "__main__":
    main()
