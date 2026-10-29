# reScrub

reScrub reviews recordings of practice surgeries for breaks in sterile technique. Upload a video
from one angled camera, and reScrub:
- labels everyone anonymously ("Person 1", "Person 2", …) and tells scrubbed from unscrubbed staff;
- tracks arms, hands and fingertips;
- marks sterile, non-sterile and patient areas;
- proposes timestamped moments to review, such as a scrubbed hand touching something non-sterile
  and then something sterile, or an unscrubbed person touching the sterile field;
- writes an optional final report with Google Gemini from the reviewer's decisions.

An instructor or trainee confirms or dismisses each moment beside a labeled video. reScrub is a
training tool: it suggests moments for a person to review and does not decide whether contamination
happened.

## Quick start

You only need [Docker](https://www.docker.com/products/docker-desktop/) (8 GB of memory for Docker,
~15 GB of disk).

```bash
git clone https://github.com/Abhik837/reScrub.git && cd reScrub
docker compose -f docker-compose.local.yml up --build     # first start: ~10–20 min
docker compose -f docker-compose.local.yml logs init      # admin email and password
```
Open **http://localhost:8080** and sign in as the admin, or choose **Create account**. Choose
**Analyze demo video** to send a 3-minute clip of a real (simulated) surgery from the MM-OR dataset
through the whole analysis, or upload your own MP4.
**View demonstration** opens a ready-made review without the backend.

The full walkthrough with screenshots, settings, GPU use and troubleshooting:
**[docs/RUN_LOCAL.md](docs/RUN_LOCAL.md)**.

## How it works

```
                 ┌─────────────── Caddy (http://localhost:8080) ───────────────┐
 Browser ───────▶│  /*      → web     Next.js website: sign-in, upload, review  │
                 │  /api/*  → api     FastAPI: accounts, uploads, results, report│
                 └──────────────────────────────┬──────────────────────────────┘
                                                │ queued job
        PostgreSQL + TimescaleDB + pgvector  ◀──┤──▶  recordings + labeled videos
        accounts, job queue, tracking data,     │     (folder, or an S3 bucket)
        findings, reports                       │
                                                ▼
                 worker (CPU or NVIDIA GPU): takes the job, then
                 people + pose → identity → hands → surfaces → depth
                 → hand-to-surface contacts → breach rules → findings + labeled video
```

1. The website uploads the video to the API, which stores it and adds a `queued` job.
2. The worker claims the job, runs the vision pipeline frame by frame, writes tracking data to
   the database, turns contacts into findings with the breach rules, and saves a labeled video.
3. The website polls the job, then shows the labeled video, a timeline and the findings. The
   reviewer's decisions are saved, and the Gemini report is written from them on request.

Every part is explained in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

| Layer | Technology |
| --- | --- |
| Website | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS |
| API | Python 3, FastAPI, Uvicorn; Argon2id passwords, cookie sessions |
| Worker | PyTorch, Ultralytics YOLO26 (pose, segmentation, identity) and YOLOE, BoT-SORT tracking, RTMW hands (ONNX Runtime), Depth Anything V2, OpenCV, ffmpeg |
| Database | PostgreSQL with TimescaleDB (time-series tracking data) and pgvector (person embeddings) |
| Storage | A local folder, or any S3-compatible bucket |
| Report | Google Gemini API (optional) |
| Packaging | Docker Compose, Caddy |

## Two ways to run it

| | What runs where | Guide |
| --- | --- | --- |
| **On your computer** | Everything in Docker: website, API, worker (CPU, or an NVIDIA GPU), database, recordings | [docs/RUN_LOCAL.md](docs/RUN_LOCAL.md) |
| **On your own domain** | The stack reScrub was built on, under your own accounts: a Vultr web server (website, API, Caddy with HTTPS), a Vultr GPU server (worker), Tiger Cloud (managed TimescaleDB) and Vultr Object Storage | [docs/DEPLOY.md](docs/DEPLOY.md) |

Both use the same code and images; only settings differ.

## Trained models and data

Three models trained for the operating room ship in
[`backend/models/trained/`](backend/models/trained/README.md) and are used automatically:

| Model | Does | Validation / test score |
| --- | --- | --- |
| Surfaces and roles | sterile, non-sterile and patient areas; scrubbed vs. unscrubbed people | mask mAP50-95 0.476 / 0.534 |
| Pose | arm and hand keypoints of gowned staff | 0.605 / 0.817 |
| Identity | keeps "Person N" stable across identical gowns | top-1 0.68 / – |

On a 48-minute surgery none of the models saw, the whole pipeline found **3 of its 6 labeled
sterility breaches** within 10 s on average, among 169 moments to review.

They were trained on **[MM-OR](https://github.com/egeozsoy/MM-OR)** (TU Munich, CVPR 2025): recordings of
simulated knee-replacement surgeries in a real operating room, with per-pixel labels and labeled
sterility breaches. **MM-OR's terms of use apply to these weights**; read
[`backend/models/trained/README.md`](backend/models/trained/README.md) before using them.

Retraining, fine-tuning, the full dataset, and why the shipped models saw only part of MM-OR:
**[docs/TRAINING.md](docs/TRAINING.md)**.

## Repository

| Path | Contents |
| --- | --- |
| [`web/`](web/README.md) | The website |
| [`backend/`](backend/README.md) | API, worker, vision pipeline, breach rules, Gemini report, accounts CLI, database schema |
| [`backend/models/trained/`](backend/models/trained/README.md) | The trained models and their scores |
| [`backend/training/`](backend/training/README.md) | Dataset builders, training, evaluation and rule tuning on MM-OR |
| [`docker-compose.local.yml`](docker-compose.local.yml) | The local stack (`docker-compose.local.gpu.yml` adds an NVIDIA GPU) |
| [`deploy/`](deploy/) | Caddy configs and update scripts for self-hosted servers |
| [`docs/`](docs/) | [Architecture](docs/ARCHITECTURE.md), [running locally](docs/RUN_LOCAL.md), [self-hosting](docs/DEPLOY.md), [training](docs/TRAINING.md), [API](docs/API.md), [security](docs/SECURITY.md) |

CI (`.github/workflows/ci.yml`) runs on every pull request: backend lint and tests, website lint,
type check and build, a build and start-up check of the local stack, `npm audit`, and a secret
scan of every commit.
