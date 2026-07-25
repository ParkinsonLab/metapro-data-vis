FROM node:22 AS frontend-build
WORKDIR /app
COPY package.json package-lock.json ./
# danfojs-node → @tensorflow/tfjs-node ships prebuilt x86_64 Linux binaries.
# On Apple Silicon, build with: docker build --platform linux/amd64 ...
# Enable Rosetta in Docker Desktop (Settings → General) for best performance.
RUN npm ci
# Explicit copies only — avoids sending gitignored local-data/ in the build context.
COPY src ./src
COPY tsconfig.json tsconfig.web.json tsconfig.server.json vite.config.ts ./
RUN VITE_DATA_MODE=mounted npm run build

FROM python:3.14-slim AS reference-build
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY analytics/pyproject.toml analytics/uv.lock ./analytics/
COPY analytics/ ./analytics/
WORKDIR /app/analytics
RUN uv sync --frozen --no-dev

WORKDIR /app
COPY resources/db/parquet/ ./resources/db/parquet/

WORKDIR /app/analytics
RUN rm -rf transform/reference/parquet \
    && mkdir -p transform/reference/parquet
RUN uv run python transform/scripts/build_reference.py

# Runtime needs bridge parquet (dbt) and pathway layout parquet (Network view) only.
RUN mkdir -p /app/runtime-parquet \
    && mv /app/resources/db/parquet/pathway_superpathways.parquet /app/runtime-parquet/ \
    && mv /app/resources/db/parquet/pathway_nodes.parquet /app/runtime-parquet/ \
    && mv /app/resources/db/parquet/pathway_edges.parquet /app/runtime-parquet/ \
    && rm -rf /app/resources/db/parquet

FROM python:3.14-slim AS runtime
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY analytics/pyproject.toml analytics/uv.lock ./analytics/
COPY analytics/ ./analytics/
COPY --from=reference-build /app/analytics/transform/reference/parquet ./analytics/transform/reference/parquet
COPY --from=reference-build /app/runtime-parquet ./resources/db/parquet
COPY --from=frontend-build /app/dist /app/dist

WORKDIR /app/analytics
RUN uv sync --frozen --no-dev

ENV DATA_ROOT=/data
ENV RUNS_DIR=/data/vis/runs
ENV REFERENCE_PARQUET_DIR=/app/analytics/transform/reference/parquet

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
