#!/usr/bin/env python3
"""Convert the date-free label artwork to a 320x240 ZPL II graphic."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageOps


WIDTH = 320
HEIGHT = 240
BYTES_PER_ROW = WIDTH // 8


def encode_graphic(source: Path, preview: Path | None = None) -> bytes:
    image = Image.open(source).convert("L")
    image = ImageOps.fit(image, (WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    image = image.point(lambda value: 255 if value >= 190 else 0, mode="1")

    if preview is not None:
        image.save(preview)

    rows: list[str] = []
    pixels = image.load()
    for y in range(HEIGHT):
        row = bytearray(BYTES_PER_ROW)
        for x in range(WIDTH):
            if pixels[x, y] == 0:
                row[x // 8] |= 1 << (7 - (x % 8))
        rows.append(row.hex().upper())

    size = BYTES_PER_ROW * HEIGHT
    return f"~DGE:OPENLBL.GRF,{size},{BYTES_PER_ROW},".encode("ascii") + "".join(rows).encode("ascii") + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--preview", type=Path)
    arguments = parser.parse_args()
    arguments.output.write_bytes(encode_graphic(arguments.source, arguments.preview))


if __name__ == "__main__":
    main()
