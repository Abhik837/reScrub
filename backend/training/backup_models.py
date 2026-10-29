"""Keep trained models in the private Object Storage bucket, so they survive rebuilding the GPU server.

The weights are never committed to git (MM-OR terms of use; see models/trained/README.md). This
copies them to and from the same private bucket the worker already uses, under models/<name>/.

    python -m training.backup_models push full-2026-10      # models/trained/* -> bucket
    python -m training.backup_models list
    python -m training.backup_models pull full-2026-10      # bucket -> models/trained/ (old files kept in backup/)

On the GPU server, run it inside the worker container (it has the bucket keys from .env):
    docker compose --profile worker run --rm worker python -m training.backup_models push full-2026-10
"""

import argparse
import shutil
import time
from pathlib import Path

from rescrub.settings import get_settings
from rescrub.storage import S3Storage

PREFIX = "models/"
SUFFIXES = {".pt", ".json"}


def trained_dir() -> Path:
    return get_settings().models_dir / "trained"


def push(store: S3Storage, name: str, folder: Path) -> list[str]:
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix in SUFFIXES)
    if not files:
        raise SystemExit(f"No trained models in {folder}")
    for f in files:
        store.put_file(f, f"{PREFIX}{name}/{f.name}", content_type="application/octet-stream")
        print(f"  {f.name} -> {PREFIX}{name}/{f.name}")
    return [f.name for f in files]


def names(store: S3Storage) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for page in store.client.get_paginator("list_objects_v2").paginate(Bucket=store.bucket, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            name, _, file = obj["Key"][len(PREFIX):].partition("/")
            if file:
                found.setdefault(name, []).append(file)
    return found


def pull(store: S3Storage, name: str, folder: Path) -> list[str]:
    files = names(store).get(name)
    if not files:
        raise SystemExit(f"No backup named {name!r}. Run `list` to see them.")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for file in files:
        dest = folder / file
        if dest.exists():  # keep what was installed, like train.py does
            (folder / "backup").mkdir(exist_ok=True)
            shutil.move(dest, folder / "backup" / f"{dest.stem}-{stamp}{dest.suffix}")
        store.get_file(f"{PREFIX}{name}/{file}", dest)
        print(f"  {PREFIX}{name}/{file} -> {dest}")
    return files


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["push", "pull", "list"])
    ap.add_argument("name", nargs="?", help="a label for this set of models, e.g. full-2026-10")
    args = ap.parse_args()
    settings = get_settings()
    if settings.storage_backend != "s3":
        raise SystemExit("Set STORAGE_BACKEND=s3 and the S3_* keys (backend/.env) to use the bucket.")
    store = S3Storage(settings)
    if args.action == "list":
        for name, files in sorted(names(store).items()):
            print(f"{name}: {', '.join(sorted(files))}")
        return
    if not args.name or "/" in args.name:
        raise SystemExit("Give a name without '/', e.g. full-2026-10")
    (push if args.action == "push" else pull)(store, args.name, trained_dir())


if __name__ == "__main__":
    main()
