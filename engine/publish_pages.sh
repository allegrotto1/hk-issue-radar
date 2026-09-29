#!/bin/bash
# Publish the built static site to GitHub Pages.
# Updates files in place. Does not delete older day or report pages.
set -euo pipefail
SITE=/workspace/radar/site
DEST=/tmp/hk-issue-radar
if [ ! -f "$SITE/index.html" ]; then
  echo "pages: missing $SITE/index.html" >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "pages: gh not logged in" >&2
  exit 1
fi
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" fetch origin main
  git -C "$DEST" reset --hard origin/main
else
  rm -rf "$DEST"
  gh repo clone allegrotto1/hk-issue-radar "$DEST" -- --depth 1
fi
cp -a "$SITE/index.html" "$SITE/404.html" "$SITE/sitemap.xml" "$SITE/favicon.svg" "$DEST/"
mkdir -p "$DEST/assets" "$DEST/tracker"
cp -a "$SITE/assets/site.css" "$DEST/assets/site.css"
if [ -d "$SITE/days" ]; then
  mkdir -p "$DEST/days"
  for d in "$SITE"/days/*; do
    [ -d "$d" ] || continue
    name=$(basename "$d")
    mkdir -p "$DEST/days/$name"
    cp -a "$d/." "$DEST/days/$name/"
  done
fi
if [ -d "$SITE/reports" ]; then
  mkdir -p "$DEST/reports"
  for d in "$SITE"/reports/*; do
    [ -d "$d" ] || continue
    name=$(basename "$d")
    mkdir -p "$DEST/reports/$name"
    cp -a "$d/." "$DEST/reports/$name/"
  done
fi
if [ -d "$SITE/tracker" ]; then
  cp -a "$SITE/tracker/." "$DEST/tracker/"
fi
# Generator lives on the repo so a later hourly run can clone and build
# even when its own workspace has no /workspace/radar.
rm -rf "$DEST/engine"
mkdir -p "$DEST/engine"
tar -C /workspace/radar --exclude site --exclude __pycache__ --exclude '*.pyc' -cf - . | tar -C "$DEST/engine" -xf -
cd "$DEST"
git add -A
if git diff --cached --quiet; then
  echo "pages: nothing new"
  exit 0
fi
stamp=$(TZ=Asia/Hong_Kong date +"%Y-%m-%d %H:%M")
git -c user.email="allegrotto1@users.noreply.github.com" -c user.name="allegrotto1" \
  commit -m "radar: publish ${stamp} HKT"
git push origin HEAD
echo "pages: pushed $(git rev-parse --short HEAD)"
