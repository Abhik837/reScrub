"""Train the three reScrub models on the datasets built from MM-OR.

    python -m training.train seg  --data /data/rescrub_seg/dataset.yaml
    python -m training.train pose --data /data/rescrub_pose/dataset.yaml
    python -m training.train reid --data /data/rescrub_reid

Each run starts from the released YOLO26 weights (transfer learning), or with
--from-installed from the model already installed (fine-tuning: lower learning rate,
fewer epochs). --resume RUN_DIR continues an interrupted run from its last epoch.
When it finishes, best.pt is scored on the validation split and copied into
MODELS_DIR under the name the backend expects:

    seg  -> trained/rescrub-or-seg.pt
    pose -> trained/rescrub-or-pose.pt
    reid -> trained/rescrub-reid-cls.pt
(the worker uses every trained model in MODELS_DIR/trained automatically)

By default (--install if-better) the new model replaces the installed one only if it scores
higher on the validation split; the old file is kept in trained/backup/. The test split is
only reported, never used to choose a model.
"""

import argparse
import shutil
import time
from pathlib import Path

import yaml

from rescrub.settings import get_settings

TASKS = {
    # base weights, output name, sensible defaults for a single 24-48 GB GPU
    "seg": ("yolo26m-seg.pt", "rescrub-or-seg.pt", {"imgsz": 1024, "epochs": 80, "batch": 8}),
    "pose": ("yolo26m-pose.pt", "rescrub-or-pose.pt", {"imgsz": 1024, "epochs": 40, "batch": 8}),
    "reid": ("yolo26n-cls.pt", "rescrub-reid-cls.pt", {"imgsz": 224, "epochs": 30, "batch": 128}),
}
# Held-out metric that decides whether a new model is better (Ultralytics results_dict keys).
METRIC = {"seg": "metrics/mAP50-95(M)", "pose": "metrics/mAP50-95(P)", "reid": "metrics/accuracy_top1"}
FINETUNE_LR0 = 0.0005  # AdamW; the released-weights default (optimizer auto) would undo much of the OR training


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task", choices=TASKS)
    ap.add_argument("--data", required=True, help="dataset.yaml (seg/pose) or folder with train/ and val/ (reid)")
    ap.add_argument("--base", help="starting weights (default: released YOLO26 weights)")
    ap.add_argument("--resume", type=Path, metavar="RUN_DIR",
                    help="continue an interrupted run (e.g. /data/runs/seg-2) from its last.pt, then install as usual")
    ap.add_argument("--from-installed", action="store_true",
                    help="fine-tune the installed model (MODELS_DIR/trained) instead of starting from --base")
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--imgsz", type=int)
    ap.add_argument("--batch", type=int)
    ap.add_argument("--lr0", type=float, help=f"initial learning rate (fine-tuning default {FINETUNE_LR0}, AdamW)")
    ap.add_argument("--patience", type=int, default=15, help="stop after this many epochs without improvement")
    ap.add_argument("--freeze", type=int, help="freeze the first N layers (e.g. 10 = backbone) when data is small")
    ap.add_argument("--device", default="0")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--project", default="runs/rescrub")
    ap.add_argument("--name")
    ap.add_argument("--install", choices=["if-better", "always", "never"], default="if-better",
                    help="copy best.pt into MODELS_DIR: only if it beats the installed model on the validation split "
                         "(default), always, or never")
    ap.add_argument("--no-install", action="store_true", help="same as --install never")
    args = ap.parse_args()
    from ultralytics import YOLO

    base, out_name, defaults = TASKS[args.task]
    installed = get_settings().models_dir / "trained" / out_name
    finetune = args.from_installed and installed.exists()
    if args.from_installed and not finetune:
        print(f"No installed {out_name} yet; starting from the released weights.")
    start = str(installed) if finetune else (args.base or base)
    params = {**defaults, **{k: v for k in ("epochs", "imgsz", "batch") if (v := getattr(args, k)) is not None}}
    if finetune:
        if args.epochs is None:
            params["epochs"] = max(10, defaults["epochs"] // 2)
        params.update(optimizer="AdamW", lr0=args.lr0 or FINETUNE_LR0, warmup_epochs=1)
    elif args.lr0 is not None:
        params.update(optimizer="AdamW", lr0=args.lr0)
    if args.freeze is not None:
        params["freeze"] = args.freeze
    if args.resume:
        last = args.resume / "weights" / "last.pt" if args.resume.is_dir() else args.resume
        print(f"Resuming {args.task} from {last}")
        model = YOLO(str(last))
        model.train(resume=True)  # same data, settings and schedule as the interrupted run
    else:
        print(f"Training {args.task} from {start}: {params}")
        model = YOLO(start)
        model.train(
            data=args.data,
            device=args.device,
            workers=args.workers,
            project=args.project,
            name=args.name or args.task,
            patience=args.patience,
            cos_lr=True,
            # The camera is fixed and overhead/angled: no vertical flips, mild geometry, strong colour jitter
            # (OR lighting changes a lot between rooms).
            **({"fliplr": 0.5, "flipud": 0.0, "degrees": 5, "scale": 0.4, "hsv_v": 0.5, "mosaic": 0.5}
               if args.task != "reid" else {}),
            **params,
        )
    best = Path(model.trainer.best)
    # The install decision uses the validation split only; the test split stays unseen until it is reported.
    new_score = held_out_score(best, args.task, args.data, args.device, "val")
    print(f"val {METRIC[args.task]}: new {new_score}")
    policy = "never" if args.no_install else args.install
    old_score = None
    if policy == "if-better" and installed.exists():
        old_score = held_out_score(installed, args.task, args.data, args.device, "val")
        print(f"val {METRIC[args.task]}: installed {old_score}")
    if args.task != "reid" and _has_images(Path(args.data), "test"):
        test_score = held_out_score(best, args.task, args.data, args.device, "test")
        print(f"test {METRIC[args.task]} (report only): new {test_score}")
    if not best.exists() or not should_install(policy, new_score, old_score, installed.exists()):
        print(f"Not installed: {best} (installed model kept)" if policy != "never" else f"Not installed: {best}")
        return
    installed.parent.mkdir(parents=True, exist_ok=True)
    if installed.exists():
        backup = installed.parent / "backup" / f"{installed.stem}-{time.strftime('%Y%m%d-%H%M%S')}.pt"
        backup.parent.mkdir(exist_ok=True)
        shutil.copyfile(installed, backup)
        print(f"Backed up the previous model -> {backup}")
    shutil.copyfile(best, installed)
    print(f"Installed {best} -> {installed}")


def held_out_score(weights: Path, task: str, data: str, device: str, split: str) -> float | None:
    """The task's held-out metric for `weights` (higher is better), or None if it can't be measured."""
    from ultralytics import YOLO

    try:
        metrics = YOLO(str(weights)).val(data=data, device=device, split=split, plots=False)
    except Exception as e:  # e.g. an installed model trained with a different class list
        print(f"Could not score {weights}: {e}")
        return None
    value = (getattr(metrics, "results_dict", None) or {}).get(METRIC[task])
    return float(value) if value is not None else None


def should_install(policy: str, new: float | None, old: float | None, has_installed: bool) -> bool:
    if policy == "never":
        return False
    if policy == "always" or not has_installed:
        return True
    if new is None:
        return False
    return old is None or new > old


def _has_images(data_yaml: Path, split: str) -> bool:
    """True if dataset.yaml names `split` and its image folder is not empty (a run may skip the test download)."""
    cfg = yaml.safe_load(data_yaml.read_text()) or {}
    if split not in cfg:
        return False
    folder = Path(cfg.get("path") or data_yaml.parent) / cfg[split]
    return folder.is_dir() and any(folder.iterdir())


if __name__ == "__main__":
    main()
