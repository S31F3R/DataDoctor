#!/bin/bash
# Replace a Data Doctor AppImage after the app has exited.
# In-app updates write this to /tmp and pass --current from $APPIMAGE
# (the name the user launched, including a rename).
#
# Usage:
#   applyAppImageUpdate.sh --current /path/MyDoctor.AppImage --new /path/new.AppImage [--wait-pid PID] [--log PATH]

CURRENT=""
NEW=""
WAIT_PID=""
LOG=""

while [ $# -gt 0 ]; do
  case "$1" in
    --current) CURRENT="$2"; shift 2 ;;
    --new) NEW="$2"; shift 2 ;;
    --wait-pid) WAIT_PID="$2"; shift 2 ;;
    --log) LOG="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *) shift ;;
  esac
done

log() {
  echo "$(date -Iseconds 2>/dev/null || date) $*"
}
fail() {
  log "ERROR: $*"
  exit 1
}

if [ -n "$LOG" ]; then
  mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
  exec >>"$LOG" 2>&1
fi

if [ -z "$CURRENT" ] || [ -z "$NEW" ]; then
  fail "Usage: $0 --current /path/AppImage --new /path/new.AppImage [--wait-pid PID]"
fi

log "apply: current=$CURRENT new=$NEW wait=$WAIT_PID"

if [ ! -f "$NEW" ]; then
  fail "new AppImage not found: $NEW"
fi

if [ -n "$WAIT_PID" ]; then
  for i in $(seq 1 600); do
    if ! kill -0 "$WAIT_PID" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  sleep 2
  if kill -0 "$WAIT_PID" 2>/dev/null; then
    fail "process $WAIT_PID still running; not replacing AppImage"
  fi
fi

magic=$(od -An -N4 -tx1 "$NEW" 2>/dev/null | tr -d ' \n')
case "$magic" in
  7f454c46*|2321*) ;;
  *)
    fail "new file is not an ELF/AppImage: $NEW"
    ;;
esac

chmod +x "$NEW" 2>/dev/null || true
HERE="$(dirname "$CURRENT")"
TMPBAK="/tmp/datadoctor-old-$$.AppImage"
rm -f "$TMPBAK" "${CURRENT}.bak"
MOVED=0
for i in $(seq 1 60); do
  if [ ! -e "$CURRENT" ]; then
    MOVED=1
    break
  fi
  if mv "$CURRENT" "$TMPBAK" 2>/dev/null; then
    MOVED=1
    break
  fi
  log "waiting to replace (file busy) $i"
  sleep 1
done
if [ "$MOVED" != 1 ]; then
  fail "could not move current AppImage aside (still in use?): $CURRENT"
fi
if ! mv "$NEW" "$CURRENT"; then
  log "restore previous AppImage"
  mv "$TMPBAK" "$CURRENT" 2>/dev/null || true
  fail "could not move new AppImage into place"
fi
chmod +x "$CURRENT" 2>/dev/null || true
rm -f "$TMPBAK"

rm -f "$HERE/applyAppImageUpdate.sh" "$HERE/applyAppImageUpdate" "${CURRENT}.bak"
rm -rf "$HERE/updates" "$HERE/Update"
NEW_DIR="$(dirname "$NEW")"
rm -f "$NEW_DIR/pending.json" "$NEW_DIR/README.txt"

log "AppImage updated: $CURRENT"

if [ -x "$CURRENT" ]; then
  nohup "$CURRENT" >/dev/null 2>&1 &
  log "Relaunched pid $!"
fi

rm -f "$0"
