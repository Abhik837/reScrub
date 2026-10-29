# Trained models

reScrub's operating-room models ship in this folder, and both ways of running reScrub use them
automatically: the local Docker stack and the self-hosted servers.

| File | What it does | Trained on | Validation (009) | Test (038) |
| --- | --- | --- | --- | --- |
| `rescrub-or-seg.pt` | Sterile / non-sterile / patient surfaces, and scrubbed vs. unscrubbed people (14 classes) | 5 training surgeries: 005, 010, 006, 008, 012 | mask mAP50-95 0.476 | 0.534 |
| `rescrub-or-pose.pt` | Keypoints of gowned, masked OR staff | All 9 training surgeries | keypoint mAP50-95 0.605 | 0.817 |
| `rescrub-reid-cls.pt` | Tells people in identical gowns apart, so "Person N" labels stay stable | 2 training surgeries: 005, 010 | top-1 accuracy 0.68 | – |

**How they were made.** All three are YOLO26 models trained with `backend/training` on the
[MM-OR](https://github.com/egeozsoy/MM-OR) dataset:
- **Settings:** every 4th labeled frame (6th in the last round), 768 px, and AdamW fine-tuning between rounds.
- **Training rounds:** four, each adding surgeries.
- **Install rule:** after every round, each model was replaced only if it scored higher on validation
  surgery 009. That's why the three files come from different rounds.
- **Held out:** test surgery 038 was never used for training or for choosing models; it is only reported.
- **Pose labels:** MM-OR has no keypoint labels, so the pose scores are measured against labels from a larger
  pose model, checked against MM-OR's person masks.

**End to end.** [`RESULTS-production.txt`](RESULTS-production.txt) is the whole pipeline, with these three
models, run on test surgery 038 (48 minutes, one angled camera) and scored against MM-OR's 6 labeled
sterility breaches:

| Findings | Breaches found | Precision | Mean onset error |
| --- | --- | --- | --- |
| 169 | 3 of 6 | 0.018 | 10 s |

reScrub is built to over-flag and let an instructor dismiss false alarms, so precision is low by design.
Most of this surgery's labeled breaches are anesthesia staff handling the drape at the head of the
table, which is hard to see from one camera.

**Using other models.** Set these in `.env` (local stack) or `backend/.env` (servers) to use the public
models instead: `SURFACE_CONFIG=config/surfaces.yaml`, `POSE_MODEL=yolo26m-pose.pt`, `EMBED_MODEL=yolo26n-cls.pt`.
New models you train ([docs/TRAINING.md](../../../docs/TRAINING.md)) are installed here and used after a
restart. How these three were trained and why they weren't trained further is in the same guide.

## MM-OR terms of use

These weights were trained on [MM-OR](https://github.com/egeozsoy/MM-OR) (TU Munich), and MM-OR's terms
of use apply to them. **By using these weights you agree to follow MM-OR's terms:**
- read them via the access form linked in the [MM-OR README](https://github.com/egeozsoy/MM-OR#mm-or-dataset);
- use the weights only as those terms allow (for example, research and education);
- cite MM-OR:

> Özsoy et al., *MM-OR: A Large Multimodal Operating Room Dataset for Semantic Understanding of
> High-Intensity Surgical Environments*, CVPR 2025.

If you can't accept those terms, delete the `.pt` files in this folder. reScrub then runs on the public
base models only.

reScrub suggests moments for a person to review. It is a training tool, not a medical device, and its
models don't establish whether contamination occurred.
