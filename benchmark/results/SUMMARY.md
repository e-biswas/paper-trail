# Paper Trail — consistency benchmark

_Auto-generated from `benchmark/results/consistency.json` by `benchmark/scripts/make_report.py`. See `benchmark/README.md` for methodology and metric definitions._

## Aggregate — per (paper, mode)

Single-cell summary. *Agreement* is verdict-agreement for Quick Check and top-hypothesis agreement for Deep. *Jaccard* is evidence-line Jaccard for Quick Check and fix-files Jaccard for Deep. *κ* is Fleiss' kappa on verdict labels (Quick Check only).

| Paper / Mode | Qs | Agreement | Jaccard | Dossier | Val. pass | κ | Avg cost | Avg duration |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `gidd/check` | 5 | 0.800 | 0.264 | — | — | 0.286 | $0.095 | 15s |
| `gidd/investigate` | 1 | 1.000 | 1.000 | 1.000 | 0.667 | — | $1.643 | 249s |
| `tabm/check` | 3 | 0.778 | 0.177 | — | — | 0.438 | $0.137 | 18s |
| `tabm/investigate` | 1 | 1.000 | 1.000 | 1.000 | 0.857 | — | $1.679 | 234s |

## gidd

### Quick Check

| Question | Modal | Agreement | File Jaccard | Line Jaccard | Conf mean ± sd | Cost ± sd | Tool calls |
|---|---|---:|---:|---:|---:|---:|---:|
| `qc1_cpu_tpu` | unclear | 0.667 | 0.289 | 0.133 | 0.67 ± 0.20 | $0.074 ± 0.012 | 3.3 ± 0.6 |
| `qc2_sweeps` | refuted | 0.667 | 0.383 | 0.111 | 0.71 ± 0.18 | $0.073 ± 0.010 | 4.0 ± 0.0 |
| `qc3_checkpoints` | confirmed | 1.000 | 1.000 | 0.576 | 0.98 ± 0.00 | $0.141 ± 0.066 | 2.3 ± 0.6 |
| `qc4_data_pinning` | confirmed | 0.667 | 0.389 | 0.248 | 0.89 ± 0.04 | $0.108 ± 0.018 | 2.0 ± 1.0 |
| `qc5_interp_param` | confirmed | 1.000 | 0.167 | 0.250 | 0.89 ± 0.01 | $0.079 ± 0.012 | 3.7 ± 0.6 |

### Deep Investigation

| Question | Modal conclusion | Conclusion agreement | Top-hypo agreement | Dossier complete | Validator | Cost ± sd | Duration ± sd |
|---|---|---:|---:|---:|---|---:|---:|
| `deep_hybrid_schedule` | no_actionable_bug | 1.000 | 0.333 | 1.000 | acceptable (pass 0.67) | $1.643 ± 0.365 | 249s ± 24s |

## tabm

### Quick Check

| Question | Modal | Agreement | File Jaccard | Line Jaccard | Conf mean ± sd | Cost ± sd | Tool calls |
|---|---|---:|---:|---:|---:|---:|---:|
| `qc1_split_leak` | confirmed | 1.000 | 0.333 | 0.083 | 0.91 ± 0.01 | $0.217 ± 0.070 | 2.3 ± 0.6 |
| `qc2_group_splits` | confirmed | 0.333 | 0.333 | 0.222 | 0.75 ± 0.17 | $0.108 ± 0.053 | 4.0 ± 0.0 |
| `qc3_test_contam` | refuted | 1.000 | 0.556 | 0.225 | 0.91 ± 0.01 | $0.086 ± 0.013 | 3.7 ± 0.6 |

### Deep Investigation

| Question | Modal conclusion | Conclusion agreement | Top-hypo agreement | Dossier complete | Validator | Cost ± sd | Duration ± sd |
|---|---|---:|---:|---:|---|---:|---:|
| `deep_ensemble_audit` | no_actionable_bug | 1.000 | 0.000 | 1.000 | strong (pass 0.86) | $1.679 ± 0.540 | 234s ± 32s |

## How to read this

- **Verdict agreement** (Quick Check) = fraction of repeats whose verdict label (confirmed / refuted / unclear) equals the modal verdict. 1.0 means every repeat produced the same label.
- **Fleiss' κ** corrects verdict-agreement for chance. κ > 0.6 is substantial; κ > 0.8 is near-perfect. Computed per (paper, mode).
- **Evidence Jaccard** (Quick Check) measures whether the agent cites the same (file, line) tuples across repeats.
- **Modal conclusion + conclusion agreement** (Deep) classifies each repeat into `actionable_bug` (fix applied AND metric delta moved — the agent's own criterion for a real bug) or `no_actionable_bug` (no fix, or fix without verified metric movement). Agreement = fraction in the modal bucket. This is the honest consistency signal for Deep runs; the top-hypothesis metric below is strictly stricter (lexical identity) and mis-measures unanimous no-bug runs.
- **Top-hypothesis agreement** = fraction of repeats whose highest-confidence verdict named the same hypothesis. Meaningful only when a verdict was emitted; 0 can mean disagreement OR unanimous 'no verdict'.
- **Dossier completeness** = fraction of repeats that emitted all five canonical sections.
- **Validator pass fraction** = mean (pass-count / 7) over repeats; a second Opus pass grades the investigation independently.
- **Cost / duration / tool-calls** are scalar dispersion signals — the smaller the SD, the more predictable the run.

*Caveat.* LLM outputs vary across calls by design (temperature, sampling). Expect phrasing drift; the metrics above focus on decision-relevant fields that should be stable under faithful reproduction.
