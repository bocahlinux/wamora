#!/bin/sh
# Phase 14 M6 (rollback / image versioning) — decision #3.
#
# Prints the IMAGE_TAG a deploy should use: the current git commit's
# short SHA if this checkout is a git repository with a resolvable
# HEAD, otherwise the literal string "local" (the same safe fallback
# infrastructure/{office,tencent}/docker-compose.yml's own
# `${IMAGE_TAG:-local}` default already uses). This never guesses a
# production-specific value — it only ever reads whatever git commit
# is actually checked out, or falls back to a fixed, non-production
# placeholder.
#
# Usage:
#   IMAGE_TAG="$(sh infrastructure/scripts/compute-image-tag.sh)"
#   export IMAGE_TAG
set -eu

if git rev-parse --short HEAD >/dev/null 2>&1; then
    git rev-parse --short HEAD
else
    echo local
fi
