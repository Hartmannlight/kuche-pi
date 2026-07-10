#!/usr/bin/env python3
"""Render and send the dated "ente" ZPL label through the locked printer device."""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
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
    """Build the cached artwork upload and dated print job."""
    if not DATE_FORMAT.fullmatch(label_date):
        raise ValueError("Datum muss das Format TT.MM haben")
    if template.count(DATE_TOKEN) != 1:
        raise ValueError("Die ZPL-Vorlage muss {{DATUM}} genau einmal enthalten")
    graphic_job = background.rstrip(b"\r\n") + b"\r\n"
    label_job = template.replace(DATE_TOKEN, label_date.encode("ascii"))
    return graphic_job, label_job


def render(background: bytes, template: bytes, label_date: str) -> bytes:
    """Return the complete ZPL stream for previews and tests."""
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


def cache_marker(printer: str) -> Path:
    return Path("/run/lock") / f"kuche-pi-label-{printer}.graphic-sha256"


def send_to_printer(
    printer: str,
    graphic_job: bytes,
    label_job: bytes,
    *,
    cache_only: bool = False,
    refresh_cache: bool = False,
) -> None:
    """Cache the artwork when necessary, then overlay and print the date."""
    if fcntl is None:  # pragma: no cover - only relevant off Linux.
        raise OSError("Raw-ZPL-Druck ist nur unter Linux verfügbar")
    device = printer_device(printer)
    lock_path = Path("/run/lock") / f"kuche-pi-label-{printer}.lock"
    marker_path = cache_marker(printer)
    graphic_digest = hashlib.sha256(graphic_job).hexdigest()
    with open(lock_path, "a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        cached_digest = ""
        try:
            cached_digest = marker_path.read_text(encoding="ascii").strip()
        except OSError:
            pass
        if refresh_cache or cached_digest != graphic_digest:
            write_job(device, graphic_job)
            time.sleep(0.25)
            marker_path.write_text(graphic_digest + "\n", encoding="ascii")
        if cache_only:
            return
        write_job(device, label_job)


def main() -> None:
    parser = argparse.ArgumentParser(description="Druckt das Tagesetikett auf dem ZPL-Drucker")
    parser.add_argument("--printer", default="ente", help="Name unter /dev/zpl (Standard: ente)")
    parser.add_argument("--date", default=date.today().strftime("%d.%m"), help="TT.MM; nur für einen Nachdruck")
    parser.add_argument("--dry-run", action="store_true", help="ZPL nur auf stdout ausgeben")
    parser.add_argument("--cache-only", action="store_true", help="Hintergrund laden, aber kein Etikett drucken")
    parser.add_argument("--refresh-cache", action="store_true", help="Hintergrund erneut in den Drucker laden")
    arguments = parser.parse_args()

    try:
        background = BACKGROUND.read_bytes()
        template = TEMPLATE.read_bytes()
        graphic_job, label_job = render_parts(background, template, arguments.date)
        if arguments.dry_run:
            sys.stdout.buffer.write(graphic_job + label_job)
            return
        send_to_printer(
            arguments.printer,
            graphic_job,
            label_job,
            cache_only=arguments.cache_only,
            refresh_cache=arguments.refresh_cache,
        )
    except (OSError, ValueError) as error:
        print(f"Etikett wurde nicht gedruckt: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
