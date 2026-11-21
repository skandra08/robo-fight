#!/usr/bin/env bash
# Tag try/<label> for the current commit. levers.LABEL / Bot.name must match <label>.
set -euo pipefail

label="${1:-}"
desc="${2:-}"
if [[ -z "$label" || -z "$desc" ]]; then
  echo "usage: $0 <label> <one-line-desc>" >&2
  exit 2
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

rm -f __pycache__/levers*.pyc 2>/dev/null || true
lev_label="$(grep -E '^LABEL\s*=' levers.py | head -1 | sed -E 's/^LABEL[[:space:]]*=[[:space:]]*\"([^\"]+)\".*/\1/')"
if [[ "$lev_label" != "$label" ]]; then
  echo "error: levers.LABEL='$lev_label' != '$label'" >&2
  exit 1
fi
name_line="$(grep -E '^\s*name\s*=' bot.py | head -1 || true)"
echo "levers.LABEL=$lev_label  Bot.name line: $name_line"

tag="try/${label}"
subject="try/${label} — ${desc}"
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  git add -A
  git commit -m "$subject"
fi
git tag -f "$tag" HEAD
echo "tagged $tag -> $(git rev-parse --short HEAD) ($(git rev-parse HEAD))"
