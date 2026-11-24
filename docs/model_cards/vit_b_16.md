# Model card notes: ViT-B/16 (`vit_b_16`)

Status: **notes only.** The full model card (intended use, metrics, limitations) is written after
the university run from the run folder; until then every result field is "not yet run".

## Source

- HuggingFace `google/vit-base-patch16-224`, commit `3f49326eb077187dfe1c2a2bb15fbd74e6ab91e3`
  (`X-Repo-Commit` header, retrieved 2026-11-22T13:49:14Z), loaded with
  `attn_implementation="eager"` so attention rollout works (`ml_research/src/oscc_ml/models/factory.py`).
- Classification head replaced by one logit (binary OSCC vs non-OSCC).

## Two confounds in the CNN-vs-ViT comparison (audit M4, ADR-0004)

1. **Pretraining data.** The checkpoint was pretrained on ImageNet-21k (about 14 million images,
   21,843 classes) and then fine-tuned on ImageNet-1k (model card, line 20). The three CNNs use
   torchvision ImageNet-1k weights only. A ViT advantage may partly come from the larger
   pretraining set.
2. **Input normalisation.** The checkpoint's `preprocessor_config.json` at that commit has
   `image_mean = image_std = [0.5, 0.5, 0.5]` (model card, line 72). Our protocol gives every model
   the ImageNet mean/std (SDS Appendix A requires identical preprocessing). The ViT therefore starts
   fine-tuning from inputs scaled differently from its pretraining.

Both are stated, not hidden (plan §4.1: "a threat to validity to state, not to hide"). Possible
FYP-II ablation: the ViT with its own 0.5/0.5 statistics, all else equal.

## Results

Not yet run. Filled by `oscc-ml report` from `runs/<timestamp>_vit_b_16_42/evaluation.json`.
