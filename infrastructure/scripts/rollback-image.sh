#!/bin/sh
# Phase 14 M6 (rollback / image versioning).
#
# Rolls <repo> back to whatever `previous` currently points at, WITHOUT
# any rebuild — both tags already exist locally, this only moves alias
# tags. Shifts previous-previous forward into the previous slot.
#
# This script only re-points local image tags. It does NOT restart any
# container, does NOT touch the database/migrations, and does NOT
# decide which services to restart or in what order — see
# docs/08-DEPLOYMENT.md's "Image versioning and rollback" section for
# the full procedure (service order, health checks after rollback, and
# the explicit warning that an image rollback does not by itself mean a
# database migration is safe to roll back).
#
# Never deletes anything: if there is no previous-previous to shift
# forward, `previous` is simply left pointing at the same image as the
# new `current` (a harmless duplicate alias) rather than being removed.
#
# Usage: sh infrastructure/scripts/rollback-image.sh <repo>
# Example: sh infrastructure/scripts/rollback-image.sh wamora-backend
set -eu

repo="${1:?Usage: rollback-image.sh <repo>}"

if ! docker image inspect "${repo}:previous" >/dev/null 2>&1; then
    echo "error: ${repo}:previous does not exist locally — nothing to roll back to." >&2
    exit 1
fi

docker tag "${repo}:previous" "${repo}:current"
echo "${repo}: current now points at what was 'previous'."

if docker image inspect "${repo}:previous-previous" >/dev/null 2>&1; then
    docker tag "${repo}:previous-previous" "${repo}:previous"
    echo "${repo}: previous now points at what was 'previous-previous'."
else
    echo "${repo}: no previous-previous recorded yet — 'previous' now points at the same image as 'current' (nothing was deleted)."
fi

echo ""
echo "Next: restart the affected service(s) with IMAGE_TAG=current, e.g.:"
echo "  IMAGE_TAG=current docker compose up -d --no-build <service>"
