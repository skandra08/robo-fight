#!/usr/bin/env bash
# Push a named A/B variant: Bot.name must contain <label>, tag try/<label>, push.
set -euo pipefail

label="${1:-}"
desc="${2:-}"
if [[ -z "$label" || -z "$desc" ]]; then
  echo "usage: $0 <label> <one-line-desc>" >&2
  exit 2
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

bot_py="$root/bot.py"
name_line="$(grep -E '^\s*name\s*=' "$bot_py" | head -1 || true)"
if [[ "$name_line" != *"$label"* ]]; then
  if grep -qE '^\s*name\s*=\s*"lh-' "$bot_py"; then
    sed -i.bak -E "s/^([[:space:]]*name[[:space:]]*=[[:space:]]*\")[^\"]+(\")/\1lh-${label}\2/" "$bot_py"
    rm -f "${bot_py}.bak"
  else
    echo "error: Bot.name must contain '$label'. Current: $name_line" >&2
    exit 1
  fi
fi
name_line="$(grep -E '^\s*name\s*=' "$bot_py" | head -1 || true)"
echo "Bot.name line: $name_line"

tag="try/${label}"
subject="try/${label} — ${desc}"
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  git add -A
  git commit -m "$subject"
fi
git tag -f "$tag" HEAD
echo "tagged $tag -> $(git rev-parse --short HEAD) ($(git rev-parse HEAD))"

branch="$(git branch --show-current)"
if [[ "$branch" == "main" || "$branch" == "master" ]]; then
  echo "error: refusing to push variant from $branch — checkout a try/* feature branch" >&2
  exit 1
fi
git push -u origin "HEAD:refs/heads/${branch}" --force
git push -f origin "refs/tags/${tag}"
echo "pushed commit + $tag"
