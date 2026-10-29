# Run reScrub on your own computer

One command starts the whole project locally: the website, the API, the analysis worker, a
TimescaleDB database (the same engine as Tiger Cloud) and a folder for recordings. Nothing
leaves your computer except model downloads on the first start, and the final report if you
add a Gemini key.

```
http://localhost:8080 ── proxy (Caddy) ─┬─ /api/*  → api     FastAPI: sign-in, uploads, results
                                        └─ /*      → web     Next.js website
                     api ◀── db (TimescaleDB + pgvector) ──▶ worker  labeling, tracking, breach analysis
                     api ◀──── recordings volume ──────────▶ worker
```
It's the self-hosted layout ([DEPLOY.md](DEPLOY.md)) on one machine; [ARCHITECTURE.md](ARCHITECTURE.md)
explains each part. Tiger Cloud becomes the
`db` container, Vultr Object Storage becomes the `recordings` volume, and the GPU server becomes
the `worker` container.

**Models:** the worker uses the three trained models included in
[`backend/models/trained`](../backend/models/trained/README.md): surfaces, pose and identity, trained on
MM-OR, whose terms of use apply. It downloads public models for hands and depth on the first start.

| You need | Notes |
| --- | --- |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) (macOS, Windows) or Docker Engine + Compose v2 (Linux, WSL 2) | `docker compose version` must print v2+. Give Docker at least **8 GB of memory** (Docker Desktop → Settings → Resources; WSL 2: see Troubleshooting). |
| ~15 GB of free disk | The images (the database image alone is ~4 GB) and the models (~1 GB). |
| Optional: NVIDIA GPU | Linux, or Windows with WSL2, plus the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Without one, analysis runs on the CPU (slower). |
| Optional: Gemini API key | For the final review report. Free at [Google AI Studio](https://aistudio.google.com) → **Get API key**. |

## 1. Get the code and start it

```bash
git clone https://github.com/Abhik837/reScrub.git
cd reScrub
cp .env.example .env          # optional: add GEMINI_API_KEY, change LOCAL_ADMIN_EMAIL
docker compose -f docker-compose.local.yml up --build
```

The first start takes a while: it builds four images and the worker downloads its models into
the `models` volume. Later starts take seconds. When the log shows `Worker ready` and the `web`
service is up, open **http://localhost:8080**.

Leave that terminal running; press `Ctrl+C` there to stop. To run in the background instead,
add `-d` and follow the log with `docker compose -f docker-compose.local.yml logs -f`.

**With an NVIDIA GPU:**
```bash
docker compose -f docker-compose.local.yml -f docker-compose.local.gpu.yml up --build
```

## 2. Get the admin password

On the first start, the `init` service creates the database tables and an admin account for
`LOCAL_ADMIN_EMAIL` (default `admin@example.com`), prints a generated password once, and exits:
```bash
docker compose -f docker-compose.local.yml logs init
```
![The init log with the admin email and its password](images/local/08-admin-password.png)

Lost it? Make a new one:
```bash
docker compose -f docker-compose.local.yml run --rm init python -m rescrub.accounts reset admin@example.com
```
More accounts: choose **Create account** on the sign-in page, or
`... run --rm init python -m rescrub.accounts add someone@example.com`.

## 3. Sign in or create an account

Open http://localhost:8080, choose **Sign in** (top right) and enter the admin email and password:

![Sign-in page](images/local/02-sign-in.png)

Anyone else chooses **Create an account** and enters an email address from any provider and a
password (at least 12 characters). The address must fit its provider's rules (a Gmail name, for
example, has 6–30 letters, numbers and periods), and other domains must exist and receive email.
Each account sees only its own recordings. To turn sign-up off, or limit it to one email domain, set
`ALLOW_REGISTRATION=false` or `REGISTRATION_EMAIL_DOMAINS=school.edu` in `.env` and run the `up`
command again; without internet access, also set `CHECK_EMAIL_DNS=false`.

![Create account page](images/local/09-create-account.png)

## 4. Analyze a recording

After signing in you land on **New review**:

![New review page](images/local/03-new-review.png)

