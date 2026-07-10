# Küche Pi: Audio-Tasten, Sendspin und Spotify Connect

Ein schlankes, headless Setup für einen Pi Zero 2 W mit USB-Soundkarte und einer
Tastatur mit F13–F20. Es braucht keine Desktop-Session und hält keine zwei
absichtlich gestarteten Quellen gleichzeitig aktiv.

## Was es macht

| Taste | Aktion |
| --- | --- |
| F13 | Alles stoppen (Button-Player, Sendspin, Spotify Connect) |
| F14 | Neueste **Tagesschau in 100 Sekunden** abspielen |
| F15 | Deutschlandfunk Kultur |
| F16 | Tagesetikett auf dem Drucker **ente** drucken, ohne Audio anzutasten |
| F17 | SWR1 Baden-Württemberg |
| F18 | Querfunk |
| F19 | ROCK ANTENNE |
| F20 | Deutschlandfunk |

Webradios werden nach sechs Stunden automatisch beendet. Die Tagesschau ist
eine einzelne Podcastfolge und läuft deshalb nur bis zum Ende.

Der Dienst verwaltet einen eindeutigen Audio-Besitzer. Ein Button-Stream
stoppt die beiden Remote-Clients vor dem Start. Der Sendspin-Hook meldet einen
Remote-Start zurück, wodurch ein laufendes Radio sofort beendet wird. Spotify
Connect kann auf dem headless Raspotify-Setup nicht zuverlässig bei jedem
externen Play-Ereignis zurückmelden; das ist der ausdrücklich optionale Teil.
Umgekehrt funktioniert der wichtige Fall vollständig: Ein Button stoppt immer
eine laufende Spotify- oder Sendspin-Wiedergabe.

## Voraussetzungen

Getestet ist der Aufbau für **Raspberry Pi OS Bookworm 32 Bit** auf einem Pi
Zero 2 W. Der Pi, Netzwerk und SSH sind bereits eingerichtet. Benötigt werden
eine USB-Soundkarte und die F13–F20-Tastatur.

Die Spotify-Wiedergabe benötigt Spotify Premium. Raspotify unterstützt auf
Debian-basierten Systemen ARMv7, also den Pi Zero 2 W, über sein eigenes
Paket-Repository. Sendspin wird über den offiziellen systemd-Installer
installiert.

## Schnellinstallation

1. Repository auf den Pi holen:

   ```bash
   git clone https://github.com/Hartmannlight/kuche-pi.git
   cd kuche-pi
   ```

