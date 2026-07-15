#!/usr/bin/env bash
# Install the lightweight kitchen audio control stack on Raspberry Pi OS Bookworm.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sudo ./scripts/install.sh --user USER --card CARD [--device DEVICE]
       [--with-sendspin] [--with-raspotify]

CARD and DEVICE come from `aplay -l`; a typical USB DAC is --card 1 --device 0.
EOF
}

USER_NAME=""
CARD=""
DEVICE="0"
WITH_SENDSPIN=false
WITH_RASPOTIFY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) USER_NAME="$2"; shift 2 ;;
    --card) CARD="$2"; shift 2 ;;
    --device) DEVICE="$2"; shift 2 ;;
    --with-sendspin) WITH_SENDSPIN=true; shift ;;
    --with-raspotify) WITH_RASPOTIFY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

[[ $(id -u) -eq 0 ]] || { echo "Please run via sudo." >&2; exit 1; }
[[ -n "$USER_NAME" && -n "$CARD" ]] || { usage >&2; exit 2; }
id "$USER_NAME" >/dev/null

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

apt-get update
apt-get install -y --no-install-recommends python3 python3-evdev mpv alsa-utils curl sudo

# The Rust agent exclusively owns the printer device. Validate its local API
# instead of requiring the obsolete /dev/zpl/ente alias.
curl -fsS http://127.0.0.1:8080/healthz >/dev/null || {
  echo "ZebraTamer ist nicht erreichbar. Zuerst zpl-agent installieren und starten." >&2
  exit 1
}
curl -fsS http://127.0.0.1:8080/v1/printers | python3 -c '
import json
import sys

printers = json.load(sys.stdin).get("data", [])
if not any(printer.get("id") == "ente" for printer in printers):
    raise SystemExit("ZebraTamer-Drucker-ID ente fehlt")
' || exit 1

groupadd --system --force kuche-audio
usermod -aG input,audio,kuche-audio "$USER_NAME"
install -d -m 0755 /etc/kuche-pi-audio /usr/local/lib/kuche-pi-audio /usr/local/share/kuche-pi-audio/labels
install -d -o "$USER_NAME" -g kuche-audio -m 0750 /var/lib/kuche-pi-audio
install -m 0755 "$ROOT_DIR/bin/audio-buttons-daemon.py" /usr/local/lib/kuche-pi-audio/audio-buttons-daemon.py
install -m 0755 "$ROOT_DIR/bin/print-ente-label.py" /usr/local/lib/kuche-pi-audio/print-ente-label.py
install -m 0755 "$ROOT_DIR/bin/wait-for-usb-audio.sh" /usr/local/lib/kuche-pi-audio/wait-for-usb-audio.sh
install -m 0755 "$ROOT_DIR/bin/audioctl.py" /usr/local/bin/audioctl
install -m 0644 "$ROOT_DIR/config/audio-buttons.json" /etc/kuche-pi-audio/config.json
install -m 0644 "$ROOT_DIR/config/snd-usb-audio.conf" /etc/modprobe.d/kuche-usb-audio.conf
install -m 0644 "$ROOT_DIR/assets/labels/opened_am_bg_203.zpl" /usr/local/share/kuche-pi-audio/labels/opened_am_bg_203.zpl
install -m 0644 "$ROOT_DIR/assets/labels/opened_am_print_template_203.zpl" /usr/local/share/kuche-pi-audio/labels/opened_am_print_template_203.zpl
sed -e "s/@CARD@/$CARD/g" -e "s/@DEVICE@/$DEVICE/g" \
  "$ROOT_DIR/config/asound.conf.template" > /etc/asound.conf
sed "s/@USER@/$USER_NAME/g" "$ROOT_DIR/systemd/audio-buttons.service" \
  > /etc/systemd/system/audio-buttons.service
install -m 0644 "$ROOT_DIR/systemd/99-kuche-pi-audio.rules" /etc/udev/rules.d/99-kuche-pi-audio.rules
install -d -m 0755 /etc/systemd/journald.conf.d /var/log/journal
install -m 0644 "$ROOT_DIR/systemd/journald-kuche-pi.conf" \
  /etc/systemd/journald.conf.d/50-kuche-pi-persistent.conf

# Only the two restart operations used by the daemon are permitted without a
# password. The daemon never gets unrestricted root access.
cat > /etc/sudoers.d/kuche-pi-audio <<EOF
$USER_NAME ALL=(root) NOPASSWD: /bin/systemctl restart sendspin.service, /bin/systemctl restart raspotify.service
EOF
chmod 0440 /etc/sudoers.d/kuche-pi-audio
visudo -cf /etc/sudoers.d/kuche-pi-audio

if $WITH_RASPOTIFY; then
  curl -fsSL https://dtcooper.github.io/raspotify/install.sh | bash
  RASPOTIFY_CONF=/etc/raspotify/conf
  [[ -f "$RASPOTIFY_CONF" ]] || { echo "Raspotify config not found: $RASPOTIFY_CONF" >&2; exit 1; }
  # Fresh Raspotify installations have no custom OPTIONS. Do not silently merge
  # unrelated user options; edit this line later if options are needed.
  if grep -q '^OPTIONS=' "$RASPOTIFY_CONF"; then
    sed -i 's|^OPTIONS=.*|OPTIONS="--device sharedout"|' "$RASPOTIFY_CONF"
  else
    printf '\nOPTIONS="--device sharedout"\n' >> "$RASPOTIFY_CONF"
  fi
  systemctl enable --now raspotify.service
fi

if $WITH_SENDSPIN; then
  curl -fsSL https://raw.githubusercontent.com/Sendspin/sendspin-cli/refs/heads/main/scripts/systemd/install-systemd.sh | bash
  usermod -aG kuche-audio sendspin
  SENDSPIN_HOME="$(getent passwd sendspin | cut -d: -f6)"
  SETTINGS="$SENDSPIN_HOME/.config/sendspin/settings-daemon.json"
  [[ -f "$SETTINGS" ]] || { echo "Sendspin settings not found: $SETTINGS" >&2; exit 1; }
  python3 - "$SETTINGS" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as stream:
    settings = json.load(stream)
settings["hook_start"] = "/usr/local/bin/audioctl remote-start sendspin"
settings["hook_stop"] = "/usr/local/bin/audioctl remote-stop sendspin"
with open(path, "w", encoding="utf-8") as stream:
    json.dump(settings, stream, indent=2)
    stream.write("\n")
PY
  chown sendspin:sendspin "$SETTINGS"
fi

# Apply the USB-audio guard both to newly installed Sendspin and to an existing
# installation when this updater is rerun without --with-sendspin.
if systemctl list-unit-files sendspin.service --no-legend 2>/dev/null | grep -q '^sendspin.service'; then
  install -d -m 0755 /etc/systemd/system/sendspin.service.d
  install -m 0644 "$ROOT_DIR/systemd/sendspin-usb-audio.conf" \
    /etc/systemd/system/sendspin.service.d/20-kuche-pi-usb-audio.conf
fi

udevadm control --reload-rules
systemctl daemon-reload
systemctl restart systemd-journald.service
if systemctl list-unit-files sendspin.service --no-legend 2>/dev/null | grep -q '^sendspin.service'; then
  systemctl restart sendspin.service
fi
systemctl enable audio-buttons.service
systemctl restart audio-buttons.service
echo
echo "Installed or updated. Reboot or reconnect the '$USER_NAME' login after the first installation."
echo "Test audio: speaker-test -D sharedout -c 2"
echo "Service logs: journalctl -u audio-buttons -f"
