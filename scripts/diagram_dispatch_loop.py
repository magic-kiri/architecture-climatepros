#!/usr/bin/env python3
"""Redraw the Use Case A assignment loop as a print-native diagram (Figure 4).

The web version is a tall single-column card — at 1.6x taller than wide it can
only ever be shrunk to ~4.5in in a portrait Word page, which is what made the
section unreadable. This lays the same flow (parsed from sections/05.html, so
the wording stays in sync) into three labelled bands that read left-to-right,
in the document's own navy/copper palette, at a landscape aspect.

Run:  python3 scripts/diagram_dispatch_loop.py
Out:  assets/figures/fig4.svg + fig4.png
"""
import math
import pathlib
import re

import cairosvg

from opsflow import parse_dispatch_flow

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / 'assets' / 'figures'

# ---- palette: the same tokens the Word document uses -------------------------
NAVY = '#12233F'
NAVY_MID = '#1B3B6F'
COPPER = '#B4671A'
TEAL = '#14685E'
RED = '#A32A21'
INK = '#22303C'
MUTED = '#6E7B8B'
RULE = '#D3DAE4'
LANE_BG = '#F7F9FC'
BLUE_SOFT = '#EEF2F8'
COPPER_SOFT = '#FCF7F0'
TEAL_SOFT = '#EAF5F1'
RED_SOFT = '#FCF2F1'
GREY_SOFT = '#F4F5F7'
WHITE = '#FFFFFF'

TONE = {                       # web tone -> (line, fill, title colour)
    'blue': (NAVY_MID, BLUE_SOFT, NAVY),
    'amber': (COPPER, COPPER_SOFT, NAVY),
    'violet': (NAVY_MID, WHITE, NAVY),
    'red': (RED, RED_SOFT, RED),
    'green': (TEAL, TEAL_SOFT, TEAL),
}

# Carlito has no ✓ or ↻ and cairosvg does not fall back per glyph, so those are
# drawn as paths instead of set as text
GLYPHS = re.compile('[✓✔↻⟳]')


def deglyph(text):
    return re.sub(r'\s{2,}', ' ', GLYPHS.sub('', text or '')).strip()

FONT = "'Carlito','Segoe UI','DejaVu Sans',sans-serif"
W = 1480                       # canvas width in units; 1 unit ~ 0.457pt at 9.4in
PAD = 22
LANE_LABEL_W = 116
X0 = LANE_LABEL_W + 34
X1 = W - PAD

F_TITLE, F_BODY, F_TAG, F_EDGE, F_LANE = 20, 16, 13.5, 15, 14.5
LH_TITLE, LH_BODY = 25, 21


def wrap(text, font_size, width, bold=False):
    """Greedy wrap using an average glyph width for Carlito."""
    per_char = font_size * (0.525 if bold else 0.50)
    limit = max(6, int(width / per_char))
    words, lines, cur = text.split(), [], ''
    for word in words:
        trial = f'{cur} {word}'.strip()
        if len(trial) <= limit or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def esc(text):
    return (text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


class Svg:
    def __init__(self):
        self.parts = []

    def add(self, markup):
        self.parts.append(markup)

    def rect(self, x, y, w, h, fill, stroke=None, rx=12, sw=1.6, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ''
        s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ''
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                 f'rx="{rx}" fill="{fill}"{s}{d}/>')

    def text(self, x, y, s, size=F_BODY, fill=INK, weight='400', anchor='start',
             spacing=None, italic=False):
        sp = f' letter-spacing="{spacing}"' if spacing else ''
        it = ' font-style="italic"' if italic else ''
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" '
                 f'font-size="{size}" fill="{fill}" font-weight="{weight}" '
                 f'text-anchor="{anchor}"{sp}{it}>{esc(s)}</text>')

    def lines(self, x, y, rows, size, fill, weight='400', lh=None, anchor='start'):
        lh = lh or size * 1.32
        for i, row in enumerate(rows):
            self.text(x, y + i * lh, row, size=size, fill=fill, weight=weight,
                      anchor=anchor)
        return y + max(0, len(rows) - 1) * lh

    def path(self, d, stroke, sw=1.8, dash=None, marker='arrow', fill='none'):
        dd = f' stroke-dasharray="{dash}"' if dash else ''
        mk = f' marker-end="url(#{marker})"' if marker else ''
        self.add(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" '
                 f'stroke-linejoin="round" stroke-linecap="round"{dd}{mk}/>')

    def diamond(self, cx, cy, w, h, stroke, fill):
        pts = f'{cx},{cy - h / 2} {cx + w / 2},{cy} {cx},{cy + h / 2} {cx - w / 2},{cy}'
        self.add(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="1.6"/>')

    def check(self, x, y, color=TEAL, size=13):
        self.add(f'<path d="M{x:.1f},{y:.1f} l{size * 0.32:.1f},{size * 0.34:.1f} '
                 f'l{size * 0.62:.1f},-{size * 0.78:.1f}" fill="none" stroke="{color}" '
                 f'stroke-width="{size * 0.19:.1f}" stroke-linecap="round" '
                 f'stroke-linejoin="round"/>')

    def render(self, height):
        markers = ''.join(
            f'<marker id="{name}" markerWidth="9" markerHeight="9" refX="7.2" '
            f'refY="3.2" orient="auto"><path d="M0,0 L7,3.2 L0,6.4 Z" '
            f'fill="{color}"/></marker>'
            for name, color in (('arrow', NAVY_MID), ('arrowC', COPPER),
                                ('arrowT', TEAL), ('arrowM', MUTED),
                                ('arrowR', RED)))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height:.0f}" '
                f'width="{W}" height="{height:.0f}">'
                f'<defs>{markers}</defs>'
                f'<rect width="{W}" height="{height:.0f}" fill="{WHITE}"/>'
                + ''.join(self.parts) + '</svg>')


