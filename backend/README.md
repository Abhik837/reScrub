# reScrub backend

The API, the analysis worker, the vision pipeline, the breach rules, the Gemini report and the
accounts CLI. How they fit together: [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

| Path | What it is |
| --- | --- |
| `rescrub/api.py`, `main.py` | FastAPI app ([docs/API.md](../docs/API.md)) |
| `rescrub/auth.py`, `emails.py`, `accounts.py` | Sign-up, sign-in and sessions; sign-up email checks (provider rules, DNS); the accounts CLI |
| `rescrub/worker.py` | Job loop: claims a queued recording, runs the pipeline and the breach rules, saves the labeled video |
| `rescrub/pipeline/` | Vision stages: `people`, `identity`, `hands`, `surfaces`, `depth`, `proximity`, `render`; `run.py` runs them (also a CLI) |
| `rescrub/analysis/breaches.py` | Breach rules: contacts → findings |
| `rescrub/report.py` | Final report written by Google Gemini |
| `rescrub/db.py`, `storage.py`, `settings.py` | Database access, video storage (folder or S3), all settings (environment variables) |
| `rescrub/init_db.py`, `download_models.py` | Apply `db/schema.sql`; pre-download the public models |
| `config/` | Surface designations for the trained model (`surfaces_mmor.yaml`) and the open-vocabulary model (`surfaces.yaml`); tracker settings |
| `db/schema.sql`, `db/app_role.sql` | Tables and hypertables; a least-privilege database user for servers |
| `models/trained/` | The trained models ([README](models/trained/README.md)) |
| `training/` | Training and evaluation on MM-OR ([README](training/README.md), guide: [docs/TRAINING.md](../docs/TRAINING.md)) |
| `Dockerfile.api` | API image (no ML libraries) |
| `Dockerfile.cpu`, `Dockerfile` | Worker images: CPU (local stack) and CUDA (NVIDIA GPU, also used for training) |
| `docker-compose.yml` | Servers: profile `api` (web server) and `worker` (GPU server); [docs/DEPLOY.md](../docs/DEPLOY.md) |

## Development

Everything runs with Docker from the repository root ([docs/RUN_LOCAL.md](../docs/RUN_LOCAL.md)).
To work on the backend directly (Python 3.12+, ffmpeg, PostgreSQL with pgvector):

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install torch torchvision          # worker only; on Linux without a GPU add --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-dev.txt    # macOS/ARM: also pip install onnxruntime

# One video, no database: JSON lines + labeled video in out/
python -m rescrub.pipeline.run clip.mp4 --out out/ [--zones zones.json]

# API + worker against a local database
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rescrub STORAGE_BACKEND=local \
       CORS_ORIGINS=http://localhost:3000 COOKIE_SECURE=false
python -m rescrub.init_db
python -m rescrub.accounts ensure you@example.com     # admin; prints the password
uvicorn rescrub.main:app --port 8000 --root-path /api &
python -m rescrub.worker
```

Tests and lint (database tests are skipped unless `TEST_DATABASE_URL` points at a disposable
database with pgvector):
```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rescrub_test pytest
ruff check --select E,F,W,I rescrub training tests
```
