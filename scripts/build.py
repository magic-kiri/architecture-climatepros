#!/usr/bin/env python3
"""OPTIONAL bundler. The primary deliverable is the short loader shell
`stream1-unified-architecture.html`, which renders sections/*.html at runtime
(needs an http server). Run this only when you want a SINGLE self-contained
file that also opens via file:// (double-click) — e.g. offline sharing.

Output: stream1-unified-architecture.bundle.html — inlines the stylesheet, the
nav, the hero, and every section fragment in document order. Edit the small
source files, never the bundle:
  - sections/style.css   shared stylesheet (inlined into <style>)
  - sections/_nav.html   fixed navigation sidebar (+ its scrollspy script)
  - sections/_hero.html  the page hero
  - sections/NN.html      one <section> per concern, in numeric order"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEC = ROOT / "sections"
OUT = ROOT / "stream1-unified-architecture.bundle.html"

style = (SEC / "style.css").read_text(encoding="utf-8")
nav = (SEC / "_nav.html").read_text(encoding="utf-8")
hero = (SEC / "_hero.html").read_text(encoding="utf-8")
sections = [f.read_text(encoding="utf-8") for f in sorted(SEC.glob("[0-9][0-9].html"))]

html = (
    "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
    "<meta charset=\"UTF-8\">\n"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
    "<title>ClimatePros · Stream 1 — Unified Architecture</title>\n"
    "<style>\n" + style + "</style>\n</head>\n<body>\n"
    + nav + "<div class=\"wrap\">\n"
    + hero + "\n" + "\n".join(sections) + "\n</div>\n</body>\n</html>\n"
)
OUT.write_text(html, encoding="utf-8")
print(f"built {OUT.name} from {len(sections)} sections ({len(html):,} bytes)")
