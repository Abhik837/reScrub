# The website image for the local Docker stack (docker-compose.local.yml). A self-hosted web server
# runs `npm run build && npm start` under pm2 instead (docs/DEPLOY.md).
FROM node:24-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Public, baked into browser code: the API is on this site's own origin under /api (Caddy routes it).
ARG NEXT_PUBLIC_API_BASE_URL=/api
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build && npm prune --omit=dev

FROM node:24-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node /app/package.json /app/next.config.ts ./
COPY --from=build --chown=node /app/node_modules ./node_modules
COPY --from=build --chown=node /app/.next ./.next
COPY --from=build --chown=node /app/public ./public
USER node
EXPOSE 3000
CMD ["npm", "start"]
