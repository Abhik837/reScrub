# Training scripts (reference)

How to run training, what the shipped models are, and why: [docs/TRAINING.md](../../docs/TRAINING.md).
This page documents the scripts, their options, and how MM-OR's labels become reScrub's classes.
All commands run inside the CUDA worker container (`docker compose --profile worker run --rm worker …`
from `backend/`), where the data disk is `/data` and models install to `/models/trained`.

## Scripts

| Script | Does |
| --- | --- |
| `run_all.sh` | Everything below in order, configured by environment variables (next section) |
| `fetch_mmor.py` | Downloads only what reScrub uses (takes, `take_jsons`, `take_tracks`, breach labels), skips point clouds/audio, checks free disk, prunes unused folders after unzipping, resumes. `--profile tiny\|small\|full`, `--takes 006_PKA,…`, `--short-clips`, `--dry-run` |
| `build_seg_dataset.py` | MM-OR (and optionally 4D-OR, `--or4d`) panoptic masks → YOLO segmentation dataset of surfaces and scrubbed/unscrubbed people. `--every N`, `--short-clips` |
| `build_pose_dataset.py` | Pose labels from a `yolo26x-pose` teacher, kept only where they agree with MM-OR's person masks (MM-OR has no keypoint labels). Needs a GPU |
| `build_reid_dataset.py` | Person crops per take and role → identity classification dataset |
| `export_contacts.py` | MM-OR scene-graph relations → ground-truth contact events (for evaluating and extending the rules) |
| `train.py` | Trains `seg`, `pose` or `reid`; installs `best.pt` to `models/trained/` if it beats the installed model on validation. `--from-installed` (fine-tune), `--resume RUN_DIR`, `--install if-better\|always\|never`, `--epochs`, `--imgsz`, `--batch`, `--lr0`, `--freeze`, `--patience` |
| `make_eval_videos.py` | Held-out surgeries → single-camera MP4s on MM-OR's clock, plus a `.frames.json` mapping labeled frames to seconds |
| `evaluate_breaches.py` | Scores findings against MM-OR's labeled breaches: precision, recall, mean onset error, timestamp problems |
| `tune_breaches.py` | Re-scores saved contact rows with many rule settings, picks the best by F2 on validation, reports it on test, installs `breach_params.json` |
| `backup_models.py` | Copies `models/trained/` to and from an S3 bucket (`push`/`pull`/`list`), for self-hosted servers |
| `mmor.py`, `mmor_classes.yaml` | MM-OR folder layout and splits; the label mapping below (single source of truth) |

## `run_all.sh` settings

| Variable | Default | Effect |
| --- | --- | --- |
| `DATA` | `/data` | Data folder inside the container |
| `PROFILE` | `small` | `tiny` (1/1/1 surgeries, ~28 GB), `small` (2/1/1, ~41 GB), `full` (9/3/4, ~432 GB) |
| `MODELS` | `seg pose reid` | Which models to train; `""` trains nothing (only scores/tunes) |
| `FINETUNE` | `0` | `1`: start from the installed models (AdamW, lr 0.0005, half the epochs) |
| `INSTALL` | `if-better` | Replace installed models only if better on validation; or `always`, `never` |
| `EVERY` | `2` (ReID `3`) | Keep every Nth labeled frame (frames 1 s apart are near-duplicates) |
| `IMGSZ` | `1024` | Training image size; 768 fits a 16 GB GPU |
| `SEG_EPOCHS`, `POSE_EPOCHS`, `REID_EPOCHS` | `80`, `40`, `30` | Epochs (early stopping after 15 without improvement) |
| `EVAL` | `1` | `0` skips the end-to-end evaluation |
| `EVAL_SPLIT` / `EVAL_SPLITS` | `test` | Which held-out split(s) to score; `val` skips the test download |
| `TUNE` | `0` | `1`: score val and test, tune the breach rules on val, report on test |
| `REUSE_EVAL` | `0` | `1`: reuse existing pipeline outputs when re-scoring |
| `DEVICE` | `0` | GPU index (or `cpu`) |
| `CAMERAS` | `auto` | Camera for evaluation videos (simstation 0, else Azure 4) |

