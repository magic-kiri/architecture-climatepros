#!/usr/bin/env python3
"""OPTIONAL bundler. The primary deliverable is the thin loader shell
`stream1-unified-architecture.html`, which loads sections/*.html at runtime
(needs an http server). Run this only when you want a SINGLE self-contained
file that also opens via file:// — e.g. for offline sharing.

Output: stream1-unified-architecture.bundle.html (inlines style.css + hero +
every section fragment in document order). Edit the fragments, never the bundle."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEC = ROOT / "sections"
OUT = ROOT / "stream1-unified-architecture.bundle.html"

style = (SEC / "style.css").read_text(encoding="utf-8")
hero = (SEC / "_hero.html").read_text(encoding="utf-8")
sections = [f.read_text(encoding="utf-8") for f in sorted(SEC.glob("[0-9][0-9].html"))]

html = (
    "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
    "<meta charset=\"UTF-8\">\n"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
    "<title>ClimatePros · Stream 1 — Unified Architecture</title>\n"
    "<style>\n" + style + "</style>\n</head>\n<body>\n<div class=\"wrap\">\n"
    + hero + "\n" + "\n".join(sections) + "\n</div>\n</body>\n</html>\n"
)
OUT.write_text(html, encoding="utf-8")
print(f"bundled {len(sections)} sections -> {OUT.name} ({len(html):,} bytes)")
