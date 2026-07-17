#!/usr/bin/env python3
"""Assemble the section fragments into the single, self-contained
`stream1-unified-architecture.html` — the deliverable that opens anywhere
(double-click / file://, local server, or GitHub Pages).

Edit the small source files, then run this to regenerate the output:
  - sections/style.css   shared stylesheet (inlined into <style>)
  - sections/_hero.html  the page hero
  - sections/NN.html      one <section> per concern, in numeric order
Never hand-edit stream1-unified-architecture.html — it is generated."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEC = ROOT / "sections"
OUT = ROOT / "stream1-unified-architecture.html"

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
