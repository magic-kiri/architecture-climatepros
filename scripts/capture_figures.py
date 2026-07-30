#!/usr/bin/env python3
"""Rasterise the seven Stream-1 diagrams out of the live design set into
assets/figures/figN.png, ready for the Word document.

Two rendering paths, because the diagrams are built two ways:
  * pure inline <svg>  (§2a unified, §2b B&C)  -> cairosvg
  * HTML + CSS cards   (§2b A, §5 flows)       -> WeasyPrint -> PDF -> pdftoppm
  * figure 4                                   -> redrawn: diagram_dispatch_loop.py

Run:  python3 scripts/capture_figures.py
Then: python3 scripts/build_docx.py   (embeds whatever it finds in assets/figures)

Deps: pip install cairosvg weasyprint  ·  poppler-utils (pdftoppm) · ImageMagick (convert)
"""
import html
import json
import pathlib
import re
import shutil
import subprocess
import sys

from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECTIONS = ROOT / 'sections'
OUT_DIR = ROOT / 'assets' / 'figures'
TMP = pathlib.Path('/tmp/figcapture')

EMOJI = re.compile('[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF'
                   '\U00002B00-\U00002BFF️]')
KEEP = set('✓✔✗✘×•')
FONT_STACK = "'Carlito','Segoe UI','DejaVu Sans',sans-serif"

# figure number -> (kind, source file, selector, nth, render width px / svg scale)
FIGURES = {
    1: ('svg', 'diagram-2a.html', None, 0, 2.2),
    2: ('html', 'diagram-2b-a.html', 'div.uca-diagram', 0, 1700),
    3: ('svg', 'diagram-2b-b.html', None, 0, 2.2),
    # figure 4 is redrawn for print rather than captured — the web card is a tall
    # single column that can only be shrunk to ~4.5in in a page
    4: ('gen', 'diagram_dispatch_loop', None, 0, 0),
    5: ('html', '05.html', 'div.diagram-frame', 0, 1500),
    6: ('html', '05.html', 'div.diagram-frame', 1, 1500),
    # figure 7 is the illustrated Use Case C flow supplied in sample-unified.docx
    7: ('brand', 'usecase-c-flow.png', None, 0, 0),
}
DPI = 140


def strip_emoji(text):
    return EMOJI.sub(lambda m: m.group(0) if m.group(0) in KEEP else '', text)


def render_svg(src_file, scale, out_png):
    import cairosvg
    raw = (SECTIONS / src_file).read_text(encoding='utf-8')
    svgs = re.findall(r'<svg\b.*?</svg>', raw, re.S)
    # the diagram is the biggest svg in the file; the small ones are markers/icons
    svg = max(svgs, key=len)
    svg = strip_emoji(html.unescape(svg))
    svg = re.sub(r'&(?!(?:amp|lt|gt|quot|apos);)', '&amp;', svg)
    # cairosvg has no paint-order, so the white halo behind edge labels would be
    # painted over the glyphs — drop the halo stroke from <text> elements
    def clean_text_tag(m):
        tag = m.group(0)
        tag = re.sub(r'\s(stroke|stroke-width|paint-order)="[^"]*"', '', tag)
        return tag
    svg = re.sub(r'<text\b[^>]*>', clean_text_tag, svg)
    svg = svg.replace('font-family:inherit', f'font-family:{FONT_STACK}')
    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg, re.I)
    w, h = float(vb.group(1)), float(vb.group(2))
    svg = re.sub(r'width="100%"', f'width="{w}" height="{h}"', svg, count=1)
    tmp_svg = TMP / (out_png.stem + '.svg')
    tmp_svg.write_text(svg, encoding='utf-8')
    cairosvg.svg2png(url=str(tmp_svg), write_to=str(out_png),
                     output_width=int(w * scale), output_height=int(h * scale),
                     background_color='white')
    return out_png


def render_html(src_file, selector, nth, page_w, out_png):
    from weasyprint import HTML
    soup = BeautifulSoup((SECTIONS / src_file).read_text(encoding='utf-8'), 'html.parser')
    node = soup.select(selector)[nth]
    frag = strip_emoji(str(node))
    css = (SECTIONS / 'style.css').read_text(encoding='utf-8')
    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
{css}
</style>
<style>
  @page {{ size: {page_w}px 5000px; margin: 0; }}
  html, body {{ margin:0; padding:16px; background:#fff; }}
  * {{ font-family: {FONT_STACK} !important; }}
  /* let the solo flow card use the full print width instead of its 580px web cap */
  .opsflow-cards.opsflow-solo {{ max-width: {page_w - 70}px !important; margin:0 !important; }}
  /* the frame chrome is redundant once the figure has its own frame in the doc */
  .diagram-frame {{ overflow: visible !important; border: none !important; padding: 0 !important; }}
  a, a.xref {{ text-decoration: none !important; }}
  /* WeasyPrint's grid support is patchy for nested tracks — the equal-column
     grids in these diagrams lay out reliably as flex rows instead */
  .uca-diagram .uca-grid2, .uca-diagram .uca-grid3,
  .uca-diagram .uca-redis-row, .uca-diagram .uca-branch {{
      display: flex !important; align-items: stretch !important; }}
  .uca-diagram .uca-grid2 > *, .uca-diagram .uca-grid3 > *,
  .uca-diagram .uca-redis-row > *, .uca-diagram .uca-branch > * {{
      flex: 1 1 0 !important; min-width: 0 !important; }}
</style></head><body>{frag}</body></html>"""
    tmp_html = TMP / f'_capture_{out_png.stem}.html'
    tmp_html.write_text(page, encoding='utf-8')
    pdf = TMP / (out_png.stem + '.pdf')
    HTML(filename=str(tmp_html), base_url=str(SECTIONS)).write_pdf(str(pdf))
    stem = TMP / (out_png.stem + '-raw')
    subprocess.run(['pdftoppm', '-png', '-r', str(DPI), '-f', '1', '-l', '1',
                    str(pdf), str(stem)], check=True, capture_output=True)
    raw = next(TMP.glob(out_png.stem + '-raw*.png'))
    subprocess.run(['convert', str(raw), '-trim', '+repage',
                    '-bordercolor', 'white', '-border', '10', str(out_png)],
                   check=True, capture_output=True)
    return out_png


def png_size(path):
    data = path.read_bytes()[16:24]
    return int.from_bytes(data[:4], 'big'), int.from_bytes(data[4:], 'big')


def main():
    for tool in ('pdftoppm', 'convert'):
        if not shutil.which(tool):
            sys.exit(f'missing {tool}')
    TMP.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for num, (kind, src, sel, nth, size) in sorted(FIGURES.items()):
        out = OUT_DIR / f'fig{num}.png'
        if kind == 'brand':
            import shutil as _sh
            _sh.copyfile(ROOT / 'assets' / 'brand' / src, out)
        elif kind == 'gen':
            import importlib
            importlib.import_module(src).main()
        elif kind == 'svg':
            render_svg(src, size, out)
        else:
            render_html(src, sel, nth, int(size), out)
        w, h = png_size(out)
        manifest[str(num)] = {'file': out.name, 'w': w, 'h': h,
                              'aspect': round(h / w, 4), 'source': src}
        where = src if kind != 'html' else f'{src} · {sel}[{nth}]'
        print(f'fig{num}  {w}x{h}px  h/w={h / w:.2f}  <- {where}')
    (OUT_DIR / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(f'\n{len(manifest)} figures -> {OUT_DIR}')


if __name__ == '__main__':
    main()
