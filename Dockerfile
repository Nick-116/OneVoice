# syntax=docker/dockerfile:1.7
# One Dockerfile, three runtime targets:
#   public  - public caption site + read-only API (no admin code paths reachable, no DB creds)
#   admin   - admin dashboard + API
#   service - ingest, worker and migrations (no frontend assets)

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG NODE_IMAGE=node:22-alpine

# ---------------------------------------------------------------- frontends
FROM ${NODE_IMAGE} AS public-build
WORKDIR /src
COPY public-web/package.json public-web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY public-web/ ./
RUN npm run build

FROM ${NODE_IMAGE} AS admin-build
WORKDIR /src
COPY admin-web/package.json admin-web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY admin-web/ ./
RUN npm run build

# ---------------------------------------------------------------- python base
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/captions ./captions
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
COPY VERSION ./
ARG APP_COMMIT=unknown
ARG APP_BUILT_AT=
ENV APP_COMMIT=${APP_COMMIT} APP_BUILT_AT=${APP_BUILT_AT}
RUN mkdir -p /app/branding && chown -R root:root /app && chmod -R a+rX /app
USER 10001:10001

FROM base AS service
CMD ["python", "-m", "captions.worker"]

FROM base AS public
COPY --from=public-build /src/dist /app/static
ENV COMPONENT=public STATIC_DIR=/app/static
EXPOSE 8080
CMD ["uvicorn", "captions.public.app:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header", "--no-access-log", "--timeout-graceful-shutdown", "5"]

FROM base AS admin
COPY --from=admin-build /src/dist /app/static
ENV COMPONENT=admin STATIC_DIR=/app/static
EXPOSE 8081
CMD ["uvicorn", "captions.admin.app:app", "--host", "0.0.0.0", "--port", "8081", "--no-server-header", "--timeout-graceful-shutdown", "5"]
