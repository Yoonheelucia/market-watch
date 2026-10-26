"""종목별 최근 5개년 실적(분기/연간)을 계산해 docs/earnings.json 으로 저장한다.

- 실적발표일, EPS 컨센서스와 실제 EPS, 서프라이즈: 야후 파이낸스 earnings dates
- 발표 반응: 발표 후 첫 거래일(D)과 D+1, D+2 의 일간 등락률
- PER: 당시 종가 / 직전 4개 분기 EPS 합, 선행 PER: 당시 종가 / 이후 4개 분기 컨센서스 EPS 합
build.py 가 호출한다. 일부 종목 조회가 실패하면 이전 earnings.json 의 값을 그대로 둔다.
"""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import time as dtime

import pandas as pd
import yfinance as yf

YEARS = 5
QUARTERS = YEARS * 4


def num(v, digits=4):
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, digits)


def timing(ts, korean):
    """발표 시각으로 장전/장중/장후를 나눈다. 장후 발표면 다음 거래일이 반응일이다."""
    t = ts.time()
    if t == dtime(0, 0):
        return '시간 미상'
    open_, close = (dtime(9, 0), dtime(15, 30)) if korean else (dtime(9, 30), dtime(16, 0))
    return '장전' if t < open_ else '장후' if t >= close else '장중'


def quarter_end(d, fy_month):
    """발표일 d 직전에 끝난 회계 분기의 마지막 달(월말)."""
    months = {(fy_month - 1 - 3 * k) % 12 + 1 for k in range(4)}
    m = pd.Timestamp(d.year, d.month, 1) - pd.offsets.MonthEnd(1)
    while m.month not in months:
        m -= pd.offsets.MonthEnd(1)
    return m


def fiscal_year_end(period_end, fy_month):
    y = period_end.year + (1 if period_end.month > fy_month else 0)
    return pd.Timestamp(y, fy_month, 1) + pd.offsets.MonthEnd(0)


def fy_label(fy_end):
    return str(fy_end.year) if fy_end.month == 12 else f'FY{fy_end.year}'


def ret(closes, i, j):
    if i < 0 or j < 0 or i >= len(closes) or j >= len(closes):
        return None
    return num((closes.iloc[i] / closes.iloc[j] - 1) * 100, 2)


