#!/bin/bash
# Replace a Data Doctor AppImage after the app has exited.
# In-app updates write this to /tmp and pass --current from $APPIMAGE
# (the name the user launched, including a rename).
#
# Usage:
#   applyAppImageUpdate.sh --current /path/MyDoctor.AppImage --new /path/new.AppImage [--wait-pid PID]

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
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *) shift ;;
  esac
done

if [ -z "$CURRENT" ] || [ -z "$NEW" ]; then
  echo "Usage: $0 --current /path/AppImage --new /path/new.AppImage [--wait-pid PID]" >&2
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
  if kill -0 "$WAIT_PID" 2>/dev/null; then
    echo "ERROR: process $WAIT_PID still running; not replacing AppImage" >&2
    exit 1
  fi
fi

magic=$(od -An -N4 -tx1 "$NEW" 2>/dev/null | tr -d ' \n')
case "$magic" in
  7f454c46*|2321*) ;;
  *)
    echo "ERROR: new file is not an ELF/AppImage: $NEW" >&2
    exit 1
    ;;
esac

chmod +x "$NEW" 2>/dev/null || true
HERE="$(dirname "$CURRENT")"
rm -f "${CURRENT}.bak"
if [ -f "$CURRENT" ]; then
  rm -f "$CURRENT"
fi
mv "$NEW" "$CURRENT"
chmod +x "$CURRENT" 2>/dev/null || true

rm -f "$HERE/applyAppImageUpdate.sh" "$HERE/applyAppImageUpdate"
rm -f "$HERE/updates/pending.json" "$HERE/updates/README.txt"
rm -f "$HERE/Update/pending.json" "$HERE/Update/README.txt"
rmdir "$HERE/updates" 2>/dev/null || true
rmdir "$HERE/Update" 2>/dev/null || true
NEW_DIR="$(dirname "$NEW")"
rm -f "$NEW_DIR/pending.json" "$NEW_DIR/README.txt"

echo "AppImage updated: $CURRENT"

if [ -x "$CURRENT" ]; then
  nohup "$CURRENT" >/dev/null 2>&1 &
  echo "Relaunched: $CURRENT"
fi

case "$0" in
  /tmp/datadoctor-apply-*) rm -f "$0" ;;
esac
