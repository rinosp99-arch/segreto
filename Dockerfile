# LATO SEGRETO: React app + Node server in one image. Content lives on a volume mounted at /data.

# ---------- 1. build the React app ----------
FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps --no-audit --no-fund
COPY frontend/ ./
ENV GENERATE_SOURCEMAP=false CI=false
RUN npm run build

# ---------- 2. server ----------
FROM node:22-bookworm-slim
WORKDIR /app
COPY server/package.json server/package-lock.json ./server/
RUN cd server && npm ci --omit=dev --no-audit --no-fund
COPY server/ ./server/
COPY scripts/ ./scripts/
# content snapshot of the old site (texts only; media are fetched by the import)
COPY inhalte/daten ./inhalte/daten
COPY inhalte/medien-liste.json ./inhalte/
COPY --from=frontend /app/frontend/build ./frontend/build

ENV NODE_ENV=production \
    DATA_DIR=/data \
    PORT=8001
WORKDIR /app/server
EXPOSE 8001
CMD ["node", "--disable-warning=ExperimentalWarning", "index.js"]
