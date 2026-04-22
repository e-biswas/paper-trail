# Paper summary (hand-compiled — PDF ingestion was blocked)

**Title:** Beware of Data Leakage from Protein LLM Pretraining

**Authors:** Leon Hermann, Tobias Fiedler, Hoang An Nguyen, Melania Nowicka, Jakub M. Bartoszewicz

**Published:** *Proceedings of Machine Learning in Computational Biology* (PMLR vol. 261), 2024. Also on bioRxiv: [10.1101/2024.07.23.604678](https://www.biorxiv.org/content/10.1101/2024.07.23.604678v1).

**Headline claim:** Evolutionary Scale Modeling (ESM / ESM2) protein language models were pretrained on UniRef50. Downstream benchmarks — thermostability (FLIP), inverse folding (CATH), etc. — commonly construct train/test splits **without filtering out sequences that were in the ESM pretraining corpus**. The authors measure that this leakage inflates reported performance by ~11% on average, and propose the **EPA (ESM Pretraining-Aware)** split protocol that enforces UniRef50-cluster separation between ESM pretraining and evaluation.

**Reproducibility-critical implication:** any protein-LM evaluation repo that builds on ESM and does NOT perform EPA-style filtering is susceptible to inflated headline numbers that will not replicate when the benchmark is constructed more strictly.

## Why this paper was picked for our robustness probe

- Domain shift: nothing like our prior tests (tabular ML leakage, dialog eval, diffusion LMs).
- The paper's central finding is **data leakage via sequence similarity** — the protein-LM analog of our canonical imputation/duplicate-row leakage failure classes. Different object (protein sequences vs. tabular rows), same structural failure.
- The ByProt repo is a widely-used protein-design toolkit that integrates ESM2 for inverse folding (LM-Design) and ProteinMPNN. A reproducibility agent should be able to tell whether ByProt applies EPA-style filtering or not.

## Why the paper markdown was not auto-ingested

`paper_meta.json` in this directory records `ingest_status: unavailable`. bioRxiv is behind Cloudflare bot protection; the `.full.pdf` URL returns 403 to our HTTP client, and curl with a spoofed User-Agent is served a Cloudflare JavaScript challenge page instead of the real PDF. The PMLR proceedings PDF landing pattern didn't resolve either.

This is a **known limitation** of the ingester for bioRxiv / Cloudflare-protected sources. A user-supplied local PDF works:

```python
await ingest("/tmp/paper.pdf")        # works — docling on a real file
await ingest("https://www.biorxiv.org/.../full.pdf")  # blocked by Cloudflare
```

For this probe, the Quick Check mode does not actually require paper context in the prompt — it's a repo audit. So we proceeded without the paper body and logged the limitation for the user's review.
