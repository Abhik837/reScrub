#!/usr/bin/env bash
# Update the GPU server (labeling, tracking, analysis) to the latest main:  bash ~/reScrub/deploy/update-worker.sh
set -euo pipefail
cd ~/reScrub
git pull --ff-only
cd backend
docker compose --profile worker up -d --build
docker compose --profile worker logs --tail 20 worker
