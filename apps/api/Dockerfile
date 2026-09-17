# Production image for the API and the worker (ADR-0010).
# Build from the repository root:
#   docker build -f apps/api/Dockerfile -t score-pilot-api .

FROM ghcr.io/astral-sh/uv:0.7.20 AS uv

FROM python:3.13-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /srv

COPY pyproject.toml uv.lock ./
COPY packages/engine packages/engine
COPY apps/api apps/api
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim AS runtime
RUN useradd --create-home --uid 10001 app
WORKDIR /srv
COPY --from=builder --chown=app:app /srv/.venv /srv/.venv
COPY --from=builder --chown=app:app /srv/database /srv/database
ENV PATH="/srv/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"

# Override the command to run the worker: arq app.worker.WorkerSettings
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