**To try it right away, choose Analyze demo video.** It uploads a 3-minute clip of a real (simulated)
knee replacement from the MM-OR dataset, [`web/public/demo/mmor-038-demo.mp4`](../web/public/demo/README.md),
and runs it through the same analysis as any upload.

**For your own recording:**
1. **Recording:** choose an MP4 (H.264; up to 500 MB and 60 minutes).
2. **Context:** a session name, and optionally what happens in the clip.
3. **Permission:** confirm you may use the footage.

![Upload form filled in](images/local/04-upload-filled.png)

4. Choose **Analyze recording**. The recording is uploaded, waits in the queue and is analyzed
   by the worker:

![Queued for analysis](images/local/05-analyzing.png)

On a laptop CPU, expect analysis to take one to several times the clip's length (the first one
also waits for the models to load); with a GPU it is much faster. The panel shows the percentage
done, or how many recordings are ahead in the queue; the worker analyzes one at a time.
`docker compose -f docker-compose.local.yml logs -f worker` prints progress about once a minute.

You can refresh or close the page while it runs: the address (`/review?session=…`) reopens the same
recording, and **Your recordings**, beside the steps, lists your recent recordings with their state.
Open one from there, or **Cancel** one that's still queued or analyzing.

## 5. Review the results

When analysis finishes, the review opens with the **labeled video**: people as "Person 1",
"Person 2", …, their arm and hand keypoints, and sterile (green), non-sterile (red) and patient
(orange) areas, with timestamped findings beside it:

![Results with the labeled video](images/local/06-results.png)

Select a finding to jump to it, then **Confirm** or **Dismiss** it. **View demonstration** opens a
ready-made review of a synthetic clip, with no backend needed:

![A review with findings (demonstration)](images/local/07-findings-demo.png)

At the bottom, **Write report with Gemini** writes the final report from the findings and your
decisions (needs `GEMINI_API_KEY` in `.env`; the video is never sent). **Export review PDF** and
**Export incident JSON** download the review, and **Download labeled video** saves the labeled MP4.

## 6. Stop, restart, reset

```bash
docker compose -f docker-compose.local.yml down          # stop; keeps accounts, recordings, models
docker compose -f docker-compose.local.yml up            # start again
docker compose -f docker-compose.local.yml down -v       # stop and DELETE all local data (fresh start)
git pull && docker compose -f docker-compose.local.yml up --build   # update to the latest code
```

## Settings

All optional, in `.env` at the repository root (see [`.env.example`](../.env.example)), then
`docker compose -f docker-compose.local.yml up -d` to apply:

| Setting | Default | What it does |
| --- | --- | --- |
| `LOCAL_ADMIN_EMAIL` | `admin@example.com` | The first admin account |
| `ALLOW_REGISTRATION` | `true` | `false` turns off **Create account** |
| `REGISTRATION_EMAIL_DOMAINS` | empty (any domain) | Only these email domains can sign up, e.g. `school.edu` |
| `CHECK_EMAIL_DNS` | `true` | Sign-up checks that the email's domain receives mail; `false` on a computer without internet |
| `UPLOADS_PER_DAY_PER_USER` | `20` | Recordings each account can upload per day; `0` = no limit |
| `GEMINI_API_KEY` | empty (report off) | Turns on the final review report |
| `FRAME_STRIDE` | `2` (CPU), `1` (GPU) | Analyze every Nth frame; higher is faster |
| `ENABLE_DEPTH`, `ENABLE_HANDS` | `true` | `false` skips the slowest stages |
| `SURFACE_CONFIG`, `POSE_MODEL`, `EMBED_MODEL` | the trained models in `backend/models/trained` | Public models instead: `config/surfaces.yaml`, `yolo26m-pose.pt` (or the much faster `yolo26n-pose.pt`), `yolo26n-cls.pt` |

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `unknown shorthand flag: 'f' in -f` | Docker has no Compose v2 plugin. Docker Desktop includes it. On Linux or WSL 2 with Docker Engine: `sudo apt install docker-compose-plugin` (Docker's repository) or `docker-compose-v2` (Ubuntu), or download it: `mkdir -p ~/.docker/cli-plugins && curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 -o ~/.docker/cli-plugins/docker-compose && chmod +x ~/.docker/cli-plugins/docker-compose`. Check with `docker compose version`. |
| `pull access denied for rescrub-api` | A clone from before this was fixed: `git pull`, or run `docker compose -f docker-compose.local.yml build` before `up`. |
| Windows with WSL 2 | Either Docker Desktop with **Settings → Resources → WSL integration** turned on for your distribution, or Docker Engine inside the distribution (`sudo service docker start`; `sudo usermod -aG docker $USER`, then reopen the terminal). WSL 2 gets half your RAM by default: for more, put `[wsl2]` and `memory=10GB` on two lines in `%UserProfile%\.wslconfig`, then `wsl --shutdown`. Open http://localhost:8080 in the Windows browser. |
| `Read timed out` (`ReadTimeoutError`) while building | A download stalled. Run the same command again: finished steps are kept. On WSL 2 or a VPN, build the worker on the host's network instead: `docker build --network host -t rescrub-worker-cpu -f backend/Dockerfile.cpu backend`, then `docker compose -f docker-compose.local.yml up` (without `--build`). Still stalling: compare `ip link show eth0` (`mtu …`) with Docker's, and set the same value as `"mtu"` in `/etc/docker/daemon.json`. |
| `port is already allocated` for 8080 | Something else uses port 8080. Stop it, or change `127.0.0.1:8080:80` in `docker-compose.local.yml`. |
| `Can't use the database at db:5432/rescrub` (or `pool initialization incomplete`); `api` unhealthy | The API and worker couldn't use the database. The message names the cause; also check `docker compose -f docker-compose.local.yml logs db --tail 60`. *Starting up* or *timeout*: run `up` again. *Killed*, *out of memory* or exit code 137 in the `db` log: give Docker or WSL more memory. *Could not … recover* or *PANIC*: the database was damaged by a forced stop; `docker compose -f docker-compose.local.yml down -v` resets it (this erases local recordings and accounts). |
| `init` exits with an error | `docker compose -f docker-compose.local.yml logs init db` |
| Stays **Queued** | `docker compose -f docker-compose.local.yml logs worker`. On the first start the worker is still downloading models. |
| Worker `Killed` / exits with code 137 | Docker ran out of memory: give it more (Docker Desktop → Resources), or set `POSE_MODEL=yolo26n-pose.pt` and `ENABLE_DEPTH=false`. |
| Can't play the video in the browser | Re-export it as an H.264 MP4. |
| Sign-up says the domain "doesn't receive email" | Check the address after the @. Without internet, set `CHECK_EMAIL_DNS=false` in `.env`. |
| "You can upload 20 recordings a day" | Set `UPLOADS_PER_DAY_PER_USER=0` (no limit) in `.env`. |
| `could not select device driver "nvidia"` | The GPU override needs the NVIDIA Container Toolkit; use the plain command instead. |

## Without Docker (for development)

For editing code with live reload, run the pieces directly. You need Python 3.12+, Node 24,
ffmpeg, and PostgreSQL with pgvector. The local stack's database can serve as that: add
`ports: ["127.0.0.1:5432:5432"]` under `db` in `docker-compose.local.yml`, then
`docker compose -f docker-compose.local.yml up -d db`.
```bash
# Backend (terminal 1 and 2)
cd backend
python -m venv .venv && . .venv/bin/activate
pip install torch torchvision                # Linux CPU: add --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-dev.txt          # macOS/ARM: also pip install onnxruntime
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rescrub STORAGE_BACKEND=local \
       CORS_ORIGINS=http://localhost:3000 COOKIE_SECURE=false
python -m rescrub.init_db
python -m rescrub.accounts ensure admin@example.com          # prints the password
uvicorn rescrub.main:app --port 8000 --root-path /api        # terminal 1
python -m rescrub.worker                                     # terminal 2 (same exports)

# Website (terminal 3)
cd web && npm ci
NEXT_PUBLIC_API_BASE_URL=/api API_INTERNAL_URL=http://127.0.0.1:8000 API_DEV_PROXY=http://127.0.0.1:8000 npm run dev
```
Open http://localhost:3000. Tests: `TEST_DATABASE_URL=postgresql://…/rescrub_test pytest` in
`backend/`; `npm run lint && npm run build` in `web/`.
