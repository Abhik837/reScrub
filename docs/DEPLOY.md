# Hosting reScrub on your own domain (Vultr + Tiger Cloud)

This puts your own copy of reScrub on the internet, on the stack it was built for, under your own
accounts and domain. Use it when other people need to sign in. To try reScrub, or to use it alone,
run it on one computer instead ([RUN_LOCAL.md](RUN_LOCAL.md)); the website is the same, so that
guide's screenshots apply here too. How the parts work: [ARCHITECTURE.md](ARCHITECTURE.md).

Throughout this guide, replace **`your-domain.com`** with your domain, and `<you>/reScrub` with
your fork (or `Abhik837/reScrub` to use this repository as it is).

It runs on four services:

| Service | Runs | Reached by |
| --- | --- | --- |
| **Web server** (Vultr Cloud Compute) | Caddy (HTTPS), the Next.js website, the FastAPI API | Browsers, at `https://your-domain.com` |
| **GPU server** (Vultr Cloud GPU) | The analysis worker (labeling, tracking, breach analysis) and model training | SSH only |
| **Tiger Cloud** (TimescaleDB) | Accounts, jobs, tracking data, findings | Both servers |
| **Vultr Object Storage** | Uploaded recordings and labeled videos (private bucket) | Both servers |

```
Browser ──HTTPS──▶ your-domain.com ─────────── WEB SERVER (Vultr Cloud Compute) ───────────┐
                   │ Caddy :443                                                             │
                   │   /api/*  ──▶ FastAPI API   127.0.0.1:8000 (Docker)  sign-in, uploads   │
                   │   /*      ──▶ Next.js site  127.0.0.1:3000 (pm2)     pages              │
                   └──────────────────┬──────────────────────────────┬───────────────────────┘
                                      │ accounts, jobs, findings     │ recordings, labeled videos
                                      ▼                              ▼
                        Tiger Cloud (TimescaleDB)          Vultr Object Storage (private)
                                      ▲                              ▲
                   ┌──────────────────┴──── GPU SERVER (Vultr Cloud GPU) ───┴──────────────────┐
                   │ Worker (Docker): labeling, tracking, breach analysis — always running    │
                   │ Training on MM-OR (same image, block-storage volume)                     │
                   │ Inbound: SSH only. It pulls jobs from Tiger Cloud.                       │
                   └──────────────────────────────────────────────────────────────────────────┘
```

How a recording flows:
1. The browser only talks to `https://your-domain.com`. The API is under `/api` on the same
   origin, so the sign-in cookie is first-party and no cross-site requests are needed.
2. The API saves the upload to Object Storage and adds a `queued` job row in Tiger Cloud.
3. The GPU worker claims the job, downloads the video, writes tracking data and findings to
   Tiger Cloud, and uploads the labeled video.
4. The website polls `/api/sessions/<id>` and plays `/api/sessions/<id>/annotated.mp4`.
   Only the account that uploaded a recording can see it.

**Order:** 1 Repository → 2 Tiger Cloud → 3 Object Storage → 4 Domain → 5 Web server →
6 Accounts → 7 GPU server → 8 Models → 9 Verify. Section 10 covers day-to-day operations.

**What it costs** (approximate prices, late 2026; check each console):

| Service | Size | About |
| --- | --- | --- |
| Vultr web server | Cloud Compute, 2 vCPU / 4 GB | ~$20/month |
| Vultr GPU server | A16 16 GB for analysis (~$0.47/h). Training is faster on an L40S 48 GB (~$1.67/h) | ~$340/month if always on; delete it when idle |
| Vultr Object Storage | Standard tier | $18/month, including 1 TB stored and 1 TB of outbound transfer |
| Tiger Cloud | Smallest compute | from ~$30/month plus storage; a free tier exists for trying it |
| Domain | any registrar | ~$10–20/year |
| Google Gemini (optional) | API key | free tier available |

**Where secrets live.** Keep each credential in your password manager and in exactly one place on
the servers; never in the repository:

| Secret | Stored in |
| --- | --- |
| Tiger Cloud `tsdbadmin` password | Your password manager. Used only from your laptop for schema changes. |
| `rescrub_app` database password | Password manager, and `DATABASE_URL` in `backend/.env` on both servers |
| Object Storage access and secret keys | Password manager, and `backend/.env` on both servers |
| GitHub deploy keys | One per server, created on that server (`~/.ssh/rescrub_deploy`); never copied elsewhere |
| SSH private key | Your laptop only (`~/.ssh`), with a passphrase. Vultr gets the `.pub` line. |

