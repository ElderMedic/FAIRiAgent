#!/usr/bin/env python3
"""Render Markdown to a simple multi-page PDF using PyMuPDF (no pandoc)."""

from __future__ import annotations

import argparse
from pathlib import Path

import fitz  # PyMuPDF


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MD to PDF (plain text boxes, for local testing)",
    )
    parser.add_argument("input_md", type=Path)
    parser.add_argument("output_pdf", type=Path)
    parser.add_argument("--chars-per-page", type=int, default=3500)
    args = parser.parse_args()

    text = args.input_md.read_text(encoding="utf-8")
    margin = 50
    width_pt, height_pt = 595, 842
    rect = fitz.Rect(margin, margin, width_pt - margin, height_pt - margin)

    chunks: list[str] = []
    buf: list[str] = []
    n = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if n + line_len > args.chars_per_page and buf:
            chunks.append("\n".join(buf))
            buf = [line]
            n = line_len
        else:
            buf.append(line)
            n += line_len
    if buf:
        chunks.append("\n".join(buf))

    doc = fitz.open()
    for ch in chunks:
        page = doc.new_page(width=width_pt, height=height_pt)
        page.insert_textbox(
            rect,
            ch,
            fontsize=8,
            fontname="helv",
            align=fitz.TEXT_ALIGN_LEFT,
        )
    args.output_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.output_pdf.as_posix())
    doc.close()
    print(f"Wrote {args.output_pdf} ({len(chunks)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
