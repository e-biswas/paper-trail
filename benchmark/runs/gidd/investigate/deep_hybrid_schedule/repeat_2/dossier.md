## claim_tested

The paper's central methodological contribution is a hybrid discrete-diffusion noise schedule π_λ = σ(aλ+b)·u + σ(−(aλ+b))·m, where a=`hybrid_mixing_scale` and b=`hybrid_mixing_shift` smoothly interpolate between masked and uniform diffusion (§2.4, Eq. 7). The paper states: "In our experiments, we fix a = 1 for simplicity." The reproducibility-relevant claim is therefore that (i) training honors both (a, b), (ii) inference/likelihood honors both (a, b) so train/infer agree, and (iii) the JAX and PyTorch inference paths are consistent.

## evidence_gathered

**Training path — correct.**
- `args.py:52-53` declares `--hybrid_mixing_scale` (default 1.0) and `--hybrid_mixing_shift` (default 0.0).
- `gidd_easydel/train.py:333-334` forwards both to `CustomDiffusionConfig`.
- `gidd_easydel/diffusion_trainer/diffusion_config.py:36-37` stores both as dataclass fields.
- `gidd_easydel/diffusion_trainer/diffusion_trainer.py:68-69` passes both to `create_mixing_schedule`.
- `gidd_easydel/diffusion_trainer/schedule.py:499-507` constructs `HybridMixingDistribution(scale=hybrid_scale, shift=hybrid_shift)`.
- `schedule.py:224` (`pi_lambda`), `:230` (`pi_lambda_at_ids`), `:236-238` (`pi_lambda_prime`), `:242-244` (`pi_lambda_prime_at_ids`), `:248` (`sample_marginals`) all use `self.scale * log_snr + self.shift`.
- `gidd_easydel/diffusion_trainer/loss.py:64-114` drives the GIDD ELBO through this schedule — scale is faithfully honored in every ELBO weight.

**JAX inference path — silent scale hardcoding.**
- `gidd_easydel/sampling.py:16-23` defines a standalone `pi_lambda(log_snr, shift=0.0, ...)` that computes `alpha = safe_sigmoid(log_snr + shift)` — **no scale argument**.
- `sampling.py:54, 77-78` (`ancestral_sampling_step`), `:112, 131` (`adaptive_sampling_step`), `:182, 274` (`generate`) take only `hybrid_mixing_shift`.
- `gidd_easydel/likelihood.py:125` — `likelihood(...)` signature accepts only `hybrid_mixing_shift: float`.
- `likelihood.py:155-163` calls `create_mixing_schedule(..., hybrid_shift=hybrid_mixing_shift, ...)` — `hybrid_scale` argument is omitted, so it defaults to 1.0 per `schedule.py:444`.

**PyTorch fallback — scale hardcoded, shift renamed to `noise_type`.**
- `gidd_easydel/model/configuration_gidd.py:36` declares `noise_type: float = 0.0` on `GiddConfig`. No scale-equivalent field.
- `gidd_easydel/model/modeling_gidd_hf.py:855-861`: `_pi_lambda` computes `alpha = torch.sigmoid(log_snr + self.config.noise_type)` — structurally identical to `sampling.py:20`, scale implicitly 1.0.
- The generate signature at `modeling_gidd_hf.py:928-946` exposes no `prior_distribution` argument, so a user loading `dvruette/gidd-unif-10b` (uniform-prior, per README) via the PyTorch example at README L32-57 will implicitly start from the mask token — not uniform noise as the JAX `sampling.py:234-239` / `likelihood.py:177-182` branches do.

## root_cause

Three independent π_λ reimplementations exist in the repo: the canonical `HybridMixingDistribution` class (JAX training), the standalone `pi_lambda` helper in `sampling.py`, and `_pi_lambda` in `modeling_gidd_hf.py`. Only the first honors the hybrid scale `a`; the other two hardcode a=1. Because the paper explicitly fixes a=1 in all experiments (§2.4), no reported scaling-curve number is affected. However, `--hybrid_mixing_scale` is exposed as a first-class CLI-configurable training knob, so anyone training with `a ≠ 1` gets a silent train/infer schedule mismatch. A second, independent asymmetry: HF `generate()` has no prior-distribution argument, so a uniform-prior checkpoint loaded via the README quick-start example silently denoises from the mask token in PyTorch.

## fix_applied

None. A code fix — plumbing `hybrid_mixing_scale` through `sampling.py::pi_lambda`, `sampling.py::{ancestral,adaptive,generate}` signatures, `likelihood.py::likelihood`, `GiddConfig.noise_scale`, `modeling_gidd_hf.py::_pi_lambda`, and adding a `prior_distribution` argument to `modeling_gidd_hf.py::generate()` — is straightforward and would be <50 lines. But this fixture ships no `eval.py` / CPU-feasible inference reproducer (10B JAX checkpoints and HF weights are infeasible in the sandbox), so the required post-fix `## Metric delta:` cannot be produced. Per the operating contract ("re-run the eval after the fix; if the metric didn't move or moved in the wrong direction, do not declare success"), no edit is committed. The recommended minimal fix, for reviewer reference:

1. `sampling.py:16` → `def pi_lambda(log_snr, scale=1.0, shift=0.0, mask_token_id=3, vocab_size=131072):` and update `alpha = safe_sigmoid(scale * log_snr + shift)`; add `hybrid_mixing_scale` to `ancestral_sampling_step`, `adaptive_sampling_step`, `generate`, and the two `jax.jit` static_argnames lists.
2. `likelihood.py:125` → add `hybrid_mixing_scale: float = 1.0`; `:160` → pass `hybrid_scale=hybrid_mixing_scale` into `create_mixing_schedule`.
3. `configuration_gidd.py:36` → add `noise_scale: float = 1.0` alongside `noise_type`; `modeling_gidd_hf.py:858` → `alpha = torch.sigmoid(self.config.noise_scale * log_snr + self.config.noise_type)`.
4. `modeling_gidd_hf.py:928` → add `prior: tp.Literal["mask","uniform"] = "mask"` and branch the initial noise fill accordingly.
5. Rename `noise_type` → `hybrid_mixing_shift` at the config level (with a backward-compat alias) so the field name reflects its role.

## remaining_uncertainty

- **Not verified with a metric.** No small-scale inference fixture exists in this repo; I could not surface a `METRIC_JSON` before/after to confirm the proposed fix moves a number. The fix is a static-correctness / API-consistency improvement, not a metric-moving bug for any shipped (a=1) config.
- **Impact on published results.** The paper explicitly fixes a=1, so none of the 25M–10B scaling experiments are affected by the scale-hardcoding. I did not find evidence of any run in the paper that used a≠1, so the reported scaling curves stand.
- **Downstream effects of the uniform-prior asymmetry.** I did not numerically quantify how much the HF mask-only init hurts generation quality on a uniform-prior checkpoint. The ancestral step (`modeling_gidd_hf.py:871-891`) recomputes q_t from the current z at every step, which may partially absorb a wrong init, but this is not proven.
- **Convention-vs-bug judgment.** Some readers could argue that hardcoding a=1 in inference is a deliberate simplification and that the training-side `--hybrid_mixing_scale` flag is the unused artifact. The repo has no assertion or warning in either direction.
- **Third-party evaluation fork.** The README (L90-94) points to `dvruette/lm-evaluation-harness` as the canonical evaluator. I did not inspect that fork; if it threads `hybrid_mixing_scale` differently, that would further change the picture.