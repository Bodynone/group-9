# syntax=docker/dockerfile:1

FROM python:3.13-slim AS backend-build
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /usr/local/bin/
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
COPY backend/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim AS backend
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/app/backend/data/grading.sqlite3
WORKDIR /app/backend
COPY --from=backend-build /app/backend/.venv ./.venv
RUN mkdir -p /app/backend/data
EXPOSE 8000
CMD ["uvicorn", "backend.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-graceful-shutdown", "30"]

FROM node:22-slim AS frontend-deps
WORKDIR /app/frontend
RUN npm install --global pnpm@11.28.5
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM frontend-deps AS frontend-build
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=$BACKEND_URL NEXT_TELEMETRY_DISABLED=1
COPY frontend ./
RUN pnpm build

FROM node:22-slim AS frontend
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
WORKDIR /app/frontend
COPY --from=frontend-build --chown=node:node /app/frontend/.next/standalone ./
COPY --from=frontend-build --chown=node:node /app/frontend/.next/static ./.next/static
COPY --from=frontend-build --chown=node:node /app/frontend/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
