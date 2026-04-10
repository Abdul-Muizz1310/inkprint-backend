#!/usr/bin/env bash
set -euo pipefail

# Push required secrets to GitHub Actions for this repo.
# Run from the repo root after filling .env in the workspace.

REPO="Abdul-Muizz1310/inkprint-backend"
ENV_FILE="${1:-../../.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found. Pass the path to .env as the first argument."
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

echo "Setting secrets on $REPO..."

gh secret set RENDER_DEPLOY_HOOK   --repo "$REPO" --body "${RENDER_DEPLOY_HOOK_INKPRINT:-}"
gh secret set DATABASE_URL         --repo "$REPO" --body "${NEON_DB_URL_INKPRINT:-}"

echo "Done."
