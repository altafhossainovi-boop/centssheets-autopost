#!/bin/zsh
# Copy the values the GitHub workflows need from automation/.env into the
# repository's Actions secrets. Values go straight from the file to gh; nothing is printed.
#   zsh automation/push_secrets.sh
set -e
cd "$(dirname "$0")/.."
for key in FB_PAGE_TOKEN FB_PAGE_ID IG_USER_ID GRAPH_VERSION REELS_START_DATE; do
  value=$(grep "^${key}=" automation/.env | cut -d= -f2-)
  if [ -z "$value" ]; then
    echo "$key is empty in automation/.env" >&2
    exit 1
  fi
  printf '%s' "$value" | gh secret set "$key"
  echo "set $key"
done
