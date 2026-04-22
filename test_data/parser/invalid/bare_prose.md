I looked at the repository and the paper. I think the main issue might be that the imputation is applied before the train/test split. This is a common bug in ML papers. Looking at the code in prepare_data.py, I can see that KNNImputer is called on the full dataframe which is a clear leakage pattern. I would recommend moving the imputation into a sklearn Pipeline so it fits only on training data.

The metric impact of this would likely be several percentage points of ROC-AUC, with the random forest being more affected than logistic regression because of the non-linear patterns KNN imputation introduces.

I am fairly confident in this diagnosis. I would suggest opening a PR with the fix.