`backend/.env` is mode 600 and is never committed. `web/.env.local` holds no secrets.

---

## 1. Repository

**Fork** the repository on GitHub if you'll change it, or use `Abhik837/reScrub` as it is. The
servers deploy the `main` branch.
- **Public repository:** the servers clone it over HTTPS
  (`git clone https://github.com/<you>/reScrub.git ~/reScrub`); skip "Deploy key".
- **Private fork:** give each server a read-only deploy key as below, and clone with
  `git clone git@github.com:<you>/reScrub.git ~/reScrub`.

### Deploy key

Run on each server, as the user that will own `~/reScrub` (`rescrub` on the web server,
`root` on the GPU server):
```bash
ssh-keygen -t ed25519 -N "" -C "rescrub-$(hostname)" -f ~/.ssh/rescrub_deploy
cat >> ~/.ssh/config <<'CFG'
Host github.com
  IdentityFile ~/.ssh/rescrub_deploy
  IdentitiesOnly yes
CFG
chmod 600 ~/.ssh/config
ssh-keyscan github.com >> ~/.ssh/known_hosts
cat ~/.ssh/rescrub_deploy.pub     # one line starting with ssh-ed25519
```
In GitHub: repository **Settings → Deploy keys → Add deploy key**. Title it after the server
(`rescrub-web`, `rescrub-gpu`), paste the `.pub` line, and leave **Allow write access**
unchecked. Then check it from the server: `ssh -T git@github.com` answers
"Hi <you>/reScrub! You've successfully authenticated…".

GitHub accepts a key on only one repository, so each server gets its own. The private key
(`~/.ssh/rescrub_deploy`, without `.pub`) never leaves its server.

## 2. Tiger Cloud (TimescaleDB)

Tiger Cloud is Tiger Data's fully managed PostgreSQL service with TimescaleDB. reScrub uses it
for accounts, the job queue, tracking data (TimescaleDB hypertables) and findings, plus pgvector
for person embeddings.

1. In the Tiger Cloud console, **Create service**:
   - type **Time series and analytics** (TimescaleDB + pgvector);
   - region **AWS US East (N. Virginia)**, closest to Vultr New Jersey;
   - start with the smallest compute size and scale up as recordings grow.

   Save the `tsdbadmin` password in your password manager and note the host and port.
2. Create the tables and the app user from your laptop (needs `psql` 16+ and a clone of this
   repository):
   ```bash
   cd reScrub/backend
   export ADMIN_DATABASE_URL='postgres://tsdbadmin:<admin password>@<host>:<port>/tsdb?sslmode=verify-full&sslrootcert=system'
   psql "$ADMIN_DATABASE_URL" -f db/schema.sql

   APP_PW=$(openssl rand -base64 32 | tr -d '/+='); echo "$APP_PW"   # save in the password manager
   psql "$ADMIN_DATABASE_URL" -v app_password="'$APP_PW'" -f db/app_role.sql
   ```
   - `schema.sql` enables `timescaledb` and `vector`, and creates the account, job,
     tracking (hypertables with compression) and findings tables. It is safe to re-run.
   - `app_role.sql` creates `rescrub_app`, which can read and write rows but cannot drop or
     alter tables.
3. The servers connect as `rescrub_app` with certificate verification:
   ```
   DATABASE_URL=postgres://rescrub_app:<app password>@<host>:<port>/tsdb?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt
   ```
4. After sections 5 and 7, open the service's **Security → IP allow list** and allow only the
   web server IP, the GPU server IP and your own IP.
5. Test from each server once it exists: `psql "<DATABASE_URL>" -c "select 1"`.

## 3. Vultr Object Storage

1. **Products → Object Storage → Add**, location **New Jersey (ewr1)**.
2. Create a **private** bucket named `rescrub-videos`.
3. Copy the hostname (`ewr1.vultrobjects.com`), the access key and the secret key.

Videos are streamed to their owner through the API; the bucket is never public.

## 4. Domain

Buy a domain at any registrar. In its DNS settings, remove any default or parked records, then
add:

