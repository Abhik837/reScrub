"""Download every model once (used at Docker build time so containers start fast).

    python -m rescrub.download_models
"""

import logging

from .pipeline.run import Models
from .settings import get_settings

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    s = get_settings().model_copy(update={"device": "cpu"})
    m = Models.load(s)
    missing = [name for name, model in (("hands", m.hands), ("depth", m.depth)) if model is None]
    if missing:
        raise SystemExit(f"Could not download: {', '.join(missing)}")
    print("All models ready in", s.models_dir)
