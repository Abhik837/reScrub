# Training and fine-tuning the models

reScrub ships three trained models ([backend/models/trained](../backend/models/trained/README.md)).
This guide covers where their data comes from, how they were trained, how to retrain or fine-tune them
on any NVIDIA machine with Docker, and why they weren't trained further. Script-level details (every
option, label mapping, sterile-field definitions) are in
[backend/training/README.md](../backend/training/README.md).

## The dataset: MM-OR

[MM-OR](https://github.com/egeozsoy/MM-OR) (Özsoy et al., CVPR 2025, TU Munich) records simulated
robot-assisted knee replacements (TKA/PKA) in a real operating room, with surgeons, nurses,
anesthesia staff and circulators. reScrub uses:
- **video** from the angled ceiling cameras (MM-OR is sampled at 1 frame per second);
- **per-pixel masks** for staff roles, the patient, drapes, tables, instruments and equipment, which
  train the surface/role model and check the pose labels;
- **labeled sterility breaches** (`take_timestamp_to_sterility_breach`), which score the end-to-end analysis.

**Access:** request it through the form in the
[MM-OR README](https://github.com/egeozsoy/MM-OR#mm-or-dataset) and accept its terms; downloads come
from `www.campar.in.tum.de`. The terms cover the data and models trained on it.

**Splits** (from the MM-OR paper; each split is different surgeries):

| Split | Surgeries | Used for |
| --- | --- | --- |
| train | 001, 003, 005, 006, 008, 010, 012, 035, 037 (~273 GB zipped) | training |
| val | 002, 007, 009 (~63 GB) | choosing checkpoints, deciding whether a new model replaces the installed one, tuning breach rules |
| test | 004, 011, 036, 038 (~95 GB) | final scores only |

## How the shipped models were trained

Four rounds on one rented Vultr GPU server (`vcg-a16-12c-120g-32vram`: NVIDIA A16 with 16 GB used,
12 vCPUs, 120 GB RAM, $0.94/hour), each adding
training surgeries and fine-tuning from the previous round. Validation surgery 009 and test surgery
038 were held out throughout. After every round, each model was replaced only if it scored higher on
validation (`INSTALL=if-better`), so the shipped files come from different rounds:

| Round | Training surgeries | Settings | Kept from this round |
| --- | --- | --- | --- |
| 1 | 005, 010 | every 4th labeled frame, 768 px, from the public YOLO26 weights | **identity** (top-1 0.68) |
| 2 | + 006, 008, 012 | fine-tuned (AdamW, lr 0.0005, half the epochs) | **surfaces and roles** (mask mAP50-95 0.476 val / 0.534 test) |
| 3 | + 037, 003 | fine-tuned | — (round 4 beat it) |
| 4 | + 035, 001: all 9 | fine-tuned, every 6th frame | **pose** (0.605 val / 0.817 test) |

End to end on test surgery 038 (48 minutes): 169 findings, 3 of 6 labeled breaches found, 10 s mean
onset error ([RESULTS-production.txt](../backend/models/trained/RESULTS-production.txt)).

## Why the training stopped there

- **Compute budget.** The four rounds ran for 54 hours on that one A16, including downloads and
  evaluation: about $54 with block storage (150–400 GB, $2.40). The whole project, including the original
  hosted site, cost about $90 on Vultr. 16 GB of GPU memory limited training to 768 px instead of 1024 px.
- **Data size.** The full MM-OR download is ~432 GB and needs a ~1 TB disk. The pose labels are made by
  running a large teacher model on every training frame, which takes hours per surgery.
- **Few suitable datasets.** reScrub needs room-level video of whole surgical teams with per-pixel
  labels and, ideally, labeled sterility breaches. Most public surgical video is endoscopic (inside
  the body), and real operating-room footage is rarely released for privacy reasons. MM-OR is the only
  public dataset we found with breach labels; its predecessor
  [4D-OR](https://github.com/egeozsoy/4D-OR) has the same mask format but no breach labels, and the
  dataset builders can add it (`--or4d`).
- **Small test set.** Test surgery 038 has only 6 labeled breaches, so one breach moves recall by
  17 points. Validation surgery 009 has none, so the breach rules couldn't be tuned on it.
- **One kind of surgery.** MM-OR is knee replacement with a MAKO robot in one room. Other rooms,
  drape colors and procedures need fine-tuning on their own footage (below).

## Retrain or fine-tune

### What you need
- **Linux with an NVIDIA GPU** (16 GB or more of GPU memory; 24–48 GB allows full 1024 px), Docker
  and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
  Windows works through WSL2 with Docker Desktop's GPU support. A rented cloud GPU works the same way:
  the Ubuntu setup commands are in [DEPLOY.md §7](DEPLOY.md#7-gpu-server-analysis).
- **Disk:** ~100 GB for `quick`, ~150 GB for `production`, ~1 TB for `full`.
- **MM-OR access** (above).

Training needs no database or storage. It runs in the CUDA worker image from `backend/docker-compose.yml`,
and new models are installed straight into `backend/models/trained/`.

### Set up (once)
```bash
git clone https://github.com/Abhik837/reScrub.git && cd reScrub/backend
cp .env.example .env                      # only DATA_HOST_DIR matters for training
sed -i 's|^DATA_HOST_DIR=.*|DATA_HOST_DIR=/path/to/big/disk|' .env
mkdir -p /path/to/big/disk && sudo chown -R 1000:1000 /path/to/big/disk models/trained
docker compose --profile worker build     # ~15 min; ends with "onnxruntime CUDA 12 / torch CUDA 12.6"
docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu22.04 nvidia-smi -L   # lists your GPU(s)
```
Inside the container that disk is `/data`. Run the long commands below in `tmux` so they survive a
closed terminal or dropped SSH session (`tmux new -s train`; detach with `Ctrl+b` then `d`; come back with
`tmux attach -t train`).

### Choose a level
Each command downloads what it needs (resumable), builds the datasets, trains, installs models that
beat the current ones on validation, and scores the full pipeline on held-out surgeries. Add
`-e FINETUNE=1` to start from the shipped models (lower learning rate, half the epochs) instead of the
public weights.

| Level | Data | Extra settings | Time on a 48 GB L40S (estimate) |
| --- | --- | --- | --- |
| `quick`: surface model only, scored on validation | ~8 GB | `-e PROFILE=tiny -e EVAL_SPLIT=val -e MODELS=seg -e EVERY=6 -e IMGSZ=640 -e SEG_EPOCHS=30` | 1–2 h |
| `production`: all three models, the shipped models' setup | ~41 GB | `-e PROFILE=small -e EVERY=4 -e IMGSZ=768` | several hours (10–15 h on a 16 GB A16) |
| `full`: all 16 surgeries, breach rules tuned | ~432 GB | `-e PROFILE=full -e TUNE=1` | a few days |

```bash
cd ~/reScrub/backend      # or wherever you cloned it
docker compose --profile worker run --rm -e DATA=/data -e DEVICE=0 \
  -e PROFILE=small -e EVERY=4 -e IMGSZ=768 -e FINETUNE=1 \
  worker bash training/run_all.sh 2>&1 | tee -a train.log
```
- **Out of GPU memory:** use a smaller `-e IMGSZ` (768, then 640).
- **More than one GPU:** keep `DEVICE=0`; the pose labeling and evaluation steps use a single GPU.
- **Add specific surgeries:** download them first, and they are included automatically:
  `docker compose --profile worker run --rm worker python -m training.fetch_mmor --out /data --takes 006_PKA,008_PKA`.
  `--dry-run` prints sizes without downloading.

### If it stops
- **During download or dataset building:** run the same command again; finished downloads are skipped.
- **During training:** continue that model from its last epoch, then let it install as usual:
  ```bash
  ls /path/to/big/disk/runs/                    # e.g. seg-2 is the run that stopped
  docker compose --profile worker run --rm worker python -m training.train seg \
    --data /data/rescrub_seg/dataset.yaml --device 0 --project /data/runs --resume /data/runs/seg-2
  ```
  Then run the level's command again with `-e MODELS=""` (train nothing; just re-score) or with the
  models that remain (e.g. `-e MODELS="pose reid"`).

### Check the results
```bash
grep -E "^Installed|Not installed|^val |^test " train.log            # which models were replaced
cat /path/to/big/disk/eval_results/test/evaluation.json              # breaches found, precision, timing
tail -n 3 /path/to/big/disk/runs/*/results.csv                       # per-epoch training metrics
```
Each training run keeps its best epoch by validation score. The test numbers are reports only;
choosing models by them would make them optimistic.

### Use the new models
They are already in `backend/models/trained/`. Restart whatever runs reScrub from this clone:
`docker compose -f docker-compose.local.yml restart worker` (from the repository root), or
`docker compose --profile worker up -d` on a GPU server. If you trained on another machine, copy the
`rescrub-*.pt` files into `backend/models/trained/` where reScrub runs. The worker's "Loading models"
log line names the files in use. Replaced models are kept in `backend/models/trained/backup/`.

## Fine-tune on your own recordings
A new room, camera angle or drape color is the best reason to fine-tune:
1. Export 200–500 frames from your camera and label them (for example in CVAT with SAM-assisted masks)
   with the class names in [`backend/training/mmor_classes.yaml`](../backend/training/mmor_classes.yaml)
   (`sterile_drape`, `scrubbed_person`, …). Export as "YOLO 1.1 segmentation".
2. Add them to the surface dataset (or write a `dataset.yaml` listing both) and train from the shipped model:
   `python -m training.train seg --data mixed.yaml --base /models/trained/rescrub-or-seg.pt --epochs 30`
   (inside the worker container, as above).

If something is draped differently in your room, change its `designation` in
`backend/config/surfaces_mmor.yaml` instead; no retraining needed.

## What would improve it most
1. **The full MM-OR training set at 1024 px** on a 24–48 GB GPU (`full` level).
2. **Your own labeled recordings** from the room and camera reScrub will be used with.
3. **More labeled breaches** for tuning and testing the breach rules, which currently decide most of
   what is flagged (`training/tune_breaches.py`, `TUNE=1`).