2. Der ZPL-Drucker wird **nicht** von diesem Repository eingerichtet. Er muss
   vorher über [pi-init](https://github.com/Hartmannlight/pi-init) installiert
   sein und dort den stabilen Namen **`ente`** erhalten haben. Prüfe nur:

   ```bash
   ls -l /dev/zpl/ente
   sudo -u pi test -w /dev/zpl/ente && echo "pi darf drucken"
   ```

   Der erste Befehl muss auf `/dev/usb/lp0` oder ähnlich zeigen; der zweite
   muss `pi darf drucken` ausgeben. Der Labeldruck verwendet den Alias direkt
   und benötigt kein separates Sender-Script.

3. USB-Soundkarte verbinden und ihre Kartennummer nachsehen:

   ```bash
   aplay -l
   ```

   Beispiel: `card 1: ... device 0` bedeutet `--card 1 --device 0`.

4. Den Audio-Stack installieren. Dieser Befehl installiert neben dem
   Tasten-Dienst auch Sendspin und Raspotify:

   ```bash
   sudo bash ./scripts/install.sh --user pi --card 1 --device 0 --with-sendspin --with-raspotify
   ```

   Ersetze `pi` durch den tatsächlichen Linux-Benutzer und die Kartennummern
   durch die Ausgabe von `aplay -l`. Der Installer lädt nur die zwei genannten
   Upstream-Installer nach: [Sendspin](https://pypi.org/project/sendspin/) und
   [Raspotify](https://github.com/dtcooper/raspotify/blob/master/install.sh).

5. Beim Sendspin-Installer als Audio-Gerät **`default`** wählen. Das vom
   Installer erzeugte `/etc/asound.conf` leitet `default` über `dmix` zur
   USB-Karte. Dadurch können mpv, Sendspin und Raspotify dieselbe Karte sauber
   öffnen.

6. Neu starten, dann Audio, Drucker und Dienst prüfen:

   ```bash
   sudo reboot
   # nach der erneuten SSH-Anmeldung:
   speaker-test -D sharedout -c 2
   /usr/local/lib/kuche-pi-audio/print-ente-label.py --date 10.07
   systemctl status audio-buttons
   journalctl -u audio-buttons -f
   ```

Raspotify erscheint danach als Spotify-Connect-Gerät. Sein Name und weitere
Optionen stehen in `/etc/raspotify/conf`; der Installer setzt dessen Ausgabe
auf `sharedout`.

## Konfliktverhalten

```text
F14–F20 (Radio/Podcast) ──> mpv starten
                               │
                               ├── Sendspin neu starten (Wiedergabe endet)
                               └── Raspotify neu starten (Wiedergabe endet)

Sendspin startet remote ──> Hook: audioctl remote-start sendspin ──> mpv stoppen
F13 ─────────────────────> mpv stoppen + beide Remote-Dienste neu starten
F16 ─────────────────────> ZPL-Job für /dev/zpl/ente starten; keine Audio-Aktion
```

Ein „Restart“ für Sendspin/Raspotify ist bewusst gewählt: Er beendet zuverlässig
eine Wiedergabe, lässt den Client aber direkt wieder als Remote-Ziel verfügbar.
Der Dienst erhält nur für genau diese beiden Befehle ein eng begrenztes
`sudoers`-Recht, kein allgemeines Root-Recht.

## Labeldruck (F16)

Die beiden bereitgestellten ZPL-Dateien sind als Assets enthalten. Bei jedem
Druck lädt F16 zuerst `OPENLBL.GRF` in den Druckerspeicher und sendet danach
das eigentliche Etikett. Dadurch funktioniert ein Druck auch direkt nach dem
Einschalten des Druckers zuverlässig.

`{{DATUM}}` wird automatisch mit dem lokalen Datum des Pi im Format
`TT.MM` ersetzt, etwa `10.07`. Das Druckprogramm akzeptiert kein
freies Datum über F16; dadurch kann kein ungültiger ZPL-Inhalt eingesetzt
werden. Ein bewusstes Nachdrucken lässt sich so ausführen:

```bash
/usr/local/lib/kuche-pi-audio/print-ente-label.py --date 10.07
```

Für eine Druckvorschau ohne Ausgabe an den Drucker:

```bash
/usr/local/lib/kuche-pi-audio/print-ente-label.py --dry-run > label.zpl
```

Der Druckprozess wird bewusst unabhängig vom Audio-Dienst gestartet und
unterbricht nichts. Sollte F16 nicht drucken, prüfe zuerst:

```bash
ls -l /dev/zpl/ente
id pi
sudo -u pi test -w /dev/zpl/ente && echo "Druckerzugriff OK"
```

## Bedienung ohne Tastatur

`audioctl` kommuniziert über einen lokalen Unix-Socket mit dem Dienst:

```bash
audioctl status
audioctl stop
audioctl play dlf
audioctl play tagesschau
audioctl remote-start sendspin
audioctl remote-stop sendspin
audioctl labels
```

Ein zusätzlicher Sendspin-Start- und -Stop-Hook wird bei der optionalen
Sendspin-Installation automatisch in dessen JSON-Konfiguration eingetragen.
Falls Sendspin schon vorhanden war, kontrolliere die beiden Felder in
`~sendspin/.config/sendspin/settings-daemon.json`:

```json
"hook_start": "/usr/local/bin/audioctl remote-start sendspin",
"hook_stop": "/usr/local/bin/audioctl remote-stop sendspin"
```

## Anpassungen

`/etc/kuche-pi-audio/config.json` enthält alle Stream-URLs, den sechs-Stunden-
Timeout und die Stop-Kommandos. Nach einer Änderung:

```bash
sudo systemctl restart audio-buttons
```

Die Standard-URLs für Deutschlandfunk und Deutschlandfunk Kultur stammen aus
deren offiziellen Livestream-Angeboten. Der Tagesschau-Button liest bei jedem
Drücken den offiziellen RSS-Feed, statt eine veraltete MP3-URL fest zu
verdrahten.

Wenn eine andere USB-Karte verwendet wird, Kartennummern mit `aplay -l` erneut
bestimmen, die Werte in `/etc/asound.conf` anpassen und testen:

```bash
speaker-test -D sharedout -c 2
mpv --no-video --ao=alsa --audio-device=alsa/sharedout https://mp3.querfunk.de/qfhi
```

## Wartung und Fehlersuche

```bash
systemctl status audio-buttons sendspin raspotify
journalctl -u audio-buttons -u sendspin -u raspotify -n 100 --no-pager
audioctl status
```

Falls keine Taste reagiert, prüfe zuerst, ob das System sie sieht:

```bash
sudo evtest
```

Der Benutzer des Dienstes muss Mitglied der Gruppen `input`, `audio` und
`kuche-audio` sein. Nach einer Gruppenänderung neu anmelden oder neu starten.

## Entwicklungstest

Der Code verwendet bis auf `python3-evdev` nur die Python-Standardbibliothek.
Der Konfigurationstest läuft auf jedem Rechner mit Python 3.11+:

```bash
python -m unittest discover -s tests -v
```
