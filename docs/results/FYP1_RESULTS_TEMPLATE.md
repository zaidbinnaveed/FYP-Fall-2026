# FYP-I results (generated)

_Filled ONLY by `oscc-ml report`; never edit the numbers by hand. Rows without a run read "not yet run"._

## 1. Dataset

_Source: `extraction.json` (dataset `see manifest`)._

| Split | Images | non-OSCC | OSCC | Patches |
| --- | ---: | ---: | ---: | ---: |
| train | 829 | 191 | 638 | n/a |
| val | 174 | 39 | 135 | n/a |
| test | 176 | 41 | 135 | n/a |

## 2. Baseline performance (test, image level; 95% grouped-bootstrap CIs)

| Model | Family | Accuracy | Precision | Recall | F1 | AUC-ROC |
| --- | --- | --- | --- | --- | --- | --- |
| ResNet50 | CNN | not yet run | | | | |
| EfficientNet-B0 | CNN | not yet run | | | | |
| DenseNet121 | CNN | not yet run | | | | |
| ViT-B/16 | ViT | not yet run | | | | |
| Logistic regression (tabular) | Tabular | 0.847 [0.793, 0.897] | 0.880 [0.827, 0.932] | 0.926 [0.878, 0.970] | 0.903 [0.864, 0.936] | 0.908 [0.856, 0.950] |
| Random forest (tabular) | Tabular | 0.932 [0.891, 0.966] | 0.942 [0.901, 0.978] | 0.970 [0.939, 0.993] | 0.956 [0.929, 0.979] | 0.956 [0.905, 0.989] |
| Gradient boosting (tabular) | Tabular | 0.920 [0.880, 0.955] | 0.942 [0.902, 0.977] | 0.956 [0.920, 0.986] | 0.949 [0.920, 0.972] | 0.959 [0.929, 0.984] |

## 3. Cost

See `cost.md` (same folder).

## 4. Figures

- `figures/accuracy_vs_cost.png`
- `figures/confusion_tab_gradient_boosting.png`
- `figures/confusion_tab_logreg.png`
- `figures/confusion_tab_random_forest.png`
- `figures/pr_test.png`
- `figures/roc_test.png`

## 5. Model selection

See `MODEL_SELECTION.md`. Summary line:

**Provisional (image models not yet run).** **Selected under the rule: Gradient boosting (tabular)** (test AUC 0.959 [0.929, 0.984], recall 0.956 [0.920, 0.986]).

## 6. Status

- Models with results: 3 of 7; not yet run: ResNet50, EfficientNet-B0, DenseNet121, ViT-B/16.
- One seed (42) in FYP-I; FYP-II repeats with seeds 42, 43, 44.