| Type | Host | Answer | TTL |
| --- | --- | --- | --- |
| A | *(blank)* | web server IPv4 | 600 |
| A | `www` | web server IPv4 | 600 |

- `www.your-domain.com` redirects to `your-domain.com`.
- The API is at `your-domain.com/api`, so it needs no record of its own.
- The GPU server needs no DNS record.
- If the web server has IPv6 enabled, add matching `AAAA` records.

Check with `dig +short your-domain.com` before section 5's HTTPS step; Caddy needs the record
in place to get a certificate.

## 5. Web server (website + API)

**Create:** Vultr → **Deploy → Cloud Compute → Shared CPU**, location **New Jersey**,
**Ubuntu 24.04 LTS**, **2 vCPU / 4 GB**, your SSH key, hostname `rescrub-web`. Put its IP in
DNS (section 4).

**Base setup** (`ssh root@WEB_IP`):
```bash
apt update && apt -y upgrade
curl -fsSL https://deb.nodesource.com/setup_24.x | bash -
apt install -y nodejs git caddy ufw docker.io docker-compose-v2 unattended-upgrades postgresql-client
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw --force enable
npm install -g pm2

# The app runs as an unprivileged user that may use Docker
adduser --disabled-password --gecos "" rescrub && usermod -aG docker rescrub
mkdir -p /home/rescrub/.ssh && cp ~/.ssh/authorized_keys /home/rescrub/.ssh/ && chown -R rescrub:rescrub /home/rescrub/.ssh

# SSH keys only. Confirm `ssh rescrub@WEB_IP` works in a second window first.
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/; s/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config && systemctl restart ssh
```

**API and website** (as `rescrub`: `ssh rescrub@WEB_IP`):
```bash
# Private fork only: first create this server's deploy key (section 1) and clone with git@github.com:<you>/reScrub.git
git clone https://github.com/<you>/reScrub.git ~/reScrub

# API
cd ~/reScrub/backend
cp .env.example .env && chmod 600 .env
nano .env        # CORS_ORIGINS=https://your-domain.com, DATABASE_URL (section 2), S3_* (section 3),
                 # optional GEMINI_API_KEY for final reports (from https://aistudio.google.com)
psql "$(grep ^DATABASE_URL .env | cut -d= -f2-)" -c "select 1"   # database reachable
docker compose --profile api up -d --build
curl -s localhost:8000/health    # {"ok":true}

# Website
cd ~/reScrub/web
printf 'NEXT_PUBLIC_API_BASE_URL=/api\nAPI_INTERNAL_URL=http://127.0.0.1:8000\n' > .env.local
npm ci && npm run build
pm2 start npm --name rescrub-web -- start -- -H 127.0.0.1
pm2 save && pm2 startup          # run the command it prints, as root
```

**HTTPS and routing** (as root):
```bash
sed 's/example.com/your-domain.com/g' /home/rescrub/reScrub/deploy/Caddyfile > /etc/caddy/Caddyfile
systemctl reload caddy
```
Caddy obtains and renews the certificates automatically. The Caddyfile:
- sends `/api/*` to the API, with a 520 MB upload limit and streaming;
- sends everything else to the website;
- redirects `www` to the bare domain.

## 6. Accounts

Anyone can create an account with an email address and password at
`https://your-domain.com/register`, from any email domain. Addresses are checked against their
provider's rules (Gmail, Outlook, Yahoo, iCloud, Proton, AOL) or, for other domains, against DNS. To
change who can sign up, set in `backend/.env` and restart the API:
- `ALLOW_REGISTRATION=false`: no sign-up; you create every account;
- `REGISTRATION_EMAIL_DOMAINS=school.edu`: only addresses at your institution (comma separated).

With open sign-up, every account can queue analysis on your GPU server; each one can upload
`UPLOADS_PER_DAY_PER_USER` recordings a day (default 20). Lower it if the GPU is busy.

Create accounts yourself on the web server, as `rescrub`:
```bash
cd ~/reScrub/backend
docker compose --profile api run --rm api python -m rescrub.accounts add you@school.edu --admin
docker compose --profile api run --rm api python -m rescrub.accounts add trainee@school.edu
```
Each command prints a generated 20-character password. Send it to the person through a
private channel; they sign in at `https://your-domain.com/login`.

