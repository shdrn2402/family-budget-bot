#!/usr/bin/env bash
# Secret scan with gitleaks, shared by the pre-commit hook and CI.
#
#   secret_scan.sh staged             scan staged changes (pre-commit hook)
#   secret_scan.sh range BASE HEAD    scan the commits in BASE..HEAD (CI)
#
# Rules: .gitleaks.private.toml when present (public rules + household values;
# gitignored, or written from a CI secret), otherwise .gitleaks.toml (public
# rules only). Findings are always redacted, because CI logs of a public repo
# are public. Exit code 1 means something was found.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

gitleaks="${GITLEAKS_BIN:-gitleaks}"
if ! command -v "$gitleaks" >/dev/null 2>&1; then
  echo "secret_scan: gitleaks is not installed (see README, 'Secret scanning')." >&2
  exit 2
fi

config=".gitleaks.private.toml"
if [[ ! -f "$config" ]]; then
  config=".gitleaks.toml"
  echo "secret_scan: $config only (no .gitleaks.private.toml, household values are not checked)." >&2
fi

common=(--config "$config" --redact --no-banner --verbose)

case "${1:-}" in
  staged)
    exec "$gitleaks" git --pre-commit --staged "${common[@]}" .
    ;;
  range)
    base="${2:-}"
    head="${3:?usage: secret_scan.sh range BASE HEAD}"
    if [[ -z "$base" || "$base" =~ ^0+$ ]] || ! git cat-file -e "${base}^{commit}" 2>/dev/null; then
      # Unknown base (e.g. a new branch): scan the head commit alone.
      log_opts="-1 $head"
    else
      log_opts="$base..$head"
    fi
    exec "$gitleaks" git --log-opts="$log_opts" "${common[@]}" .
    ;;
  *)
    echo "usage: secret_scan.sh staged | range BASE HEAD" >&2
    exit 2
    ;;
esac
