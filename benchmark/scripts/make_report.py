"""Render benchmark/results/SUMMARY.md from consistency.json.

Separate from analyze_consistency.py so we can iterate on the markdown
without re-running expensive analysis or API calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
BENCH_ROOT = ROOT / "benchmark"
RESULTS_DIR = BENCH_ROOT / "results"


def _fmt(val: Any, suffix: str = "") -> str:
    if val is None:
        return "—"
    if isinstance(val, float):
        return f"{val:.3f}{suffix}"
    return f"{val}{suffix}"


def _quick_check_table(per_group: dict[str, Any], paper: str) -> str:
    rows = []
    header = ("| Question | Modal | Agreement | File Jaccard | Line Jaccard | "
              "Conf mean ± sd | Cost ± sd | Tool calls |\n"
              "|---|---|---:|---:|---:|---:|---:|---:|\n")
    for label, stats in sorted(per_group.items()):
        if not label.startswith(f"{paper}/check/"):
            continue
        q = label.split("/")[-1]
        modal = stats.get("modal_verdict") or "—"
        agreement = _fmt(stats.get("verdict_agreement"))
        fj = _fmt(stats.get("evidence_file_jaccard_pairwise_mean"))
        lj = _fmt(stats.get("evidence_line_jaccard_pairwise_mean"))
        cm = stats.get("confidence_mean")
        cs = stats.get("confidence_sd")
        conf_cell = f"{cm:.2f} ± {cs:.2f}" if cm is not None and cs is not None else "—"
        cost = f"${stats.get('cost_mean_usd', 0):.3f} ± {stats.get('cost_sd_usd', 0):.3f}"
        tc = f"{stats.get('tool_calls_mean', 0):.1f} ± {stats.get('tool_calls_sd', 0):.1f}"
        rows.append(f"| `{q}` | {modal} | {agreement} | {fj} | {lj} | {conf_cell} | {cost} | {tc} |")
    return header + "\n".join(rows) + "\n"


def _deep_table(per_group: dict[str, Any], paper: str) -> str:
    header = ("| Question | Modal conclusion | Conclusion agreement | "
              "Top-hypo agreement | Dossier complete | Validator | Cost ± sd | Duration ± sd |\n"
              "|---|---|---:|---:|---:|---|---:|---:|\n")
    rows = []
    for label, stats in sorted(per_group.items()):
        if not label.startswith(f"{paper}/investigate/"):
            continue
        q = label.split("/")[-1]
        rows.append("| `{q}` | {concl} | {conclagree} | {agree} | {dos} | {val} | {cost} | {dur} |".format(
            q=q,
            concl=stats.get("modal_conclusion") or "—",
            conclagree=_fmt(stats.get("conclusion_agreement")),
            agree=_fmt(stats.get("top_hypothesis_agreement")),
            dos=_fmt(stats.get("dossier_completeness_fraction")),
            val=(stats.get("validator_overall_mode") or "—") +
                (f" (pass {stats['validator_pass_fraction_mean']:.2f})"
                 if stats.get("validator_pass_fraction_mean") is not None else ""),
            cost=f"${stats.get('cost_mean_usd', 0):.3f} ± {stats.get('cost_sd_usd', 0):.3f}",
            dur=f"{stats.get('duration_mean_s', 0):.0f}s ± {stats.get('duration_sd_s', 0):.0f}s",
        ))
    return header + "\n".join(rows) + "\n"


def _aggregate_table(aggregates: dict[str, Any]) -> str:
    lines = [
        "| Paper / Mode | Qs | Agreement | Jaccard | Dossier | Val. pass | κ | Avg cost | Avg duration |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, agg in sorted(aggregates.items()):
        kappa = "—"
        k = agg.get("fleiss_kappa")
        if isinstance(k, dict) and k.get("applicable"):
            kappa = f"{k['kappa']:.3f}"
        agreement = (
            agg.get("mean_verdict_agreement")
            if "mean_verdict_agreement" in agg
            else agg.get("mean_conclusion_agreement")
        )
        jaccard = (
            agg.get("mean_evidence_line_jaccard")
            if "mean_evidence_line_jaccard" in agg
            else agg.get("mean_fix_files_jaccard")
        )
        dossier = agg.get("dossier_completeness_fraction")
        val_pass = agg.get("mean_validator_pass_fraction")
        lines.append(
            f"| `{label}` | {agg.get('n_questions', 0)} | "
            f"{_fmt(agreement)} | {_fmt(jaccard)} | {_fmt(dossier)} | {_fmt(val_pass)} | {kappa} | "
            f"${agg.get('mean_cost_usd', 0):.3f} | {agg.get('mean_duration_s', 0):.0f}s |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    path = RESULTS_DIR / "consistency.json"
    if not path.exists():
        print(f"error: {path} does not exist. Run analyze_consistency.py first.")
        sys.exit(1)

    data = json.loads(path.read_text())
    per_group = data.get("per_group") or {}
    aggregates = data.get("aggregates") or {}
    papers = sorted({label.split("/")[0] for label in per_group})

    lines: list[str] = []
    lines.append("# Paper Trail — consistency benchmark")
    lines.append("")
    lines.append(
        "_Auto-generated from `benchmark/results/consistency.json` by "
        "`benchmark/scripts/make_report.py`. See `benchmark/README.md` for "
        "methodology and metric definitions._"
    )
    lines.append("")

    lines.append("## Aggregate — per (paper, mode)")
    lines.append("")
    lines.append(
        "Single-cell summary. *Agreement* is verdict-agreement for Quick Check "
        "and top-hypothesis agreement for Deep. *Jaccard* is evidence-line "
        "Jaccard for Quick Check and fix-files Jaccard for Deep. *κ* is "
        "Fleiss' kappa on verdict labels (Quick Check only)."
    )
    lines.append("")
    lines.append(_aggregate_table(aggregates))

    for paper in papers:
        lines.append(f"## {paper}")
        lines.append("")
        if any(label.startswith(f"{paper}/check/") for label in per_group):
            lines.append("### Quick Check")
            lines.append("")
            lines.append(_quick_check_table(per_group, paper))
        if any(label.startswith(f"{paper}/investigate/") for label in per_group):
            lines.append("### Deep Investigation")
            lines.append("")
            lines.append(_deep_table(per_group, paper))

    lines.append("## How to read this")
    lines.append("")
    lines.append(
        "- **Verdict agreement** (Quick Check) = fraction of repeats whose "
        "verdict label (confirmed / refuted / unclear) equals the modal "
        "verdict. 1.0 means every repeat produced the same label.\n"
        "- **Fleiss' κ** corrects verdict-agreement for chance. κ > 0.6 is "
        "substantial; κ > 0.8 is near-perfect. Computed per (paper, mode).\n"
        "- **Evidence Jaccard** (Quick Check) measures whether the agent "
        "cites the same (file, line) tuples across repeats.\n"
        "- **Modal conclusion + conclusion agreement** (Deep) classifies each "
        "repeat into `actionable_bug` (fix applied AND metric delta moved — "
        "the agent's own criterion for a real bug) or `no_actionable_bug` "
        "(no fix, or fix without verified metric movement). Agreement = "
        "fraction in the modal bucket. This is the honest consistency "
        "signal for Deep runs; the top-hypothesis metric below is strictly "
        "stricter (lexical identity) and mis-measures unanimous no-bug runs.\n"
        "- **Top-hypothesis agreement** = fraction of repeats whose highest-"
        "confidence verdict named the same hypothesis. Meaningful only "
        "when a verdict was emitted; 0 can mean disagreement OR unanimous "
        "'no verdict'.\n"
        "- **Dossier completeness** = fraction of repeats that emitted all "
        "five canonical sections.\n"
        "- **Validator pass fraction** = mean (pass-count / 7) over repeats; "
        "a second Opus pass grades the investigation independently.\n"
        "- **Cost / duration / tool-calls** are scalar dispersion signals — "
        "the smaller the SD, the more predictable the run.\n"
        "\n"
        "*Caveat.* LLM outputs vary across calls by design (temperature, "
        "sampling). Expect phrasing drift; the metrics above focus on "
        "decision-relevant fields that should be stable under faithful "
        "reproduction."
    )
    lines.append("")

    out = RESULTS_DIR / "SUMMARY.md"
    out.write_text("\n".join(lines))
    print(f"[report] wrote {out}")


if __name__ == "__main__":
    main()
