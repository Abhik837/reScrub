#!/usr/bin/env bash
# MM-OR training on an NVIDIA GPU: download -> datasets -> train -> end-to-end evaluation.
# Runs inside the CUDA worker image (docs/TRAINING.md):
#
#   docker compose --profile worker run --rm -e DATA=/data -e PROFILE=small worker bash training/run_all.sh
#
# Splits (MM-OR paper): train takes train the models, val takes pick checkpoints,
# test takes are only touched in step 4, so the final numbers are on unseen surgeries.
#
# Faster runs:
#   PROFILE=tiny          one surgery per split
#   EVERY=6               keep every 6th labeled frame (MM-OR frames 1 s apart are near-duplicates)
#   IMGSZ=640             train at 640 px instead of 1024
#   SEG_EPOCHS=30 POSE_EPOCHS=15 REID_EPOCHS=10
#   MODELS="seg"          train only the surface/role model; keep the base pose and ReID models
#   MODELS=""             train nothing: only score (and tune) with the installed models
#   EVAL_SPLIT=val        score on the validation surgery and skip downloading the test split
#   EVAL=0                skip step 4 (and the test download)
#
# Better models and rules:
#   FINETUNE=1            start from the installed OR models (lower learning rate) instead of the released weights
#   INSTALL=if-better     a new model replaces the installed one only if it scores higher on held-out data
#                         (default; also "always" or "never")
#   TUNE=1                score the val and test surgeries, tune the breach rules on val (step 5),
#                         report them on test and install them for the worker
#   REUSE_EVAL=1          reuse step-4 outputs that already exist instead of re-running the video pipeline
set -euo pipefail
DATA=${DATA:-/data}
PROFILE=${PROFILE:-small}     # tiny = 1/1/1 surgeries; small = 2 train / 1 val / 1 test; full = all main takes
DEVICE=${DEVICE:-0}
[[ "$DEVICE" == auto ]] && DEVICE=0   # the worker's .env says auto; the trainers want a GPU index (or cpu)
CAMERAS=${CAMERAS:-auto}      # camera used as the "one angled camera" (auto: simstation 0, else azure 4)
MODELS=${MODELS-"seg pose reid"}   # set but empty = train nothing
EVAL=${EVAL:-1}
EVAL_SPLIT=${EVAL_SPLIT:-test}
TUNE=${TUNE:-0}
EVAL_SPLITS=${EVAL_SPLITS:-$EVAL_SPLIT}
[[ "$TUNE" == 1 ]] && EVAL_SPLITS="val test"
INSTALL=${INSTALL:-if-better}
TRAIN_OPTS="--install $INSTALL"
[[ "${FINETUNE:-0}" == 1 ]] && TRAIN_OPTS="$TRAIN_OPTS --from-installed"
SPLITS=train,val
[[ "$EVAL" == 1 && " $EVAL_SPLITS " == *" test "* ]] && SPLITS=train,val,test
M="$DATA/MM-OR_data"
step() { echo; echo "=== $* ==="; }
has() { [[ " $MODELS " == *" $1 "* ]]; }
opt() { [[ -n "${2:-}" ]] && echo "$1 $2" || true; }   # "--flag value" only when value is set

step "1. Download MM-OR ($PROFILE: $SPLITS)"
python -m training.fetch_mmor --out "$DATA" --profile "$PROFILE" --splits "$SPLITS"

step "2. Build datasets ($MODELS)"
# shellcheck disable=SC2046
has seg  && python -m training.build_seg_dataset  --mmor "$M" --out "$DATA/rescrub_seg" $(opt --every "${EVERY:-}")
# shellcheck disable=SC2046
has reid && python -m training.build_reid_dataset --mmor "$M" --out "$DATA/rescrub_reid" $(opt --every "${EVERY:-}")
# shellcheck disable=SC2046
has pose && python -m training.build_pose_dataset --mmor "$M" --out "$DATA/rescrub_pose" --device "$DEVICE" \
  $(opt --every "${EVERY:-}")