| Task | Command (same `docker compose … run --rm api` prefix) |
| --- | --- |
| New password (signs them out everywhere) | `python -m rescrub.accounts reset <email>` |
| Block or unblock | `python -m rescrub.accounts disable <email>` / `enable <email>` |
| List accounts | `python -m rescrub.accounts list` |
| Delete an account with all its recordings and files | `python -m rescrub.accounts delete <email>` |

Users delete their own recordings with **Delete recording** in the review.

## 7. GPU server (analysis)

**Create:** Vultr → **Deploy → Cloud GPU**, location **New Jersey** (or the nearest with
stock), **Ubuntu 22.04 LTS** with NVIDIA drivers, your SSH key, hostname `rescrub-gpu`.
Analysis needs a 16 GB GPU (an A16 is enough); training is much faster on a 48 GB L40S or an A100.

Attach **Block Storage** in the same location for training data ([TRAINING.md](TRAINING.md#what-you-need)
lists sizes); analysis alone doesn't need it.

```bash
ssh root@GPU_IP
apt update && apt -y upgrade
apt install -y docker.io docker-compose-v2 git ufw unattended-upgrades postgresql-client
ufw allow 22 && ufw --force enable          # nothing else inbound: the worker pulls jobs
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/; s/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config && systemctl restart ssh
nvidia-smi                                  # shows the GPU; if not: ubuntu-drivers install && reboot

# NVIDIA Container Toolkit (lets Docker use the GPU)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt update && apt install -y nvidia-container-toolkit && nvidia-ctk runtime configure --runtime=docker && systemctl restart docker

# Block storage, only if you'll train here. Check the device name with lsblk; mkfs erases it, so only on a new volume.
lsblk
mkfs.ext4 /dev/vdb && mkdir -p /mnt/data && mount /dev/vdb /mnt/data
echo '/dev/vdb /mnt/data ext4 defaults,nofail 0 2' >> /etc/fstab

# Private fork only: first create this server's deploy key (section 1) and clone with git@github.com:<you>/reScrub.git
git clone https://github.com/<you>/reScrub.git ~/reScrub
cd ~/reScrub/backend
cp .env.example .env && chmod 600 .env && nano .env      # same DATABASE_URL and S3_* as the web server
psql "$(grep ^DATABASE_URL .env | cut -d= -f2-)" -c "select 1"
mkdir -p /mnt/data && chown -R 1000:1000 models /mnt/data
docker compose --profile worker build                    # includes the base model weights (~15 min)
docker compose --profile worker up -d
docker compose --profile worker logs -f worker           # "Worker ready"
```

The worker now analyzes uploads and restarts on reboot (`restart: unless-stopped`). It uses the
repository's trained models (`backend/models/trained/`) automatically; section 8 explains them and
how to train your own.

## 8. Models

Nothing to do: the worker uses the three trained models in `backend/models/trained/` automatically
(the compose file mounts that folder), and public models for hands and depth, baked into the image.
MM-OR's terms of use apply to the trained weights ([models/trained/README.md](../backend/models/trained/README.md)).

To retrain or fine-tune them on this GPU server, follow [TRAINING.md](TRAINING.md): the server already
has everything it needs (Docker, the NVIDIA Container Toolkit, `/mnt/data`). Stop the worker first
(`docker compose --profile worker stop worker`) so training has the GPU, and start it again afterwards
(`docker compose --profile worker up -d`); it loads the new models. Back them up to your bucket with
`docker compose --profile worker run --rm worker python -m training.backup_models push <name>`.

## 9. Verify

**End to end:**
1. `https://your-domain.com` loads; `https://your-domain.com/api/health` returns `{"ok":true}`.
2. `https://your-domain.com/review` sends you to **Sign in**. Choose **Create an account** and sign up
   with your email (or sign in with an account from section 6).
3. Upload a short MP4. It goes from queued to analyzing to completed and shows the labeled
   video with timestamped findings. Seeking works.
4. Confirm a finding and reload: the decision is kept. **Sign out**; `/review` asks you to
   sign in again.

**Security** (from your laptop):
```bash
curl -sI https://your-domain.com | grep -iE "content-security|strict-transport"       # both present
curl -s -o /dev/null -w "%{http_code}\n" https://your-domain.com/api/docs                # 404
curl -s https://your-domain.com/api/sessions/00000000-0000-0000-0000-000000000000        # {"error":"Please sign in."}
curl -s -X POST -H "Origin: https://evil.example" -H "Content-Type: application/json" \
  -d '{"email":"a@b.co","password":"x"}' https://your-domain.com/api/auth/login          # 403
nc -zv -w3 WEB_IP 3000; nc -zv -w3 WEB_IP 8000; nc -zv -w3 GPU_IP 8000                  # all refused
for i in $(seq 12); do curl -s -o /dev/null -w "%{http_code} " -H "Origin: https://your-domain.com" \
  -H "Content-Type: application/json" -d '{"email":"nobody@example.com","password":"wrong-password"}' \
  https://your-domain.com/api/auth/login; done; echo                                      # 401 ×10, then 429
curl -s -H "Origin: https://your-domain.com" -H "Content-Type: application/json" \
  -d '{"email":"someone@no-such-domain-rescrub.invalid","password":"a long test password"}' \
  https://your-domain.com/api/auth/register                                               # "... doesn't receive email ..."
```
On both servers, `ls -l ~/reScrub/backend/.env` shows `-rw-------`.

**Troubleshooting:**

| Problem | Where to look |
| --- | --- |
| Uploads stay "queued" | GPU server: `docker compose --profile worker logs worker`. Is it running, and does `psql` reach Tiger Cloud (IP allow list)? |
| Sign-up says a real domain "doesn't receive email" | The web server's DNS: `docker compose --profile api exec api python -c "import dns.resolver; print(dns.resolver.resolve('school.edu', 'MX')[0])"`. Fix DNS, or set `CHECK_EMAIL_DNS=false` in `backend/.env` and restart the API. |
| Sign-in fails for everyone | Web server: `docker compose --profile api logs api`. `CORS_ORIGINS` must be exactly `https://your-domain.com`. |
| `/review` returns to sign-in after signing in | `web/.env.local` needs `API_INTERNAL_URL=http://127.0.0.1:8000`; rebuild and `pm2 restart rescrub-web`. |
| Database certificate error | `DATABASE_URL` must end in `sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt`. The app's Postgres driver bundles its own OpenSSL, which doesn't find the system certificates from `sslrootcert=system`. |
| No HTTPS | DNS doesn't point at the web server yet; `journalctl -u caddy`. |

## 10. Operations

**Deploy a change** (after its pull request is merged into `main`):
- Web server, as `rescrub`: `bash ~/reScrub/deploy/update-web.sh` (pulls, rebuilds the API
  and website, restarts both, checks `/api/health`).
- GPU server: `bash ~/reScrub/deploy/update-worker.sh`.
- If the change touches `backend/db/schema.sql`, apply it first from your laptop with the
  admin URL: `psql "$ADMIN_DATABASE_URL" -f db/schema.sql` (safe to re-run; for example, it adds
  `proximity_events.person_designation`, which the worker writes and the breach rules read). A new table also needs the app
  user's permissions, e.g. for the `reports` table:
  `psql "$ADMIN_DATABASE_URL" -c "GRANT SELECT, INSERT, UPDATE, DELETE ON reports TO rescrub_app"`.

**Logs:** `docker compose --profile api logs -f api`, `pm2 logs rescrub-web`,
`journalctl -u caddy` (web server); `docker compose --profile worker logs -f worker` (GPU server).

**Backups:** Tiger Cloud backs up the service automatically; restores are in the service's
**Operations** tab.

**Retrain:** see section 8.

**Rotate a credential** (scheduled, or immediately if one is ever exposed):
- **Database:** `ALTER ROLE rescrub_app PASSWORD '<new>';` as `tsdbadmin`, then update
  `DATABASE_URL` on both servers and restart the API and worker. Reset `tsdbadmin` in the
  Tiger Cloud console.
- **Object Storage:** regenerate the keys in Vultr, update `S3_*` on both servers, restart.
- **Gemini:** create a new key in Google AI Studio, update `GEMINI_API_KEY` on the web server,
  restart the API, then delete the old key.
- **SSH:** add the new public key to `~/.ssh/authorized_keys` on both servers and in Vultr,
  confirm it works, then remove the old one.
- **Deploy key:** on the server, delete `~/.ssh/rescrub_deploy*` and create a new key as in
  section 1; in GitHub, add the new key and delete the old one under **Settings → Deploy keys**.
