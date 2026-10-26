"""미국 종목의 사업부별 분기 매출을 SEC 공시(XBRL)에서 뽑아 docs/segments.json 으로 저장한다.

- 10-Q / 10-K 의 XBRL 에서 매출(Revenues 계열) 사실값 중, 하나의 축(사업부·제품 등)으로 나뉜 값을 모은다
- 여러 축 가운데 '나눈 값의 합 ≈ 전체 매출' 이 되는 축만 쓰고, 그중 가장 잘게 나뉜 축을 고른다 (지역 축은 제외)
- 4분기는 10-K 연간값 − 3분기 누적(9개월)값으로 계산한다
- 이미 처리한 공시는 다시 받지 않도록 결과에 공시 번호를 남겨 둔다
SEC 는 요청에 연락처 이메일을 요구하므로 환경변수 SEC_EMAIL 이 있어야 한다.
"""
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date

import requests

OUT = os.path.join(os.path.dirname(__file__), 'docs', 'segments.json')
QUARTERS = 8          # 화면에 보여 줄 분기 수
FILINGS = 10          # 종목당 확인할 최근 10-Q/10-K 수
REVENUE = ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues',
           'RevenueFromContractWithCustomerIncludingAssessedTax', 'RevenuesNetOfInterestExpense',
           'SalesRevenueNet', 'RevenuesNetOfInterestExpenseAndProvisionForCreditLoss']
SKIP_AXIS = re.compile(r'Geograph|Country|Region|Customer|Concentration|Consolidation|Range|Restatement|Legal|Scenario', re.I)

_last = [0.0]


def get(url, **kw):
    # SEC 요청 제한(초당 10회)을 넉넉히 지킨다
    wait = 0.15 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    r = requests.get(url, headers={'User-Agent': f"market-watch {os.environ['SEC_EMAIL']}"}, timeout=60, **kw)
    r.raise_for_status()
    return r


def local(tag):
    return tag.split('}')[-1]


def parse_instance(xml_bytes):
    """XBRL 인스턴스에서 (축, 멤버) 별 매출 사실값을 뽑는다."""
    root = ET.fromstring(xml_bytes)
    contexts = {}
    for c in root.iter():
        if local(c.tag) != 'context':
            continue
        start = end = None
        dims = {}
        for e in c.iter():
            n = local(e.tag)
            if n == 'startDate':
                start = e.text.strip()
            elif n == 'endDate':
                end = e.text.strip()
            elif n == 'explicitMember':
                dims[e.get('dimension')] = e.text.strip()
        if start and end:
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days
            contexts[c.get('id')] = (end, days, dims)

    facts = {}  # concept -> list of (end, days, dims, value)
    for e in root:
        n = local(e.tag)
        if n not in REVENUE or e.get('contextRef') not in contexts or not (e.text or '').strip():
            continue
        try:
            v = float(e.text)
        except ValueError:
            continue
        end, days, dims = contexts[e.get('contextRef')]
        facts.setdefault(n, []).append((end, days, dims, v))
    return facts


def parse_labels(xml_bytes):
    """라벨 파일에서 '회사가 붙인 이름' 을 뽑는다. 예: aapl_IPhoneMember → iPhone"""
    root = ET.fromstring(xml_bytes)
    X = '{http://www.w3.org/1999/xlink}'
    locs, texts, arcs = {}, {}, []
    for e in root.iter():
        n = local(e.tag)
        if n == 'loc':
            locs[e.get(X + 'label')] = e.get(X + 'href', '').split('#')[-1]
        elif n == 'label':
            role = e.get(X + 'role', '')
            if role.endswith('/label') or role.endswith('/terseLabel'):
                texts.setdefault(e.get(X + 'label'), {})['terse' if 'terse' in role else 'std'] = (e.text or '').strip()
        elif n == 'labelArc':
            arcs.append((e.get(X + 'from'), e.get(X + 'to')))
    out = {}
    for f, t in arcs:
        if f in locs and t in texts:
            out[locs[f]] = texts[t].get('terse') or texts[t].get('std')
    return out


def kind(days):
    return 'q' if 80 <= days <= 100 else '9m' if 260 <= days <= 285 else 'y' if 350 <= days <= 380 else None


def humanize(member):
    name = member.split(':')[-1]
    name = re.sub(r'(Segment)?Member$', '', name)
    name = re.sub(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', ' ', name)
    return name.replace(' And ', ' & ').strip()


def build_ticker(cik, cache):
    sub = get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json').json()
    r = sub['filings']['recent']
    filings = [(r['accessionNumber'][i], r['primaryDocument'][i], r['form'][i])
               for i in range(len(r['form'])) if r['form'][i] in ('10-Q', '10-K')][:FILINGS]

    done = cache.get('filings', {})
    if filings and cache.get('labelsFrom') != filings[0][0]:
        acc, doc, _ = filings[0]
        try:
            lab = get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{re.sub(r'.htm$', '_lab.xml', doc)}").content
            cache['labels'] = {k: v for k, v in parse_labels(lab).items() if k.endswith('Member')}
            cache['labelsFrom'] = acc
        except Exception:
            pass
    for acc, doc, form in filings:
        if acc in done:
            continue
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}"
        inst = re.sub(r'\.htm$', '_htm.xml', doc)
        try:
            xml = get(f'{base}/{inst}').content
        except requests.HTTPError:
            idx = get(f'{base}/index.json').json()
            names = [f['name'] for f in idx['directory']['item']
                     if f['name'].endswith('.xml') and not re.search(r'_(cal|def|lab|pre)\.xml$|FilingSummary', f['name'])]
            if not names:
                done[acc] = []
                continue
            xml = get(f'{base}/{names[0]}').content
        rows = []
        for concept, items in parse_instance(xml).items():
            for end, days, dims, v in items:
                k = kind(days)
                if k:
                    rows.append([concept, end, k, sorted(dims.items()), v])
        done[acc] = rows
    cache['filings'] = {acc: done[acc] for acc, _, _ in filings if acc in done}
    return cache


