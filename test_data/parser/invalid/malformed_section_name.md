## Claim:
claim: "Paper claims RF >> LR."

## Hipothesis 1: Imputation leakage
confidence: 0.7
reason: "Typo in header — parser should either skip or warn."

## HYPOTHESIS 2: Duplicate rows
confidence: 0.5
reason: "Uppercase variant — parser should handle case-insensitively or reject cleanly."

## Check Imputation leakage
hypothesis_id: h1
description: "Missing colon after Check."
method: "Read"

## Finding -
check_id: c1
result: "Section divider is dash, not colon."
