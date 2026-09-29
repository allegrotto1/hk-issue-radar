#!/bin/bash
# Rebuild the Pages site from engine/data/reports and copy it into a checkout.
# Does not delete older report or day pages. Repo root is the first argument.
set -euo pipefail
REPO=${1:-.}
REPO=$(cd "$REPO" && pwd)
ENGINE="$REPO/engine"
SITE=$(mktemp -d)
python3 "$ENGINE/build.py" --strict --out "$SITE"
mkdir -p "$SITE/tracker"
cp -a "$ENGINE/tracker/index.html" "$ENGINE/tracker/tracker.css" "$ENGINE/tracker/data.json" "$SITE/tracker/"
cp -a "$SITE/index.html" "$SITE/404.html" "$SITE/sitemap.xml" "$SITE/favicon.svg" "$REPO/"
mkdir -p "$REPO/assets" "$REPO/days" "$REPO/reports" "$REPO/tracker"
cp -a "$SITE/assets/site.css" "$REPO/assets/site.css"
if [ -d "$SITE/days" ]; then
  for d in "$SITE"/days/*; do
    [ -d "$d" ] || continue
    name=$(basename "$d")
    mkdir -p "$REPO/days/$name"
    cp -a "$d/." "$REPO/days/$name/"
  done
fi
for d in "$SITE"/reports/*; do
  [ -d "$d" ] || continue
  name=$(basename "$d")
  mkdir -p "$REPO/reports/$name"
  cp -a "$d/." "$REPO/reports/$name/"
done
cp -a "$SITE/tracker/." "$REPO/tracker/"
rm -rf "$SITE"
echo "republish: rebuilt into $REPO"
