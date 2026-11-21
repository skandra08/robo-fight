#!/usr/bin/env bash
# Tag try/<label> for the current commit. Bot.name must contain <label>.
set -euo pipefail

label="${1:-}"
desc="${2:-}"
if [[ -z "$label" || -z "$desc" ]]; then
  echo "usage: $0 <label> <one-line-desc>" >&2
  exit 2
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

name_line="$(grep -E '^\s*name\s*=' bot.py | head -1 || true)"
if [[ "$name_line" != *"$label"* ]]; then
  echo "error: Bot.name must contain '$label'. Current: $name_line" >&2
  exit 1
fi
echo "Bot.name line: $name_line"

tag="try/${label}"
subject="try/${label} — ${desc}"
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  git add -A
  git commit -m "$subject"
fi
git tag -f "$tag" HEAD
echo "tagged $tag -> $(git rev-parse --short HEAD) ($(git rev-parse HEAD))"
