#!/usr/bin/env python3
"""Render and send the dated "ente" ZPL label through the locked zpl-send tool."""

from __future__ import annotations

import argparse
from datetime import date
try:  # fcntl is available on Raspberry Pi OS; guard it for Windows unit tests.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None
import os
from pathlib import Path
import re
import sys


ASSET_DIRECTORY = Path("/usr/local/share/kuche-pi-audio/labels")
BACKGROUND = ASSET_DIRECTORY / "opened_am_bg_203.zpl"
TEMPLATE = ASSET_DIRECTORY / "opened_am_print_template_203.zpl"
DATE_TOKEN = b"{{DATUM}}"
DATE_FORMAT = re.compile(r"\d{2}\.\d{2}\.\d{4}\Z")
PRINTER_NAME = re.compile(r"[A-Za-z0-9._-]+\Z")


def render(background: bytes, template: bytes, label_date: str) -> bytes:
    """Build one reliable printer job: graphic download, then the filled label."""
    if not DATE_FORMAT.fullmatch(label_date):
        raise ValueError("Datum muss das Format TT.MM.JJJJ haben")
    if template.count(DATE_TOKEN) != 1:
        raise ValueError("Die ZPL-Vorlage muss {{DATUM}} genau einmal enthalten")
    return background.rstrip(b"\r\n") + b"\r\n" + template.replace(DATE_TOKEN, label_date.encode("ascii"))


def printer_device(printer: str) -> Path:
    if not PRINTER_NAME.fullmatch(printer):
        raise ValueError("Ungültiger Druckername")
    return Path("/dev/zpl") / printer


def send_to_printer(printer: str, payload: bytes) -> None:
    """Write a complete raw ZPL job while serialising simultaneous F16 presses."""
    if fcntl is None:  # pragma: no cover - only relevant off Linux.
        raise OSError("Raw-ZPL-Druck ist nur unter Linux verfügbar")
    device = printer_device(printer)
    lock_path = Path("/run/lock") / f"kuche-pi-label-{printer}.lock"
    with open(lock_path, "a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        descriptor = os.open(device, os.O_WRONLY | os.O_NOCTTY)
        try:
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written == 0:
                    raise OSError("Drucker hat keine Daten angenommen")
                remaining = remaining[written:]
        finally:
            os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser(description="Druckt das Tagesetikett auf dem ZPL-Drucker")
    parser.add_argument("--printer", default="ente", help="Name unter /dev/zpl (Standard: ente)")
    parser.add_argument("--date", default=date.today().strftime("%d.%m.%Y"), help="TT.MM.JJJJ; nur für einen Nachdruck")
    parser.add_argument("--dry-run", action="store_true", help="ZPL nur auf stdout ausgeben")
    arguments = parser.parse_args()

    try:
        payload = render(BACKGROUND.read_bytes(), TEMPLATE.read_bytes(), arguments.date)
        if arguments.dry_run:
            sys.stdout.buffer.write(payload)
            return
        send_to_printer(arguments.printer, payload)
    except (OSError, ValueError) as error:
        print(f"Etikett wurde nicht gedruckt: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