# ---------------------------------------------------------------- box geometry
def box_height(title, detail, tags, width):
    inner = width - 34
    h = 15
    h += len(wrap(title, F_TITLE, inner - 30, bold=True)) * LH_TITLE
    if tags:
        h += 24
    if detail:
        h += 6 + len(wrap(detail, F_BODY, inner)) * LH_BODY
    return h + 15


def draw_step(svg, x, y, w, item, number=True):
    line, fill, accent = TONE[item['tone']]
    item = dict(item, title=deglyph(item['title']), detail=deglyph(item['detail']))
    h = box_height(item['title'], item['detail'], item['tags'], w)
    svg.rect(x, y, w, h, fill, stroke=line, rx=13)
    tx = x + 17
    ty = y + 15 + F_TITLE
    if number:
        svg.add(f'<circle cx="{tx + 11:.1f}" cy="{ty - 6:.1f}" r="12.5" fill="{line}"/>')
        svg.text(tx + 11, ty - 1.5, str(item['n']), size=F_TAG + 1, fill=WHITE,
                 weight='700', anchor='middle')
        tx += 32
    last = svg.lines(tx, ty, wrap(item['title'], F_TITLE, w - 34 - (tx - x - 17),
                                  bold=True), F_TITLE, accent, '700', LH_TITLE)
    cur = last + 8
    if item['tags']:
        tagx = tx
        for tag in item['tags']:
            tw = len(tag) * F_TAG * 0.52 + 18
            svg.rect(tagx, cur, tw, 19, COPPER_SOFT, stroke=None, rx=9.5)
            svg.text(tagx + tw / 2, cur + 14, tag, size=F_TAG, fill=COPPER,
                     weight='700', anchor='middle')
            tagx += tw + 7
        cur += 26
    if item['detail']:
        svg.lines(x + 17, cur + F_BODY, wrap(item['detail'], F_BODY, w - 34),
                  F_BODY, MUTED, '400', LH_BODY)
    return h


def draw_pill(svg, x, y, w, head, sub, tone='teal', dash=None):
    tick = bool(GLYPHS.search(head or ''))
    head, sub = deglyph(head), deglyph(sub)
    line, fill, accent = {
        'teal': (TEAL, TEAL_SOFT, TEAL),
        'grey': (MUTED, GREY_SOFT, MUTED),
        'red': (RED, RED_SOFT, RED),
    }[tone]
    head_lines = wrap(head, F_BODY + 1, w - 30, bold=True)
    sub_lines = wrap(sub, F_BODY - 1, w - 30) if sub else []
    h = 14 + len(head_lines) * 20 + (6 + len(sub_lines) * 17 if sub_lines else 0) + 14
    svg.rect(x, y, w, h, fill, stroke=line, rx=h / 2 if h < 60 else 14, sw=1.5, dash=dash)
    cy = y + 14 + F_BODY
    last = svg.lines(x + w / 2, cy, head_lines, F_BODY + 1, accent, '700',
                     20, anchor='middle')
    if tick:
        tw = len(head_lines[0]) * (F_BODY + 1) * 0.525
        svg.check(x + w / 2 + tw / 2 + 8, cy - 8, accent, 14)
    if sub_lines:
        svg.lines(x + w / 2, last + 6 + F_BODY - 1, sub_lines, F_BODY - 1, MUTED,
                  '400', 17, anchor='middle')
    return h