def build_one(ticker, name, closes):
    korean = ticker.endswith(('.KS', '.KQ'))
    tz = 'Asia/Seoul' if korean else 'America/New_York'
    t = yf.Ticker(ticker)

    ed = t.get_earnings_dates(limit=QUARTERS + 12)
    if ed is None or ed.empty:
        raise RuntimeError('실적 일정 없음')
    ed = ed.copy()
    ed.index = ed.index.tz_convert(tz)
    ed = ed.sort_index()

    info = t.info or {}
    fy_ts = info.get('lastFiscalYearEnd')
    fy_month = pd.Timestamp(fy_ts, unit='s').month if fy_ts else 12
    try:
        est = t.earnings_estimate
    except Exception:
        est = None
    est_avg = (lambda p: num(est.loc[p, 'avg']) if est is not None and 'avg' in est.columns and p in est.index else None)

    closes = closes.dropna()
    cdates = closes.index.date
    today = pd.Timestamp.now(tz=tz)

    # 분기별 행: 회계 분기마다 한 건 (실제 EPS 가 있는 발표를 우선)
    rows = {}
    upcoming = None
    for ts, r in ed.iterrows():
        actual, estimate = num(r.get('Reported EPS')), num(r.get('EPS Estimate'))
        if ts > today and actual is None:
            if upcoming is None or ts < upcoming['ts']:
                upcoming = {'ts': ts, 'est': estimate}
            continue
        if actual is None:
            continue
        pe_ = quarter_end(ts, fy_month)
        if pe_ in rows and rows[pe_]['ts'] > ts:
            continue
        rows[pe_] = {'ts': ts, 'est': estimate, 'act': actual}

    periods = sorted(rows)
    estimates = [rows[p]['est'] for p in periods] + ([upcoming['est']] if upcoming else [])
    quarters = []
    for n, p in enumerate(periods):
        r = rows[p]
        ts, when = r['ts'], timing(r['ts'], korean)
        same_day = when in ('장전', '장중', '시간 미상')
        i = next((k for k, d in enumerate(cdates) if d > ts.date() or (same_day and d == ts.date())), None)
        price = num(closes.iloc[i], 2) if i is not None else None
        ttm = sum(rows[x]['act'] for x in periods[n - 3:n + 1]) if n >= 3 else None
        nxt = estimates[n + 1:n + 5]
        fwd = sum(nxt) if len(nxt) == 4 and None not in nxt else None
        fy_end = fiscal_year_end(p, fy_month)
        fq = 4 - (fy_end.year * 12 + fy_end.month - p.year * 12 - p.month) // 3
        surprise = (r['act'] - r['est']) / abs(r['est']) * 100 if r['est'] else None
        quarters.append({
            'date': ts.strftime('%Y-%m-%d'), 'when': when,
            'period': p.strftime('%Y.%m'), 'fy': fy_label(fy_end), 'fq': fq, 'fyEnd': fy_end.strftime('%Y-%m-%d'),
            'est': r['est'], 'act': r['act'], 'surp': num(surprise, 2),
            'beat': None if r['est'] is None else (1 if r['act'] > r['est'] else -1 if r['act'] < r['est'] else 0),
            'r0': ret(closes, i, i - 1) if i is not None else None,
            'r1': ret(closes, i + 1, i) if i is not None else None,
            'r2': ret(closes, i + 2, i + 1) if i is not None else None,
            'price': price, 'ttm': num(ttm),
            'pe': num(price / ttm, 1) if price and ttm and ttm > 0 else None,
            'fpe': num(price / fwd, 1) if price and fwd and fwd > 0 else None,
        })

    # 연간 행: 회계연도별로 4개 분기를 묶는다
    years = []
    by_fy = {}
    for q in quarters:
        by_fy.setdefault(q['fyEnd'], []).append(q)
    fy_ends = sorted(by_fy)
    for k, fe in enumerate(fy_ends):
        qs = by_fy[fe]
        complete = len(qs) == 4
        eps = sum(q['act'] for q in qs)
        ests = [q['est'] for q in qs]
        est_sum = sum(ests) if None not in ests else None
        before = closes[closes.index <= pd.Timestamp(fe)]
        price = num(before.iloc[-1], 2) if complete and len(before) else None
        nxt = by_fy.get(fy_ends[k + 1]) if k + 1 < len(fy_ends) else None
        if nxt and len(nxt) == 4 and None not in [q['est'] for q in nxt]:
            fwd = sum(q['est'] for q in nxt)
        elif complete and all(len(by_fy[f]) < 4 for f in fy_ends[k + 1:]):
            fwd = est_avg('0y')  # 진행 중인 회계연도의 현재 컨센서스
        else:
            fwd = None
        prev = years[-1] if years else None
        q4 = qs[-1] if complete else None
        years.append({
            'fy': qs[0]['fy'], 'fyEnd': fe, 'n': len(qs), 'eps': num(eps),
            'est': num(est_sum), 'surp': num((eps - est_sum) / abs(est_sum) * 100, 2) if est_sum else None,
            'beats': sum(1 for q in qs if q['beat'] == 1),
            'growth': num((eps / prev['eps'] - 1) * 100, 1) if prev and prev['n'] == 4 and complete and prev['eps'] > 0 else None,
            'price': price,
            'pe': num(price / eps, 1) if price and eps > 0 else None,
            'fpe': num(price / fwd, 1) if price and fwd and fwd > 0 else None,
            'date': q4['date'] if q4 else None, 'when': q4['when'] if q4 else None,
            'r0': q4['r0'] if q4 else None, 'r1': q4['r1'] if q4 else None, 'r2': q4['r2'] if q4 else None,
        })

    last = num(closes.iloc[-1], 2)
    ttm = sum(q['act'] for q in quarters[-4:]) if len(quarters) >= 4 else None
    fwd_eps = est_avg('+1y')
    try:
        fwd_growth = num(est.loc['+1y', 'growth'] * 100, 1) if est is not None and 'growth' in est.columns and '+1y' in est.index else None
    except Exception:
        fwd_growth = None
    complete_years = [y for y in years if y['n'] == 4]
    return {
        'name': name, 'longName': info.get('longName') or info.get('shortName'),
        'currency': 'KRW' if korean else 'USD', 'fyMonth': fy_month,
        'price': last, 'priceDate': closes.index[-1].strftime('%Y-%m-%d'),
        'ttmEps': num(ttm), 'pe': num(last / ttm, 1) if ttm and ttm > 0 else None,
        'fwdEps': fwd_eps, 'fwdGrowth': fwd_growth, 'fpe': num(last / fwd_eps, 1) if fwd_eps and fwd_eps > 0 else None,
        'next': {'date': upcoming['ts'].strftime('%Y-%m-%d'), 'when': timing(upcoming['ts'], korean), 'est': upcoming['est']} if upcoming else None,
        'quarters': quarters[-QUARTERS:],
        'years': complete_years[-YEARS:] + [y for y in years if y['n'] < 4 and y is years[-1]],
    }


def build_earnings(stocks, download, out):
    """stocks: {ticker: 이름}. download: build.download (재시도 포함)."""
    old = {}
    if out.exists():
        try:
            old = json.loads(out.read_text()).get('stocks', {})
        except Exception:
            pass

    tickers = sorted(stocks)
    start = (pd.Timestamp.today() - pd.DateOffset(years=YEARS + 1, months=6)).strftime('%Y-%m-%d')
    raw = download(tickers, start, auto_adjust=False)  # 분할만 반영된 종가 (배당 미반영)

    def one(ticker):
        try:
            return ticker, build_one(ticker, stocks[ticker], raw[ticker]['Close'])
        except Exception as e:
            return ticker, e

    result, failed = {}, []
    with ThreadPoolExecutor(4) as ex:
        for ticker, r in ex.map(one, tickers):
            if isinstance(r, Exception):
                failed.append(f'{ticker}({r})')
                if ticker in old:
                    result[ticker] = old[ticker]
            else:
                result[ticker] = r
    print(f'실적: {len(tickers) - len(failed)}/{len(tickers)}개 종목 갱신' + (f', 실패 {failed}' if failed else ''))
    return result
