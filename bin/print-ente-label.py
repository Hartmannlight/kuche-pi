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
import time


ASSET_DIRECTORY = Path("/usr/local/share/kuche-pi-audio/labels")
BACKGROUND = ASSET_DIRECTORY / "opened_am_bg_203.zpl"
TEMPLATE = ASSET_DIRECTORY / "opened_am_print_template_203.zpl"
DATE_TOKEN = b"{{DATUM}}"
DATE_FORMAT = re.compile(r"\d{2}\.\d{2}\Z")
PRINTER_NAME = re.compile(r"[A-Za-z0-9._-]+\Z")


def render_parts(background: bytes, template: bytes, label_date: str) -> tuple[bytes, bytes]:
    """Build the graphic upload and the label as separate raw printer jobs."""
    if not DATE_FORMAT.fullmatch(label_date):
        raise ValueError("Datum muss das Format TT.MM haben")
    if template.count(DATE_TOKEN) != 1:
        raise ValueError("Die ZPL-Vorlage muss {{DATUM}} genau einmal enthalten")
    return background.rstrip(b"\r\n") + b"\r\n", template.replace(DATE_TOKEN, label_date.encode("ascii"))


def render(background: bytes, template: bytes, label_date: str) -> bytes:
    """Return a combined job for previews and tests."""
    return b"".join(render_parts(background, template, label_date))


def printer_device(printer: str) -> Path:
    if not PRINTER_NAME.fullmatch(printer):
        raise ValueError("Ungültiger Druckername")
    return Path("/dev/zpl") / printer


def write_job(device: Path, payload: bytes) -> None:
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


def send_to_printer(printer: str, graphic_job: bytes, label_job: bytes) -> None:
    """Upload the graphic, then print after the printer has stored it."""
    if fcntl is None:  # pragma: no cover - only relevant off Linux.
        raise OSError("Raw-ZPL-Druck ist nur unter Linux verfügbar")
    device = printer_device(printer)
    lock_path = Path("/run/lock") / f"kuche-pi-label-{printer}.lock"
    with open(lock_path, "a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        write_job(device, graphic_job)
        # USB-to-parallel adapters return from write before the printer has
        # necessarily committed a ~DG graphic to RAM.
        time.sleep(0.25)
        write_job(device, label_job)


def main() -> None:
    parser = argparse.ArgumentParser(description="Druckt das Tagesetikett auf dem ZPL-Drucker")
    parser.add_argument("--printer", default="ente", help="Name unter /dev/zpl (Standard: ente)")
    parser.add_argument("--date", default=date.today().strftime("%d.%m"), help="TT.MM; nur für einen Nachdruck")
    parser.add_argument("--dry-run", action="store_true", help="ZPL nur auf stdout ausgeben")
    arguments = parser.parse_args()

    try:
        background = BACKGROUND.read_bytes()
        template = TEMPLATE.read_bytes()
        graphic_job, label_job = render_parts(background, template, arguments.date)
        if arguments.dry_run:
            sys.stdout.buffer.write(graphic_job + label_job)
            return
        send_to_printer(arguments.printer, graphic_job, label_job)
    except (OSError, ValueError) as error:
        print(f"Etikett wurde nicht gedruckt: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
