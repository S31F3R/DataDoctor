#!/bin/bash
# Replace a Data Doctor AppImage after the app has exited.
#
# Usage:
#   applyAppImageUpdate.sh --current /path/DataDoctor.AppImage --new /path/Update/new.AppImage [--wait-pid PID]
#
# Typical flow (handled by the app):
#   1) App downloads new AppImage into Update/ next to the current AppImage
#   2) App starts this script with --wait-pid $$ and quits
#   3) This script waits for the PID, backs up the old AppImage, moves the new one into place
#
# Manual:
#   1) Close Data Doctor
#   2) ./applyAppImageUpdate.sh --current ./DataDoctor.AppImage --new ./Update/DataDoctor-x86_64.AppImage

set -e
CURRENT=""
NEW=""
WAIT_PID=""

while [ $# -gt 0 ]; do
  case "$1" in
    --current) CURRENT="$2"; shift 2 ;;
    --new) NEW="$2"; shift 2 ;;
    --wait-pid) WAIT_PID="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,16p' "$0"
      exit 0
      ;;
    *) shift ;;
  esac
done

if [ -z "$CURRENT" ] || [ -z "$NEW" ]; then
  echo "Usage: $0 --current /path/DataDoctor.AppImage --new /path/Update/new.AppImage [--wait-pid PID]" >&2
  exit 1
fi

if [ ! -f "$NEW" ]; then
  echo "ERROR: new AppImage not found: $NEW" >&2
  exit 1
fi

if [ -n "$WAIT_PID" ]; then
  for i in $(seq 1 600); do
    if ! kill -0 "$WAIT_PID" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  sleep 1
fi

chmod +x "$NEW" 2>/dev/null || true

if [ -f "$CURRENT" ]; then
  BAK="${CURRENT}.bak"
  rm -f "$BAK"
  mv "$CURRENT" "$BAK" || true
fi

mv "$NEW" "$CURRENT"
chmod +x "$CURRENT" 2>/dev/null || true

UPD_DIR="$(dirname "$CURRENT")/Update"
rm -f "$UPD_DIR/pending.json" 2>/dev/null || true

echo "AppImage updated: $CURRENT"
echo "Previous copy (if any): ${CURRENT}.bak"
