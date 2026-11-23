# Cost

| Model | Family | Learnt parameters | GFLOPs / patch | CPU latency ms (unit) | Training time (s) |
| --- | --- | ---: | ---: | --- | ---: |
| ResNet50 | CNN | not yet run | | | |
| EfficientNet-B0 | CNN | not yet run | | | |
| DenseNet121 | CNN | not yet run | | | |
| ViT-B/16 | ViT | not yet run | | | |
| Logistic regression (tabular) | Tabular | 68 | n/a | 2.43 (feature row) | 2.2 |
| Random forest (tabular) | Tabular | 70490 | n/a | 128.90 (feature row) | 147.7 |
| Gradient boosting (tabular) | Tabular | 12724 | n/a | 11.45 (feature row) | 665.6 |

Tabular parameters = coefficients (logistic regression) or tree nodes (forests, boosting); image models = network weights. GFLOPs do not apply to the tabular models.
