#!/usr/bin/env python3
"""One-time: split the monolithic stream1-unified-architecture.html into
sections/ fragments. Ranges are exact substrings covering the whole file with
no gaps, so build.py concatenation reproduces the original byte-for-byte."""
import re, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "stream1-unified-architecture.html"
OUT = ROOT / "sections"
OUT.mkdir(exist_ok=True)

text = SRC.read_text(encoding="utf-8")

a = text.index("<style>") + len("<style>")   # head keeps the literal <style>
b = text.index("</style>")                    # css = text[a:b]
c = text.index('<section id="s1">')           # body-open = text[b:c]

(OUT / "_head.html").write_text(text[:a], encoding="utf-8")
(OUT / "_style.css").write_text(text[a:b], encoding="utf-8")
(OUT / "_body-open.html").write_text(text[b:c], encoding="utf-8")

opens = [m.start() for m in re.finditer(r'<section id="s\d+">', text)]
opens.append(len(text))
for k in range(len(opens) - 1):
    seg = text[opens[k]:opens[k + 1]]
    n = re.search(r'<section id="s(\d+)"', seg).group(1)
    (OUT / f"{int(n):02d}.html").write_text(seg, encoding="utf-8")

print(f"wrote {len(opens)-1} section fragments + _head/_style/_body-open to {OUT}")
