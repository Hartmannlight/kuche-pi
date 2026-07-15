#!/usr/bin/env python3
"""Render the dated "ente" label and submit it through the local zpl-agent."""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ASSET_DIRECTORY = Path("/usr/local/share/kuche-pi-audio/labels")
BACKGROUND = ASSET_DIRECTORY / "opened_am_bg_203.zpl"
TEMPLATE = ASSET_DIRECTORY / "opened_am_print_template_203.zpl"
DATE_TOKEN = b"{{DATUM}}"
DATE_FORMAT = re.compile(r"\d{2}\.\d{2}\Z")
PRINTER_NAME = re.compile(r"[A-Za-z0-9._-]+\Z")
DEFAULT_AGENT_URL = "http://127.0.0.1:8080"
GRAPHIC_ACCEPT_TIMEOUT_SECONDS = 35
LABEL_ACCEPT_TIMEOUT_SECONDS = 15
GRAPHIC_SETTLE_SECONDS = 0.25
CACHE_DIRECTORY = Path("/var/lib/kuche-pi-audio")


def render_parts(background: bytes, template: bytes, label_date: str) -> tuple[bytes, bytes]:
    """Build the cached artwork upload and dated print job."""
    if not DATE_FORMAT.fullmatch(label_date):
        raise ValueError("Datum muss das Format TT.MM haben")
    if template.count(DATE_TOKEN) != 1:
        raise ValueError("Die ZPL-Vorlage muss {{DATUM}} genau einmal enthalten")
    if background.startswith(b"~DGR:"):
        background = b"~DGE:" + background[len(b"~DGR:") :]
    elif not background.startswith(b"~DGE:"):
        raise ValueError("Die Hintergrundgrafik ist kein ZPL-~DG-Objekt")
    graphic_job = background.rstrip(b"\r\n") + b"\r\n"
    label_job = template.replace(DATE_TOKEN, label_date.encode("ascii"))
    return graphic_job, label_job


def render(background: bytes, template: bytes, label_date: str) -> bytes:
    """Return the complete ZPL stream for previews and tests."""
    return b"".join(render_parts(background, template, label_date))


def validate_printer_name(printer: str) -> None:
    if not PRINTER_NAME.fullmatch(printer):
        raise ValueError("Ungültiger Druckername")


def cache_marker(printer: str) -> Path:
    validate_printer_name(printer)
    return CACHE_DIRECTORY / f"{printer}.graphic-sha256"


def write_cache_marker(path: Path, digest: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(digest + "\n", encoding="ascii")
    temporary.replace(path)


def submit_job(agent_url: str, printer: str, payload: bytes, description: str) -> str:
    validate_printer_name(printer)
    endpoint = f"{agent_url.rstrip('/')}/v1/printers/{quote(printer, safe='._-')}/jobs"
    request = Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/zpl",
            "X-ZPL-Origin": "kuche-pi-print-button",
            "X-ZPL-Description": description,
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            if response.status != 202:
                raise OSError(f"zpl-agent antwortete mit HTTP {response.status}")
            body = json.load(response)
    except HTTPError as error:
        raise OSError(f"zpl-agent antwortete mit HTTP {error.code}") from error
    except URLError as error:
        raise OSError(f"zpl-agent ist nicht erreichbar: {error.reason}") from error
    job_id = body.get("data", {}).get("id")
    if not isinstance(job_id, str):
        raise OSError("zpl-agent hat keine Job-ID zurückgegeben")
    return job_id


def wait_for_transport(
    agent_url: str,
    job_id: str,
    description: str,
    timeout_seconds: float,
) -> None:
    endpoint = f"{agent_url.rstrip('/')}/v1/jobs/{quote(job_id, safe='-')}"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            with urlopen(endpoint, timeout=5) as response:
                body = json.load(response)
        except (HTTPError, URLError) as error:
            raise OSError(f"zpl-agent Jobstatus nicht erreichbar: {error}") from error
        job = body.get("data", {})
        state = job.get("state")
        if state == "transport_accepted":
            return
        if state in {"failed", "outcome_unknown"}:
            raise OSError(f"{description} fehlgeschlagen: {job.get('error') or state}")
        if time.monotonic() >= deadline:
            raise OSError(f"{description} wurde nicht rechtzeitig übernommen")
        time.sleep(0.25)


def send_to_printer(
    agent_url: str,
    printer: str,
    graphic_job: bytes,
    label_job: bytes,
    *,
    cache_only: bool = False,
    refresh_cache: bool = False,
) -> None:
    """Keep artwork in printer flash and submit only the small dated label."""
    marker_path = cache_marker(printer)
    graphic_digest = hashlib.sha256(graphic_job).hexdigest()
    try:
        cached_digest = marker_path.read_text(encoding="ascii").strip()
    except OSError:
        cached_digest = ""

    if refresh_cache or cached_digest != graphic_digest:
        graphic_id = submit_job(agent_url, printer, graphic_job, "Grafik-Upload")
        wait_for_transport(
            agent_url,
            graphic_id,
            "Grafik-Upload",
            GRAPHIC_ACCEPT_TIMEOUT_SECONDS,
        )
        # Wait until the LP 2824 Plus has committed the E: flash object before
        # recalling it. The PL2305 can finish its USB transfer slightly sooner.
        time.sleep(GRAPHIC_SETTLE_SECONDS)
        write_cache_marker(marker_path, graphic_digest)

    if cache_only:
        return

    label_id = submit_job(agent_url, printer, label_job, "Tagesetikett")
    wait_for_transport(
        agent_url,
        label_id,
        "Tagesetikett",
        LABEL_ACCEPT_TIMEOUT_SECONDS,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Druckt das Tagesetikett auf dem ZPL-Drucker")
    parser.add_argument("--printer", default="ente", help="zpl-agent-Drucker-ID (Standard: ente)")
    parser.add_argument("--agent-url", default=DEFAULT_AGENT_URL, help="zpl-agent Basis-URL")
    parser.add_argument("--date", default=date.today().strftime("%d.%m"), help="TT.MM; nur für einen Nachdruck")
    parser.add_argument("--dry-run", action="store_true", help="ZPL nur auf stdout ausgeben")
    parser.add_argument("--cache-only", action="store_true", help="Grafik laden, aber nicht drucken")
    parser.add_argument("--refresh-cache", action="store_true", help="Grafik erneut in den Flash laden")
    arguments = parser.parse_args()

    try:
        background = BACKGROUND.read_bytes()
        template = TEMPLATE.read_bytes()
        graphic_job, label_job = render_parts(background, template, arguments.date)
        if arguments.dry_run:
            sys.stdout.buffer.write(graphic_job + label_job)
            return
        send_to_printer(
            arguments.agent_url,
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
