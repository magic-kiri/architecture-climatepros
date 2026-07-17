#!/usr/bin/env python3
"""Assemble sections/ fragments into the single self-contained
stream1-unified-architecture.html. Edit the fragments, never the output.

Order: _head.html (ends with <style>) + _style.css + _body-open.html
(</style>...</head><body><div class="wrap"> + hero) + NN.html sections in
numeric order. Each part is concatenated raw, so section fragments are the
plain <section id="sN">...</section> blocks."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEC = ROOT / "sections"
OUT = ROOT / "stream1-unified-architecture.html"

parts = [
    (SEC / "_head.html").read_text(encoding="utf-8"),
    (SEC / "_style.css").read_text(encoding="utf-8"),
    (SEC / "_body-open.html").read_text(encoding="utf-8"),
]
for f in sorted(SEC.glob("[0-9][0-9].html")):
    parts.append(f.read_text(encoding="utf-8"))

OUT.write_text("".join(parts), encoding="utf-8")
print(f"built {OUT.name} from {len(list(SEC.glob('[0-9][0-9].html')))} sections")
