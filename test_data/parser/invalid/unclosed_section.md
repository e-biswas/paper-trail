## Claim:
claim: "Paper claims RF beats LR on Muchlinski civil-war panel."

## Hypothesis 1: Imputation-before-split leakage
confidence: 0.6
reason: "Common pattern in older R-to-Python ports; worth checking first."

## Hypothesis 2: Target column included in imputation matrix
confidence: 0.45
reason: "If the target is in the frame at fit time, KNN uses y as a feature. Need to
