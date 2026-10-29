#!/usr/bin/env bash
# Update the web server (website + API) to the latest main:  bash ~/reScrub/deploy/update-web.sh
set -euo pipefail
cd ~/reScrub
git pull --ff-only
echo "== website"
cd web && npm ci && npm run build && (pm2 restart rescrub-web || pm2 start npm --name rescrub-web -- start -- -H 127.0.0.1) && pm2 save
echo "== API"
cd ../backend
docker compose --profile api up -d --build
# Schema changes (rare) are applied separately with the admin login: see docs/DEPLOY.md, section 10.
echo "== checks"
sleep 5
# The site's address is the first CORS_ORIGINS entry in backend/.env (e.g. https://your-domain.com).
SITE=$(grep -E '^CORS_ORIGINS=' .env | cut -d= -f2- | cut -d, -f1)
curl -fsS "$SITE/api/health" && echo "  API ok"
curl -fsS -o /dev/null "$SITE" && echo "  website ok"
