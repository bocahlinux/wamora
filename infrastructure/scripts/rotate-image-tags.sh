#!/bin/sh
# Phase 14 M6 (rollback / image versioning) — decisions #4/#5.
#
# After a NEW build of <repo> has already been tagged <repo>:<new_tag>
# (e.g. via `IMAGE_TAG=<new_tag> docker compose build`), this shifts
# the current/previous/previous-previous alias chain so the image that
# WAS `current` stays addressable as `previous` (and what was
# `previous` becomes `previous-previous`), then points `current` at the
# new tag. Keeps at least 3 application-image versions rollback-able by
# name at all times (docs/08-DEPLOYMENT.md's "Image versioning and
# rollback" section).
#
# Never deletes or untags anything: an image shifted out of the
# previous-previous slot keeps its own original tag (whatever IMAGE_TAG
# it was built with, e.g. a git short SHA) untouched on disk — only the
# convenience alias chain moves, so nothing addressable becomes a
# dangling <none>:<none> image just from running this script.
#
# Usage: sh infrastructure/scripts/rotate-image-tags.sh <repo> <new_tag>
# Example: sh infrastructure/scripts/rotate-image-tags.sh wamora-backend a1b2c3d
set -eu

repo="${1:?Usage: rotate-image-tags.sh <repo> <new_tag>}"
new_tag="${2:?Usage: rotate-image-tags.sh <repo> <new_tag>}"

if ! docker image inspect "${repo}:${new_tag}" >/dev/null 2>&1; then
    echo "error: ${repo}:${new_tag} does not exist locally — build it first, e.g.:" >&2
    echo "  IMAGE_TAG=${new_tag} docker compose build" >&2
    exit 1
fi

if docker image inspect "${repo}:previous" >/dev/null 2>&1; then
    docker tag "${repo}:previous" "${repo}:previous-previous"
    echo "${repo}: previous -> previous-previous"
fi

if docker image inspect "${repo}:current" >/dev/null 2>&1; then
    docker tag "${repo}:current" "${repo}:previous"
    echo "${repo}: current -> previous"
fi

docker tag "${repo}:${new_tag}" "${repo}:current"
echo "${repo}: current = ${new_tag}"
