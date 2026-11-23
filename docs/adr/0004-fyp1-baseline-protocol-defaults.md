# ADR-0004: FYP-I baseline protocol defaults

- **Status:** Team defaults, agreed on 18 Nov 2026 in the R2 planning session and used unchanged by
  the FYP-I baseline run. To be confirmed or changed at **gate G2 (Feb 2027**, plan §8: "protocol
  frozen, O1–O5 confirmed"). Supervisor sign-off: [`docs/audit/SUPERVISOR_SIGNOFF.md`](../audit/SUPERVISOR_SIGNOFF.md).
- **Resolves:** FYP-I audit finding B3 (protocol defaults without a decision record) and the
  documentation half of M2, M4 and M5.
- **Precedence:** SDS > SRS > Proposal. Every value below fills a gap that SDS Appendix A leaves
  open (it says "mild colour jitter", "search range 1e-5 to 1e-3", "ImageNet-pretrained" without
  numbers or versions). Nothing here overrides the SDS.
- **Changes to code:** comments only (`factory.py:10-11`, `protocol.yaml:5-7`, `protocol.yaml:64`).
  Training behaviour, `protocol_version` and `PREPROCESS_VERSION` are unchanged.

## Decision

| # | Setting | Value | Where | Basis |
| --- | --- | --- | --- | --- |
| 1 | Colour jitter (train only) | brightness 0.1, contrast 0.1, saturation 0.1, hue 0.02 | `ml_research/configs/protocol.yaml:31-35` | SDS "mild colour jitter"; small values keep H&E hues plausible |
| 2 | Warm-up | 2 epochs, then cosine decay | `protocol.yaml:48-50` | Plan R2 table "cosine schedule with warm-up (O1)"; number is a default |
| 3 | Learning rate before the sweep | 1e-4 (placeholder only) | `protocol.yaml:45` | Replaced in `train-all` by the sweep result (`runs/sweep/chosen_lr.json`) |
| 4 | LR grid | 1e-5, 3e-5, 1e-4, 3e-4, 1e-3 | `protocol.yaml:46` | SDS range 1e-5..1e-3; plan grid |
| 5 | Sweep trial length | 5 epochs per (model, LR) | `ml_research/src/oscc_ml/train/sweep.py:27` (`DEFAULT_SWEEP_EPOCHS`) | Compute budget on one GPU: 4 models × 5 LRs × 5 epochs |
| 6 | Sweep selection rule | highest mean over the 4 models of each run's best validation image-level AUC; ties → lower LR | `sweep.py:29-32` (`SELECTION_RULE`) | SDS "the chosen schedule is applied to every model": one shared LR (plan O1 primary analysis) |
| 7 | CNN weights | torchvision `IMAGENET1K_V1` for ResNet50, EfficientNet-B0, DenseNet121 | `ml_research/src/oscc_ml/models/factory.py:49,56,64` | The classic, widely reported ImageNet-1k recipe; V2 weights use a different training recipe |
| 8 | ViT weights | HuggingFace `google/vit-base-patch16-224` (ImageNet-21k pretrain, ImageNet-1k fine-tune), eager attention | `factory.py:36-42` | Plan §4.1; the only ViT-B/16 named in CLAUDE.md §4 |
| 9 | Input normalisation, all four models | ImageNet mean/std | `protocol.yaml:16-17` | SDS Appendix A (identical preprocessing for every model) |
| 10 | Class imbalance | `BCEWithLogitsLoss(pos_weight = n_neg/n_pos of train)` + τ on validation (target recall 0.95, max F1) | `protocol.yaml:59`, `:64` | SDS loss; plan O2. Minority-class augmentation is **not** used (see M5 below) |
| 11 | Test-split access | Only `oscc-ml evaluate` reads test, from `checkpoints/best.pt` | `eval/evaluate.py::predict_test` | Audit M2, fixed in Phase 2A PR (B); before/after fingerprint identical |
| 12 | Batch size, epochs, patience, seed, AMP | 32, max 50, patience 7 on validation image AUC, seed 42, AMP on CUDA | `protocol.yaml:52-58` | SDS Appendix A; unchanged even on a 24 GB GPU (identical protocol) |

## Known confounds and deviations recorded here

- **M4, ViT normalisation.** The `google/vit-base-patch16-224` checkpoint was trained with
  mean = std = 0.5 (`preprocessor_config.json` at HF commit `3f49326e`, model card line 72,
  retrieved 22 Nov 2026). The protocol feeds it ImageNet mean/std, as the SDS requires. Fine-tuning
  adapts the first layer, but the starting point differs from the checkpoint's own recipe.
- **M4, ViT pretraining.** The ViT was pretrained on ImageNet-21k (14 M images) before ImageNet-1k
  fine-tuning (model card line 20); the CNNs saw ImageNet-1k only. Part of any ViT advantage may be
  the larger pretraining set, not the architecture. Both points are stated in
  [`docs/model_cards/vit_b_16.md`](../model_cards/vit_b_16.md) and in every results chapter. A
  possible FYP-II ablation: the ViT with its own 0.5/0.5 statistics.
- **M5, minority augmentation.** SDS risk table (`SDS.md:438`) lists "augmentation of the minority
  class, class-weighted loss, threshold calibration on validation data". The baseline uses the last
  two only. Minority-specific augmentation would change the training distribution of one class and
  would have to be applied identically to all four models; it becomes an **R3 ablation** (FYP-II).
- **M2.** Fixed rather than documented: training never opens the test split.

## Consequences

- The FYP-I numbers are produced under exactly these settings; `run_info.json` and
  `config.resolved.yaml` in every run folder record them.
- Changing any of rows 1–8 after the university run requires a new run of every model.
- Gate G2 (Feb 2027) either confirms these values or replaces them with an amended ADR.