def assemble(cache):
    """모은 사실값으로 분기별 사업부 매출 표를 만든다."""
    # (concept, axis, member, kind, end) -> value  /  총매출은 axis=None
    vals = {}
    for rows in cache['filings'].values():
        for concept, end, k, dims, v in rows:
            dims = [(a, m) for a, m in dims if not (a.endswith('ConsolidationItemsAxis') and m.endswith('OperatingSegmentsMember'))]
            if not dims:
                vals[(concept, None, None, k, end)] = v
            elif len(dims) == 1 and not SKIP_AXIS.search(dims[0][0]):
                vals[(concept, dims[0][0], dims[0][1], k, end)] = v

    def quarterly(concept, axis, member):
        q = {e: v for (c, a, m, k, e), v in vals.items() if c == concept and a == axis and m == member and k == 'q'}
        nine = {e: v for (c, a, m, k, e), v in vals.items() if c == concept and a == axis and m == member and k == '9m'}
        for (c, a, m, k, e), v in vals.items():
            if c == concept and a == axis and m == member and k == 'y' and e not in q:
                ye = date.fromisoformat(e)
                prev = [n for n in nine if 80 <= (ye - date.fromisoformat(n)).days <= 100]
                if prev:
                    q[e] = v - nine[prev[0]]
        return q

    # 회사에 따라 총매출과 사업부 매출을 서로 다른 항목으로 적기도 해서, 총매출은 어느 항목이든 쓴다
    any_total = {}
    for concept in reversed(REVENUE):
        any_total.update(quarterly(concept, None, None))
    best = None
    for concept in REVENUE:
        total = {**any_total, **quarterly(concept, None, None)}
        if not total:
            continue
        axes = {}
        for (c, a, m, k, e) in vals:
            if c == concept and a:
                axes.setdefault(a, set()).add(m)
        for axis, members in axes.items():
            series = {m: quarterly(concept, axis, m) for m in members}
            ends = sorted(e for e in total if sum(1 for s in series.values() if e in s) >= 2)[-QUARTERS:]
            if len(ends) < 4:
                continue
            last = ends[-1]
            live = [m for m in members if last in series[m]]
            # 합계 바로 맞추기: 상위 묶음(예: 애플 'Products') 이 섞여 있으면 큰 것부터 빼 본다
            for _ in range(3):
                ssum = sum(series[m][last] for m in live)
                if abs(ssum - total[last]) <= total[last] * 0.02 or len(live) <= 2:
                    break
                big = max(live, key=lambda m: series[m][last])
                if abs(ssum - series[big][last] - total[last]) < abs(ssum - total[last]):
                    live.remove(big)
                else:
                    break
            ssum = sum(series[m][last] for m in live)
            if len(live) < 2 or abs(ssum - total[last]) > total[last] * 0.02:
                continue
            cells = sum(1 for m in live for e in ends if e in series[m])
            score = (ends[-1], len(live) <= 8, cells)  # 최신 분기 → 너무 잘게 쪼개지 않음 → 채워진 칸 수
            if best is None or score > best[0]:
                best = (score, concept, axis, live, series, total, ends)
    if not best:
        return None
    _, concept, axis, live, series, total, ends = best
    live.sort(key=lambda m: -series[m].get(ends[-1], 0))
    labels = cache.get('labels', {})

    def name(m):
        lab = labels.get(m.replace(':', '_'))
        return re.sub(r'\s*\[Member\]|\s+[Ss]egment$', '', lab).strip() if lab else humanize(m)
    return {
        'axis': humanize(axis.replace('Axis', 'Member')),
        'quarters': ends,
        'total': [round(total.get(e, 0) / 1e6) for e in ends],
        'series': [{'name': name(m), 'values': [None if e not in series[m] else round(series[m][e] / 1e6) for e in ends]}
                   for m in live],
    }


def build_segments(tickers):
    if not os.environ.get('SEC_EMAIL'):
        print('사업부 매출: SEC_EMAIL 이 없어 건너뜀')
        return
    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT))
        except Exception:
            pass
    cache_path = os.path.join(os.path.dirname(__file__), 'segments-cache.json')  # 웹에 올릴 필요 없는 중간 자료
    caches = {}
    if os.path.exists(cache_path):
        try:
            caches = json.load(open(cache_path))
        except Exception:
            pass

    ciks = {v['ticker']: v['cik_str'] for v in get('https://www.sec.gov/files/company_tickers.json').json().values()}
    result, failed = {}, []
    for t in tickers:
        sec_t = t.replace('.', '-')
        if sec_t not in ciks:
            continue
        try:
            caches[t] = build_ticker(ciks[sec_t], caches.get(t, {}))
            seg = assemble(caches[t])
            if seg:
                result[t] = seg
            else:
                failed.append(f'{t}(구분 없음)')
        except Exception as e:
            failed.append(f'{t}({type(e).__name__})')
            if t in old:
                result[t] = old[t]
    json.dump(caches, open(cache_path, 'w'), separators=(',', ':'))
    json.dump(result, open(OUT, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'사업부 매출: {len(result)}/{len(tickers)}개 종목' + (f', 없음/실패 {failed}' if failed else ''))


if __name__ == '__main__':
    import sys
    build_segments(sys.argv[1:])
