## Verdict:
verdict: unclear
confidence: 0.55
evidence:
  - file: src/prepare_data.py
    line: 42
    snippet: "train_df, test_df = split_by_time(df, cutoff=2005)"
  - file: src/split_utils.py
    line: 18
    snippet: "def split_by_time(df, cutoff): ..."
notes: "The repo ships two splitters: a standard train_test_split in prepare_data.py (lines 18-22, unused in this code path) AND a custom split_by_time at line 42. Without knowing which splitter is live under the default entrypoint, the question cannot be cleanly answered. Recommend inspecting `scripts/run_experiment.py` to see which path is invoked."