python -m training.export_contacts --mmor "$M" --out "$DATA/rescrub_contacts.jsonl"

step "3. Train ($INSTALL: a model is installed in MODELS_DIR/trained only per that policy)"
# shellcheck disable=SC2046,SC2086
has seg  && python -m training.train seg  --data "$DATA/rescrub_seg/dataset.yaml"  --device "$DEVICE" --project "$DATA/runs" \
  $TRAIN_OPTS $(opt --epochs "${SEG_EPOCHS:-}") $(opt --imgsz "${IMGSZ:-}")
# shellcheck disable=SC2046,SC2086
has pose && python -m training.train pose --data "$DATA/rescrub_pose/dataset.yaml" --device "$DEVICE" --project "$DATA/runs" \
  $TRAIN_OPTS $(opt --epochs "${POSE_EPOCHS:-}") $(opt --imgsz "${IMGSZ:-}")
# shellcheck disable=SC2046,SC2086
has reid && python -m training.train reid --data "$DATA/rescrub_reid"              --device "$DEVICE" --project "$DATA/runs" \
  $TRAIN_OPTS $(opt --epochs "${REID_EPOCHS:-}")

if [[ "$EVAL" != 1 ]]; then echo "Skipping step 4 (EVAL=$EVAL)."; exit 0; fi

step "4. End-to-end on held-out surgeries ($EVAL_SPLITS): label, track, analyze, score timestamps"
export SURFACE_CONFIG=config/surfaces_mmor.yaml
# Pose and identity: the installed trained models if present (as in the worker), unless set explicitly.
# Evaluation videos are whole surgeries (often >1 h at 1 fps): ignore the upload limit from .env.
export MAX_VIDEO_SEC=${EVAL_MAX_VIDEO_SEC:-14400}
for split in $EVAL_SPLITS; do
  # Separate folders per split, so a validation run never picks up (or reports) test surgeries.
  VIDEOS="$DATA/eval_videos/$split"
  RESULTS="$DATA/eval_results/$split"
  python -m training.make_eval_videos --mmor "$M" --out "$VIDEOS" --split "$split" --cameras "$CAMERAS"
  mkdir -p "$RESULTS"
  for v in "$VIDEOS"/*.mp4; do
    n=$(basename "$v" .mp4)
    if [[ "${REUSE_EVAL:-0}" == 1 && -f "$RESULTS/$n/summary.json" ]]; then
      echo "$n: reusing $RESULTS/$n"
    else
      python -m rescrub.pipeline.run "$v" --out "$RESULTS/$n"
    fi
    python -m rescrub.analysis.breaches --jsonl "$RESULTS/$n" --out "$RESULTS/$n.findings.json" > /dev/null
  done
  python -m training.evaluate_breaches --mmor "$M" --videos "$VIDEOS" --results "$RESULTS"
  echo "Report: $RESULTS/evaluation.json  Labeled videos: $RESULTS/*/*.annotated.mp4"
done

if [[ "$TUNE" == 1 ]]; then
  step "5. Tune the breach rules on val, report on test, install for the worker"
  python -m training.tune_breaches --mmor "$M" \
    --tune-results "$DATA/eval_results/val" --tune-videos "$DATA/eval_videos/val" \
    --report-results "$DATA/eval_results/test" --report-videos "$DATA/eval_videos/test"
  # Re-score with the installed rules so evaluation.json matches what the worker will do.
  for split in $EVAL_SPLITS; do
    for v in "$DATA/eval_videos/$split"/*.mp4; do
      n=$(basename "$v" .mp4)
      python -m rescrub.analysis.breaches --jsonl "$DATA/eval_results/$split/$n" \
        --out "$DATA/eval_results/$split/$n.findings.json" > /dev/null
    done
    python -m training.evaluate_breaches --mmor "$M" --videos "$DATA/eval_videos/$split" \
      --results "$DATA/eval_results/$split"
  done
fi