Outputs (under `DATA`): `MM-OR_data/`, `rescrub_seg/`, `rescrub_pose/`, `rescrub_reid/` (datasets, each
with a `stats.json` of counts per class), `runs/<model>[-N]/` (training curves, `best.pt`, `last.pt`),
`eval_videos/<split>/`, `eval_results/<split>/evaluation.json` and labeled videos.

## Evaluation and rule tuning

Each held-out surgery becomes one MP4 from the angled camera at MM-OR's 1 frame per second; the
pipeline and the breach rules run on it, and `evaluate_breaches` compares the findings with the labeled
breaches on the same clock (`--tolerance`, default 3 s). It reports precision, recall, mean onset error,
and timestamp problems (should be 0).

Most of the gap between contacts and real breaches is in the rules, not the models. The rules run on
saved contact rows in seconds, so `tune_breaches` tries every combination of stricter contact distance
and depth, minimum frames, repeat merging and which rules are on, ranks them by F2 (a missed breach
counts more than an extra flag), and installs the winner as `models/trained/breach_params.json` only if
it beats the defaults on validation. It needs validation surgeries with labeled breaches (`PROFILE=full`
has them; `small`'s 009 has none).

## How MM-OR labels map to reScrub

`mmor_classes.yaml` is the single source of truth. In short:

| reScrub class | MM-OR labels | Designation |
| --- | --- | --- |
| `sterile_drape` | drape | sterile |
| `instrument_table` | instrument_table (draped back table) | sterile |
| `instrument` | drill, saw, hammer, cementer | sterile |
| `tracker_array` | tracker | sterile |
| `robot_arm` | mako_robot | neutral (never a breach on its own; see below) |
| `patient` | patient (exposed, outside the drapes) | patient |
| `operating_table`, `anesthesia_equipment`, `robot_station`, `monitor`, `c_arm`, `secondary_table` | ot, ae, mps_station, monitor, c_arm, secondary_table | nonsterile |
| `scrubbed_person` | head_surgeon, assistant_surgeon, nurse (scrub nurse) | sterile |
| `unscrubbed_person` | circulator, anest, mps, student, unrelated_person | nonsterile |

Merging roles into scrubbed/unscrubbed (instead of learning "head surgeon") lets the model
generalize to mock surgeries where students play the roles. In the pipeline, each tracked
person's designation is a confidence-weighted vote over the role masks that fall on them. It
is stored in `people.designation` and drawn as "(scrubbed)" or "(unscrubbed)".

## What is sterile in an OR

This is a summary of standard surgical asepsis (AORN Recommended Practices for Sterile
Technique and the teaching materials based on them). The class designations above and
the breach rules are based on it.

**Sterile**
- **Scrubbed people's gown front**, from **chest to the level of the sterile field** (table
  height). **Sleeves** count from **2 inches above the elbow to the cuff**, all the way
  around. **Sterile gloves** count too.
- **Draped tables:** only the **horizontal tabletop**. Anything hanging over the edge or
  below table level is not sterile.
- **Sterile drapes** over the patient and equipment, but only on top. The **prepped incision
  site** is sterile too.
- **Sterile instruments and supplies** that stay on the sterile field.

**Not sterile**
- **Gown back, neckline, shoulders, armpits and sleeve cuffs** (once the hands are past
  them). These rub against things and can't be watched, so they are never a barrier. This is
  why reScrub assumes people don't turn their back to the camera.
- **Anything below waist or table level.** Hands and forearms should stay between **waist and
  mid-chest**.
- The **1-inch (2.5 cm) edge** of a drape or wrapper.
- **Unscrubbed staff**: circulator, anesthesia, product specialists, observers. They must stay
  at least **12 inches (30 cm)** from the sterile field, face it when passing, and never reach
  over it.
