#!/usr/bin/env bash
# Avoid starting Sendspin's expensive audio discovery until the configured USB
# card is present. The service can remain in activating state without a busy
# restart loop while the hub or DAC is disconnected.
set -euo pipefail

CARD_ID="${1:-Device}"
TIMEOUT_SECONDS="${2:-300}"
CARDS_PATH="${ASOUND_CARDS_PATH:-/proc/asound/cards}"
ELAPSED=0

while ! grep -Eq "^[[:space:]]*[0-9]+[[:space:]]+\\[${CARD_ID}[[:space:]]*\\]:" "$CARDS_PATH"; do
  if (( ELAPSED >= TIMEOUT_SECONDS )); then
    echo "ALSA card '${CARD_ID}' did not appear within ${TIMEOUT_SECONDS} seconds" >&2
    exit 1
  fi
  sleep 2
  (( ELAPSED += 2 ))
done
