## claim_tested

The paper (arXiv 2512.10858) claims that discrete diffusion LMs — masked, uniform, and hybrid — scale competitively with ALMs, and that uniform diffusion in particular is more token-efficient at compute-optimality, with a 10B-parameter uniform-diffusion model trained to 10²² FLOPs validating the predicted scaling law. The reproducibility-relevant sub-claim that can in principle be attacked at small scale is the **masked-vs-uniform PPL comparison** (the core of Fig. 1 and Fig. 2), because the numerical gap between noise types hinges on how the training loss handles the "mask" token in the output distribution.

## evidence_gathered

- **`gidd_easydel/diffusion_trainer/loss.py:85`** — `logits = logits.at[..., self.mask_token_id].set(-1e6)` runs unconditionally inside `GiddLoss.__call__`, with no branch on `prior_distribution`. Under `Priors.UNIFORM`, `mask_token_id` defaults to `-1` (the last vocab index) via `create_mixing_schedule(…, mask_token_id=-1)` at `gidd_easydel/diffusion_trainer/schedule.py:443`; that last vocab entry is a real token, so its logit is artificially pinned at −1e6 for every forward pass of every uniform-diffusion run.
- **`gidd_easydel/diffusion_trainer/schedule.py:158–197, 488–498`** — `GeneralMixingDistribution` is commented out and the `distribution="general"` factory branch is commented out; calling the factory with that string raises `Unknown MixingDistribution type: general`. This is not wired to the scaling experiments but breaks the extensibility advertised in Section 2.4.
- **`tests/test_schedule.py:607`** — author comment: *"Note: get_loss_weights currently has a bug with pi_lambda_prime_from_ids"* with the follow-up `assert jnp.allclose(elbo_weights, loss_weights / p_log_snr)` commented out. An active, documented, unresolved loss-weight bug in the codebase.
- **`tests/test_schedule.py`** uses method names `pi_lambda_prime_from_ids` and `pi_lambda_from_ids` throughout; `schedule.py` exposes only the `_at_ids` variants — the test suite is currently un-runnable even if JAX were installed.
- **No `eval.py`** / `reproduce*.py` / `METRIC_JSON` emitter in the repo (Grep `METRIC_JSON` → zero `.py` hits; only notebooks reference the word). The only eval entrypoint is `eval_ray.py`, which submits a TPU job to the `dvruette/lm-evaluation-harness` fork.
- **Environment** — `/Users/eb/Downloads/experiments/paper-trail/.venv/bin/python -c 'import jax'` → `ModuleNotFoundError`; requirements demand `jax==0.7.1` plus `EasyDeL` / `eformer` / `orbax` custom forks, which are not installed.

## root_cause

Not determined. Three candidate code-level defects were identified but none could be promoted to a ratified verdict without a runnable `## Metric delta:`. The most mechanically plausible (h1) is the unconditional mask-token logit suppression in `loss.py:85`, which under uniform diffusion excludes one legitimate vocabulary entry from the output distribution and therefore biases the masked-vs-uniform PPL comparison that drives Fig. 1 / Fig. 2. The most flagrant symptom (h2) is the author's own comment in `tests/test_schedule.py:607` that `get_loss_weights` has a bug coupled to `pi_lambda_prime_from_ids`, but the accompanying test is non-executable because of API name drift, so the bug is latent and unverified.

## fix_applied

None. Per the operating contract, no fix is written when a `## Metric delta:` block showing `after != before` cannot be produced. The investigation was aborted at step 10 of the loop.

## remaining_uncertainty

- I **did not execute** any Python in this investigation — the venv has no JAX and the repo has no small eval fixture. Every claim about `pi_lambda_at_ids`, `get_loss_weights`, and `loss.py` is from static reading.
- I **did not verify** the effect size of `loss.py:85` under uniform diffusion. At vocab ≈ 50 257 (GPT-NeoX/Llama-style tokenizer shipped in `tokenizer/`), the theoretical bias on PPL is small but not negligible for scaling-law fits. A proper check would retrain a ~25M-param model at one step with and without the conditional suppression.
- I **did not verify** the loss-weight bug the author flagged in `tests/test_schedule.py:607`. The hand-trace on a single point (log_snr=0, input_ids=5, labels=10, V=100, mask=99) produces `loss_weights ≈ 0.5` and `elbo = 2.0` with no numerical anomaly, so the bug may lie in (a) broadcasting at batch shape, (b) dtype promotion (`safe_sigmoid` casts to float32 then back), or (c) the `clip(1e-8)` floor interacting with the `(pi_at_z - pi_prime_at_z)` numerator near log_snr extremes — all untested here.
- I **did not re-read** the `main_gpu.py` / `train.py` paths to confirm which of the `GeneralMixingDistribution` / `HybridMixingDistribution` / uniform-prior configurations is the default for the scaling-law table; a human reviewer should confirm that the hybrid-mixing-shift=1000 command in the README reliably selects masked-like behaviour and not the uniform path that triggers h1.
- I **cannot attribute** the paper's published `Train. PPL` numbers (10B uniform = 9.15; 3B mask = 11.3; 3B uniform = 11.7) to this codebase vs. the actual large-scale TPU runs — those runs used the `dvruette/EasyDeL` / `dvruette/eformer` forks which are not pinned to a commit in `requirements.txt`, so a sha drift could also account for any local-vs-paper discrepancy.

Auto PR is OFF for this run; no branch or PR will be opened. The user should review the three candidate defects above and, if they want the investigation continued, either provide a runnable small-sample fixture (tokenized shard + 1-step eval script that prints `METRIC_JSON:`) or run this investigator in an environment where JAX 0.7.1 + the four custom forks are installed.