- **Undraped surfaces**: operating table sides, anesthesia machine, carts, monitors, C-arm,
  floor, walls.
- **Anything that went out of view**, got wet through a drape (strike-through), or whose
  sterility is in doubt ("if in doubt, it is contaminated").

**Typical breaks a reviewer looks for**, and how reScrub can see them:

| Break | Detectable from reScrub data |
| --- | --- |
| Scrubbed hand or glove touches a nonsterile surface, then something sterile | `proximity_events` (nonsterile, `candidate_contact`) followed by sterile contact for the same person and hand |
| Unscrubbed person touches the sterile field, instrument table or instruments | `people.designation = 'nonsterile'` + `proximity_events` on a sterile surface; MM-OR `breach_candidate` rows are ground truth |
| Hands drop below table or waist level | wrist/fingertip `y` below the drape/table top edge or the person's hip keypoints (`keypoints`) |
| Arms folded under the armpits / hands above the chest | wrist near shoulder keypoints |
| Unscrubbed person within 12 in of the field | person box or keypoints within ~30 cm (px scale from table size) of a sterile surface |
| Touching the drape edge | contact within a few px of a sterile mask boundary (`pixel_dist` small, `inside_mask` false) |
| Turning the back to the field | not reliably visible from one camera (assumed not to happen) |

Sources (accessed 2026-10): AORN Recommended Practices for Sterile Technique / Sterile Field
([ANSI preview](https://webstore.ansi.org/preview-pages/AORN/preview_II-03_SterileField_2012.pdf));
[Children's Wisconsin attire and aseptic technique policy](https://childrenswi.org/-/media/chwlibrary/files/secure/protected-pages/staff/attire-policy-and-aseptic-techniques.pdf);
[CNOR study guide: principles of surgical asepsis](https://open-exam-prep.com/study-guides/cnor/ch6/principles-surgical-asepsis);
[NCCT TS-C guide: sterile field boundaries](https://open-exam-prep.com/study-guides/ncct-tsc/introduction-asepsis/aseptic-principles);
[Infection Control Today: maintaining asepsis within a sterile field](https://infectioncontroltoday.com/view/maintaining-asepsis-within-sterile-field-surgery).
The sources disagree slightly on the exact gown and sleeve boundaries. Follow your institution's
current AORN guideline where it differs.

### How this matches MM-OR's own breach labels

The labeled breaches in all 38 MM-OR takes (`take_timestamp_to_sterility_breach`) follow these
rules:

| MM-OR breach (count) | Rule |
| --- | --- |
| nurse/assistant surgeon touching or manipulating the operating table (276) or a monitor (2) | scrubbed person → nonsterile |
| MPS/circulator/anaesthetist touching, holding or preparing the drape (114), instrument table (68), saw (38) | unscrubbed person → sterile |
| anaesthetist/MPS touching the patient (13) | unscrubbed person → patient |

Robot contact is never labeled a breach, by either group, so the robot is `neutral`. Skin
preparation by the circulator before draping is flagged by the patient rule but is not a breach
in MM-OR; set `Params(unscrubbed_patient_is_breach=False)` in `rescrub/analysis/breaches.py` to
exclude unscrubbed contact with the patient.

## Dataset notes

- MM-OR is **knee arthroplasty with a MAKO robot**. Other procedures, room layouts and drape
  colors may need fine-tuning on your own footage ([docs/TRAINING.md](../../docs/TRAINING.md#fine-tune-on-your-own-recordings)).
- MM-OR masks are **semantic per role** (one mask per role per frame). If two people share a
  role and stand apart, they become separate instances; if they overlap, one merged instance.
- The pose model is trained on **pseudo-labels**. It adapts detection to the OR (fewer false
  people, better with occlusion), but its keypoints can't beat the teacher's.
- ReID identities are **per take**. Validation measures recognizing the same people later in
  the same surgery, which is exactly what tracking needs.
