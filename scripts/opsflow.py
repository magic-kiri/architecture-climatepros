#!/usr/bin/env python3
"""Read the Use Case A assignment loop out of sections/05.html as structured data.

The html export of the design set flattens this flow card into one run-on
paragraph (step titles fused to their descriptions, decision arms dumped inline).
The live fragment still has the real structure, so both the Word step table and
the redrawn print diagram are built from here — one source, two renderings.
"""
import pathlib
import re

from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECTIONS = ROOT / 'sections'

EMOJI = re.compile('[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF'
                   '\U00002B00-\U00002BFF️]')
KEEP = set('✓✔✗✘×•')
TONES = ('blue', 'amber', 'violet', 'red', 'green')


def clean(text):
    text = EMOJI.sub(lambda m: m.group(0) if m.group(0) in KEEP else '', text or '')
    text = text.replace(' ', ' ').replace('“', '"').replace('”', '"')
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s+([,.;:!?])(?![A-Za-z0-9])', r'\1', text)
    text = re.sub(r'\(\s+', '(', text)
    text = re.sub(r'\s+\)', ')', text)
    return text.strip()


def _soup(name='05.html'):
    return BeautifulSoup((SECTIONS / name).read_text(encoding='utf-8'), 'html.parser')


def _tone(el):
    for t in TONES:
        if t in (el.get('class') or []):
            return t
    return 'blue'


def _end(el):
    """A branch terminal: headline + optional sub-label."""
    sub = el.find('small')
    sub_text = clean(sub.get_text(' ', strip=True)) if sub else ''
    if sub:
        sub.extract()
    return {'text': clean(el.get_text(' ', strip=True)), 'sub': sub_text,
            'go': 'go' in (el.get('class') or []),
            'loop': 'move' in (el.get('class') or [])}


def parse_dispatch_flow():
    """-> {'trigger', 'items': [step | decision, ...]} in flow order."""
    card = _soup().select('div.opsflow-cards.opsflow-solo')[0].select_one('.opsflow-card')
    trigger = clean(card.select_one('.opsflow-trigger').get_text(' ', strip=True))
    trigger = re.sub(r'^Trigger\s*·\s*', '', trigger)

    items = []
    step_no = 0

    def take_node(node):
        nonlocal step_no
        body = node.select_one('.opsflow-body') or node
        txt = body.select_one('.opsflow-txt')
        tags = [clean(t.get_text(' ', strip=True))
                for t in txt.select('.opsflow-tag')] if txt else []
        detail = ''
        if txt:
            small = txt.find('small')
            if small:
                detail = clean(small.get_text(' ', strip=True))
                small.extract()
            for t in txt.select('.opsflow-tag'):
                t.extract()
            title = clean(txt.get_text(' ', strip=True))
        else:
            title = clean(body.get_text(' ', strip=True))
        step_no += 1
        items.append({'kind': 'step', 'n': step_no, 'title': title, 'detail': detail,
                      'tags': tags, 'tone': _tone(node)})

    def scan(container):
        pending = None
        for el in container.children:
            if not el.name:
                continue
            cls = el.get('class') or []
            if 'opsflow-conn' in cls or 'opsflow-loop-tag' in cls:
                continue
            if 'opsflow-node' in cls:
                take_node(el)
            elif 'opsflow-decision' in cls:
                inner = el.select_one('.opsflow-decision-inner') or el
                pending = {'kind': 'decision',
                           'q': clean(inner.get_text(' ', strip=True)),
                           'tone': _tone(el), 'arms': [], 'ends': []}
                items.append(pending)
            elif 'opsflow-branch-arms' in cls and pending:
                pending['arms'] = [clean(a.get_text(' ', strip=True))
                                   for a in el.select('.opsflow-arm')]
            elif 'opsflow-branches' in cls and pending:
                pending['ends'] = [_end(e) for e in el.select('.opsflow-end')]
                pending = None
            elif 'opsflow-loop' in cls:
                scan(el)

    scan(card.select_one('.opsflow-chain'))

    # the source numbers its worker steps in a second series and points the retry
    # arm at "step 4" of that inner series — repoint it at the single sequence
    offer = next((i for i in items if i['kind'] == 'step'
                  and i['title'].lower().startswith('offer to the top')), None)
    if offer:
        for it in items:
            if it['kind'] == 'decision':
                for e in it['ends']:
                    e['sub'] = re.sub(r'loop back to step \d+',
                                      f"loop back to step {offer['n']}", e['sub'])
    return {'trigger': trigger, 'items': items}


def parse_sns_roundtrip():
    """-> [{'n', 'title', 'detail'}] for the Amazon SNS round-trip steps."""
    out = []
    for div in _soup().select('div.flow-step'):
        num = div.select_one('.flow-num')
        head = div.select_one('h4')
        body = div.select_one('p')
        out.append({'n': clean(num.get_text()) if num else str(len(out) + 1),
                    'title': clean(head.get_text(' ', strip=True)) if head else '',
                    'detail': clean(body.get_text(' ', strip=True)) if body else ''})
    return out


if __name__ == '__main__':
    flow = parse_dispatch_flow()
    print('trigger:', flow['trigger'])
    for it in flow['items']:
        if it['kind'] == 'step':
            print(f"  {it['n']}. [{it['tone']}] {it['title']}"
                  f"{'  tags=' + str(it['tags']) if it['tags'] else ''}")
            print(f"      {it['detail']}")
        else:
            print(f"  <> {it['q']}  arms={it['arms']}")
            for e in it['ends']:
                print(f"      -> {e['text']}  ({e['sub']})")
    print()
    for s in parse_sns_roundtrip():
        print(f"  {s['n']}. {s['title']} — {s['detail'][:70]}")
