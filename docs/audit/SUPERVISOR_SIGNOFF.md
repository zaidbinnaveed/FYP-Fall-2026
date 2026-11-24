# Supervisor sign-off: FYP-I deviations and gate G1

Project AI FYP 1015, OSCC Health Intelligence. Supervisor: Miss Rubab Manzar.
Prepared 23 Nov 2026 from the FYP-I audit ([`FYP1_COMPLIANCE_AUDIT.md`](FYP1_COMPLIANCE_AUDIT.md)).
Each line is a place where what we built differs from, or fills a gap in, the approved SRS/SDS.
Tick **Accept** or **Change**, and add a note if needed.

## Gate G1: dataset audit reviewed (plan R1 acceptance)

| | Item | Evidence | Accept | Change |
| --- | --- | --- | :---: | :---: |
| G1 | The dataset audit and the dry-run counts were shown to the supervisor: 5,192 files → 1,224 originals → **1,179 kept**, 35 label-conflict images excluded, split **829 / 174 / 176**, leakage test passed, independent verifier 46/46 | [`FYP1_COMPLIANCE_AUDIT.md`](FYP1_COMPLIANCE_AUDIT.md) §4, [`../datasheet.md`](../datasheet.md), ADR-0005 | ☐ | ☐ |

Date shown: ____________  Outcome / notes: ______________________________________________

## Deviations

| # | Deviation | One-line reason | Evidence | Accept | Change |
| --- | --- | --- | --- | :---: | :---: |
| 1 | **Split grouped by image similarity, not by patient** (SRS FR-7.2, NFR-PER-09; SDS App. A) | No release (GitHub, Mendeley v1/v2, Kaggle) has patient or slide IDs; pHash groups (≤ 10) are the closest leak-safe proxy. Test metrics may be optimistic | Errata E7; [`../datasheet.md`](../datasheet.md) L1; audit M1 | ☐ | ☐ |
| 2 | **ViT normalisation**: ImageNet mean/std for all models, although the ViT checkpoint uses 0.5/0.5 (HF commit `3f49326e`) | The SDS requires identical preprocessing for every model; the mismatch is stated as a confound | Errata E9; ADR-0004; [`../model_cards/vit_b_16.md`](../model_cards/vit_b_16.md) | ☐ | ☐ |
| 3 | **ViT pretrained on ImageNet-21k** (+1k fine-tune); CNNs on ImageNet-1k only | The standard ViT-B/16 checkpoint; stated as a threat to validity of the CNN-vs-ViT comparison | Errata E9; ADR-0004; model card notes | ☐ | ☐ |
| 4 | **No minority-class augmentation** (SDS risk table); class-weighted loss + recall-oriented τ instead | Keeps the protocol identical for all models; minority augmentation becomes an R3 ablation in FYP-II | Errata E10; ADR-0004; audit M5 | ☐ | ☐ |
| 5 | **ADR-0002**: tissue = saturation > min(Otsu, 40) | Plain Otsu finds no glass/tissue split on full-frame tissue and dropped most tiles | [`../adr/0002-o5-tissue-threshold-cap.md`](../adr/0002-o5-tissue-threshold-cap.md); errata E12 | ☐ | ☐ |
| 6 | **ADR-0003**: duplicate clusters carrying both labels are excluded (35 images) | The true label of an image published under both classes cannot be known | [`../adr/0003-label-conflict-exclusion.md`](../adr/0003-label-conflict-exclusion.md); errata E13 | ☐ | ☐ |
| 7 | **ADR-0004**: protocol defaults the SDS leaves open (jitter 0.1/0.1/0.1/0.02, 2 warm-up epochs, 5-epoch sweep, shared-LR rule, torchvision V1 weights) | Needed numbers for the baseline run; confirmed or changed at gate G2 (Feb 2027) | [`../adr/0004-fyp1-baseline-protocol-defaults.md`](../adr/0004-fyp1-baseline-protocol-defaults.md); errata E15 | ☐ | ☐ |
| 8 | **ADR-0005**: pHash duplicate threshold 4, group threshold 10, reviewed same-field list (2 pairs) | Threshold 6 merged different fields; 4 + a visual review removes only true duplicates | [`../adr/0005-phash-thresholds-and-reviewed-duplicates.md`](../adr/0005-phash-thresholds-and-reviewed-duplicates.md), contact sheets in [`figures/`](figures/); errata E14 | ☐ | ☐ |
| 9 | **PyTorch only** (proposal/SRS: "TensorFlow/Keras and PyTorch") | One framework keeps one data loader, augmentation, optimizer and AMP setup for an identical protocol | Plan §4.1; CLAUDE.md §4; audit §3 item 1 | ☐ | ☐ |
| 10 | **Multi-OSCC external set deferred to FYP-II** | 34.6 GB single archive; not needed for the FYP-I baselines | Errata E11; datasheet "Multi-OSCC"; audit M6 | ☐ | ☐ |
| 11 | **FYP-I scope change**: tabular dataset + classical classifiers added (proposed FR-7.11), working mock UI moved into FYP-I, LLM/chatbot on hold | Supervisor's FYP-I requirements (recorded verbatim) | [`../SCOPE_CHANGE_FYP1.md`](../SCOPE_CHANGE_FYP1.md); errata E16–E18 | ☐ | ☐ |

Supervisor: ______________________  Signature: ______________  Date: ____________

Team lead: _______________________  Signature: ______________  Date: ____________
