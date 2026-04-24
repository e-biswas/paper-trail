## claim_tested

The paper claims TabM — a BatchEnsemble-style parameter-efficient ensemble of k=32 MLPs with adapter-induced diversity (random-sign scaling on the first-layer R adapter, ones elsewhere) — matches a traditional deep ensemble of k independently trained MLPs at a fraction of the parameter count. Specifically audited: (a) whether k is actually varied in sweeps or hard-coded; (b) whether aggregation is the claimed mean-of-predictions rule or something else (majority vote, learned weighting); (c) whether per-benchmark hyperparameters are traceable to committed configs; (d) whether parameter-count accounting is consistent between TabM and the deep-ensemble baseline.

## evidence_gathered

- **Aggregation (c1):** `paper/bin/model.py:536–543` applies `scipy.special.softmax` then `.mean(1)` over the k-submodel axis for classification; regression denormalizes then means. This is mean-of-probabilities, which matches the conventional deep-ensemble aggregation used by Lakshminarayanan 2017 and the BatchEnsemble paper. No alternative (majority-vote, learned weighting) is applied.
- **Training loss (c1):** `paper/bin/model.py:441–449` flattens (B, k) and computes cross-entropy per submodel prediction, so the k submodels are trained as k independent predictors — matches the paper's Section 3.3.
- **k sweep (c2):** Grep across `paper/exp/**/*.toml` returns 12,224 hits for `k = 32` and ZERO hits for any other k. Every tuning space (`0-tuning.toml`) and every per-seed evaluation TOML pins k=32. Example: `paper/exp/tabm/adult/0-tuning.toml:40`. The paper's Section 5.3 k-ablation is not reproducible from the committed `exp/` tree alone.
- **Head selection / test contamination (c3):** `paper/bin/model.py:715–724` computes per-head val scores via `dataset.task.calculate_metrics({'val': head_predictions['val'][:, i]}, ...)` and picks `best_head_idx = int(np.argmax(head_val_scores))`. TabM[G] greedy at `paper/bin/model.py:748–776` scores candidates on val only. Test metrics are reported once on the selected heads at line 734 and line 786.
- **Parameter counting (c4):** `paper/bin/model.py:409` calls `lib.deep.get_n_parameters(model)` on the full `Model`. `LinearEfficientEnsemble` registers `weight`, `r`, `s`, `bias` all as `nn.Parameter` (tabm.py:585–597 and the lib/deep.py parity), so `module.parameters()` traversal captures adapters, embeddings, shared backbone, and output NLinear uniformly for both TabM and MLP×k.
- **Training-batch diversity (c5):** Tuning configs set `share_training_batches = false` (e.g. `paper/exp/tabm/adult/0-tuning.toml:41`), and the training loop (`paper/bin/model.py:586–596`) uses `torch.rand((k, n_train)).argsort(dim=1)` to generate k independent shuffles — real per-submodel diversity, matching the paper.

## root_cause

No bug identified. The repository's training / evaluation / head-selection / parameter-counting protocol is consistent with the paper's claims on all four audited dimensions. The single concern — k=32 hard-coded across 12,224 config entries — is a transparency gap for the Section 5.3 ablation, not a defect in the headline TabM-vs-deep-ensemble comparison, because that comparison consistently uses k=32 for both sides as the paper reports.

## fix_applied

None. Per the operating contract (constraint 6: "PR only when the fix is real") and the benchmark-case instruction ("Do NOT fabricate a problem to find"), no code change was made. No `## Metric delta:` is emitted because no fix was applied and no re-run was performed.

## remaining_uncertainty

- I did not execute the training pipeline (would require GPU + 10+ minute runs per dataset). Audit is code-reading only; the runtime behavior could in principle diverge from the code on hardware-specific paths (AMP, compile), but those paths are clearly gated behind opt-in flags and the default `amp=false, compile=false` path is the one reviewed.
- The paper's Section 5.3 k-ablation data lives outside the committed `exp/` tree; I cannot independently verify the ablation's numeric curve from this repo alone — only that the production sweep pins k=32.
- I did not inspect `paper/lib/metrics.py` line-by-line for per-task metric definitions; I relied on `dataset.task.calculate_metrics` being sklearn-standard (ROC-AUC / accuracy / RMSE) based on prose in `paper/README.md`. A hand-rolled metric that diverges from its name would not be caught by this audit.
- I did not audit the CatBoost / XGBoost / FT-Transformer baseline configs (`paper/exp/mlp*`, etc.) for fairness of comparison — only the TabM path and its claimed `MLP×k` / deep-ensemble counterpart at the aggregation level.
- The `tabm_reference.py` file is marked DEPRECATED; I treated `tabm.py` + `paper/bin/model.py` as the canonical code paths.