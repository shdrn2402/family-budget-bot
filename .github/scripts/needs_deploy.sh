#!/usr/bin/env bash
# Prints "deploy=true" or "deploy=false" for the commit range BEFORE..AFTER.
# Deploy is skipped only when every changed file is under docs/ or is Markdown.
# Anything unclear (unknown or missing BEFORE, empty diff) means deploy=true.
set -euo pipefail

before="${1:-}"
after="${2:?usage: needs_deploy.sh BEFORE AFTER}"

if [[ -z "$before" || "$before" =~ ^0+$ ]] || ! git cat-file -e "${before}^{commit}" 2>/dev/null; then
  echo "deploy=true"
  exit 0
fi

changed="$(git diff --name-only "$before" "$after")"
if [[ -z "$changed" ]] || grep -qvE '^docs/|\.md$' <<<"$changed"; then
  echo "deploy=true"
else
  echo "deploy=false"
fi
