# ── Stage 1: build the Vite frontend ─────────────────────────────────────────
FROM node:20-slim AS web-builder
WORKDIR /app/web

# Install pnpm
RUN npm install -g pnpm

COPY web/package.json web/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

COPY web/ ./
RUN pnpm build

# ── Stage 2: Python runtime (aarch64-compatible slim image) ──────────────────
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY api api
COPY vision vision
COPY events events
COPY analytics analytics
COPY telemetry telemetry
COPY store store
COPY packs packs
COPY configs configs
RUN pip install --no-cache-dir -e .

# Copy compiled frontend into the image
COPY --from=web-builder /app/web/dist /app/web/dist

EXPOSE 8080
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
