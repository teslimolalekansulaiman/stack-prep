#!/usr/bin/env bash
# Runs on the Hetzner box, piped in over SSH by the deploy workflow.
#
# Expects IMAGE, REGISTRY_TOKEN and ACTOR in the environment. Needs no sudo:
# the deploy user is in the docker group, which is the whole reason the setup
# is arranged this way (sudo on that box requires a password, so an unattended
# deploy cannot use it).

set -euo pipefail

cd /opt/score-pilot

if [ ! -f .env.local ]; then
  echo "No /opt/score-pilot/.env.local — see deploy/README.md, one-time setup." >&2
  exit 1
fi

# The token is valid only while the workflow runs and is never written to disk.
echo "$REGISTRY_TOKEN" | docker login ghcr.io -u "$ACTOR" --password-stdin
trap 'docker logout ghcr.io >/dev/null 2>&1 || true' EXIT

compose() {
  IMAGE="$IMAGE" docker compose --env-file .env.local -f compose.yml "$@"
}

echo "==> Pulling $IMAGE"
compose pull api

echo "==> Starting database and cache"
compose up -d postgres redis

echo "==> Applying migrations"
# --no-deps: postgres is already up and healthy; this must not restart it.
compose run --rm --no-deps api python -m app.cli migrate

echo "==> Starting API and worker"
compose up -d

# What is running, recorded where a rollback can find it without the CI log.
echo "$IMAGE" > .deployed-image
date -Is >> .deployed-image

docker image prune -f >/dev/null
echo "==> Done"