def lane(svg, y, h, label):
    svg.rect(PAD, y, W - 2 * PAD, h, LANE_BG, stroke=RULE, rx=14, sw=1.2)
    svg.rect(PAD, y, 4.5, h, NAVY_MID, stroke=None, rx=2)
    cx, cy = PAD + 58, y + h / 2
    # the label reads bottom-to-top, so it has to fit inside the band height
    size, spacing = F_LANE, 1.6
    while (len(label) * (size * 0.56 + spacing)) > h - 24 and size > 9:
        size -= 0.5
        spacing = max(0.4, spacing - 0.1)
    svg.add(f'<g transform="rotate(-90 {cx} {cy})">')
    svg.text(cx, cy + 5, label, size=size, fill=NAVY_MID, weight='700',
             anchor='middle', spacing=f'{spacing:.1f}')
    svg.add('</g>')


def build():
    flow = parse_dispatch_flow()
    items = flow['items']
    steps = [i for i in items if i['kind'] == 'step']
    gate, accept = [i for i in items if i['kind'] == 'decision']
    intake, pickup = steps[0], steps[1]
    worker = steps[2:5]
    offer, escalate = steps[5], steps[6]

    svg = Svg()
    y = PAD + 4

    # ---------------- band 1 · intake -------------------------------------
    bw = 320
    trig_h = 30
    step_h = box_height(intake['title'], intake['detail'], intake['tags'], bw)
    yes_end = next(e for e in gate['ends'] if e['go'])
    no_end = next(e for e in gate['ends'] if not e['go'])

    dcx = X0 + bw + 155
    pill_w = 340
    px = dcx + 105 + 90
    no_w = 330
    h_yes = draw_pill(Svg(), 0, 0, pill_w, yes_end['text'], yes_end['sub'], 'teal')
    h_no = draw_pill(Svg(), 0, 0, no_w, no_end['text'], no_end['sub'], 'grey')

    body_top = y + 20 + trig_h + 18
    diamond_h = 112
    lane_h = (20 + trig_h + 18
              + max(step_h, diamond_h + 34 + h_no, h_yes) + 22)
    lane(svg, y, lane_h, 'INTAKE · PLATFORM')

    svg.rect(X0, y + 18, 248, trig_h, COPPER_SOFT, stroke=None, rx=15)
    svg.text(X0 + 16, y + 18 + 20, f"TRIGGER · {flow['trigger'].upper()}",
             size=F_TAG, fill=COPPER, weight='700', spacing='1.4')

    draw_step(svg, X0, body_top, bw, intake)
    dcy = body_top + diamond_h / 2
    svg.path(f'M{X0 + bw + 8},{dcy} H{dcx - 105}', NAVY_MID)
    svg.diamond(dcx, dcy, 200, diamond_h, NAVY_MID, WHITE)
    q_rows = wrap(gate['q'], F_BODY, 152)
    for i, row in enumerate(q_rows):
        svg.text(dcx, dcy + 5 + (i - (len(q_rows) - 1) / 2) * 18, row,
                 size=F_BODY, fill=NAVY, weight='700', anchor='middle')

    # YES · straight on into the queue
    y_yes = dcy - h_yes / 2
    svg.path(f'M{dcx + 104},{dcy} H{px - 8}', TEAL, marker='arrowT')
    svg.text(dcx + 118, dcy - 10, gate['arms'][1], size=F_EDGE, fill=TEAL, weight='700')
    draw_pill(svg, px, y_yes, pill_w, yes_end['text'], yes_end['sub'], 'teal')

    # NO · drops out under the gate, no further processing
    y_no = dcy + diamond_h / 2 + 34
    svg.path(f'M{dcx},{dcy + diamond_h / 2 + 2} V{y_no - 8}', MUTED,
             marker='arrowM', dash='5 4')
    svg.text(dcx + 12, dcy + diamond_h / 2 + 24, gate['arms'][0], size=F_EDGE,
             fill=MUTED, weight='700')
    draw_pill(svg, dcx - no_w / 2, y_no, no_w, no_end['text'], no_end['sub'],
              'grey', dash='5 4')

    band1_bottom = y + lane_h
    y = band1_bottom + 34

    # ---------------- band 2 · worker -------------------------------------
    row2 = [pickup] + worker
    gap = 26
    bw2 = (X1 - X0 - gap * (len(row2) - 1)) / len(row2)
    heights = [box_height(s['title'], s['detail'], s['tags'], bw2) for s in row2]
    lane_h2 = max(heights) + 44
    lane(svg, y, lane_h2, 'DISPATCH WORKER')
    top2 = y + 22
    xs = [X0 + i * (bw2 + gap) for i in range(len(row2))]
    for x, item in zip(xs, row2):
        draw_step(svg, x, top2, bw2, item)
    for i in range(len(row2) - 1):
        x_from = xs[i] + bw2 + 5
        svg.path(f'M{x_from},{top2 + max(heights) / 2} H{xs[i + 1] - 8}', NAVY_MID)
    # hand-off from the queue pill into the first worker box
    svg.path(f'M{px + pill_w / 2},{y_yes + h_yes + 6} V{y - 17} '
             f'H{xs[0] + bw2 / 2} V{top2 - 8}', TEAL, marker='arrowT')
    svg.text(xs[0] + bw2 / 2 + 14, y - 23, 'queued dispatch id', size=F_EDGE,
             fill=TEAL, weight='700')

    band2_bottom = y + lane_h2
    y = band2_bottom + 34

    # ---------------- band 3 · offer loop ---------------------------------
    bw3 = 350
    offer_h = box_height(offer['title'], offer['detail'], offer['tags'], bw3)
    acc_yes = next(e for e in accept['ends'] if e['go'])
    acc_no = next(e for e in accept['ends'] if e['loop'])
    esc_w = 320
    esc_h = box_height(escalate['title'], escalate['detail'], escalate['tags'], esc_w)
    ph = draw_pill(Svg(), 0, 0, 260, acc_yes['text'], acc_yes['sub'], 'teal')
    lane_h3 = max(offer_h, esc_h, 130) + 96
    lane(svg, y, lane_h3, 'OFFER LOOP')
    top3 = y + 24
    draw_step(svg, X0, top3, bw3, offer)
    dcx3 = X0 + bw3 + 150
    dcy3 = top3 + offer_h / 2
    svg.path(f'M{X0 + bw3 + 8},{dcy3} H{dcx3 - 105}', NAVY_MID)
    svg.diamond(dcx3, dcy3, 200, 112, COPPER, COPPER_SOFT)
    q_rows = wrap(accept['q'], F_BODY, 150)
    for i, row in enumerate(q_rows):
        svg.text(dcx3, dcy3 + 5 + (i - (len(q_rows) - 1) / 2) * 18, row,
                 size=F_BODY, fill=COPPER, weight='700', anchor='middle')

    yes_x = dcx3 + 150
    svg.path(f'M{dcx3 + 104},{dcy3} H{yes_x - 8}', TEAL, marker='arrowT')
    svg.text(dcx3 + 116, dcy3 - 10, accept['arms'][1], size=F_EDGE, fill=TEAL,
             weight='700')
    draw_pill(svg, yes_x, dcy3 - ph / 2, 260, acc_yes['text'], acc_yes['sub'], 'teal')

    # retry arc back into the offer box
    loop_y = top3 + max(offer_h, 130) + 52
    svg.path(f'M{dcx3},{dcy3 + 58} V{loop_y} H{X0 + bw3 / 2} V{top3 + offer_h + 8}',
             COPPER, marker='arrowC', dash='6 4')
    svg.text(dcx3 - 20, loop_y - 9,
             deglyph(f"{accept['arms'][0]} · {acc_no['text']}"),
             size=F_EDGE, fill=COPPER, weight='700', anchor='end')
    svg.text(dcx3 - 20, loop_y + 15, deglyph(acc_no['sub']), size=F_EDGE - 1,
             fill=MUTED, anchor='end', italic=True)

    # escalation exit
    esc_x = X1 - esc_w
    esc_y = loop_y - 30 - esc_h if esc_h < lane_h3 - 60 else top3
    esc_y = min(max(top3, esc_y), y + lane_h3 - esc_h - 20)
    svg.path(f'M{dcx3},{loop_y} H{esc_x + esc_w / 2} V{esc_y + esc_h + 8}',
             RED, marker='arrowR', dash='6 4')
    svg.text(esc_x + esc_w / 2 - 10, loop_y - 9, 'shortlist exhausted',
             size=F_EDGE, fill=RED, weight='700', anchor='end')
    draw_step(svg, esc_x, esc_y, esc_w, escalate)

    height = y + lane_h3 + PAD
    return svg.render(height), height


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    markup, height = build()
    svg_path = OUT_DIR / 'fig4.svg'
    svg_path.write_text(markup, encoding='utf-8')
    scale = 2600 / W
    cairosvg.svg2png(url=str(svg_path), write_to=str(OUT_DIR / 'fig4.png'),
                     output_width=int(W * scale), output_height=int(height * scale),
                     background_color='white')
    print(f'fig4  {int(W * scale)}x{int(height * scale)}px  '
          f'aspect h/w={height / W:.2f}  -> {OUT_DIR / "fig4.png"}')


if __name__ == '__main__':
    main()
