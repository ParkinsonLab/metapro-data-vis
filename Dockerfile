FROM node:22 AS frontend-build
WORKDIR /app
COPY package.json package-lock.json ./
# danfojs-node → @tensorflow/tfjs-node ships prebuilt x86_64 Linux binaries.
# On Apple Silicon, build with: docker build --platform linux/amd64 ...
# Enable Rosetta in Docker Desktop (Settings → General) for best performance.
RUN npm ci
COPY . .
RUN npm run build

FROM python:3.14-slim AS runtime
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# build_reference.py uses `git rev-parse` to locate resources/db/parquet
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY analytics/pyproject.toml analytics/uv.lock ./analytics/
WORKDIR /app/analytics
RUN uv sync --frozen --no-dev

WORKDIR /app
COPY analytics/ ./analytics/
COPY resources/db/parquet/ ./resources/db/parquet/
RUN git init /app

WORKDIR /app/analytics
RUN uv run python transform/scripts/build_reference.py

COPY --from=frontend-build /app/dist /app/dist

ENV DATA_ROOT=/data
ENV RUNS_DIR=/data/vis/runs
ENV REFERENCE_PARQUET_DIR=/app/analytics/transform/reference/parquet

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
