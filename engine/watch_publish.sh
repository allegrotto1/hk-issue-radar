#!/bin/bash
# Backup: if the public homepage is missing this hour's edition but the
# report JSON is already on GitHub, rebuild and push. Checks every 5 minutes
# from 09:00 through 19:59 HKT.
set -u
REPO=allegrotto1/hk-issue-radar
while true; do
  hour=$(TZ=Asia/Hong_Kong date +%H)
  day=$(TZ=Asia/Hong_Kong date +%F)
  if [ "$hour" -lt 9 ] || [ "$hour" -gt 19 ]; then
    sleep 300
    continue
  fi
  label="${hour}:00"
  home=$(curl -fsS --max-time 20 "https://allegrotto1.github.io/hk-issue-radar/?t=$(date +%s)" || true)
  if printf '%s' "$home" | grep -q "$label"; then
    echo "watch: $day $label already on the homepage"
    sleep 300
    continue
  fi
  dest="/workspace/radar/data/reports/${day}-${hour}.json"
  if [ ! -f "$dest" ]; then
    if gh api "repos/${REPO}/contents/engine/data/reports/${day}-${hour}.json" --jq .content 2>/dev/null \
      | base64 -d > "$dest.tmp" && [ -s "$dest.tmp" ]; then
      mv "$dest.tmp" "$dest"
      echo "watch: downloaded ${day}-${hour}.json"
    else
      rm -f "$dest.tmp"
      echo "watch: $label missing and no JSON yet"
      sleep 300
      continue
    fi
  fi
  if python3 /workspace/radar/build.py --strict --out /workspace/radar/site \
    && mkdir -p /workspace/radar/site/tracker \
    && cp /workspace/radar/tracker/index.html /workspace/radar/tracker/tracker.css /workspace/radar/tracker/data.json /workspace/radar/site/tracker/ \
    && bash /workspace/radar/publish_pages.sh; then
    echo "watch: published $label"
  else
    echo "watch: publish failed for $label"
  fi
  sleep 300
done
