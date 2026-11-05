"""미국 주식 전체로 '이동평균선 위 종목 비율'을 계산해 docs/breadth.json 의 market 칸에 넣는다.

Barchart Market Performance 의 'MARKET AVERAGE'($BCMM)와 같은 기준:
  SEC 공시 종목(ETF·우선주·워런트·유닛·펀드 제외), 6개월(126거래일) 이상 거래, 주가 $2 초과.
주가는 배당을 반영하지 않은 값(auto_adjust=False)을 쓴다. Barchart 와 같아지는 방식 (2026-11-05 확인).
종목 목록은 나스닥 공식 목록(nasdaqtrader.com). 받지 못하면 지난번 목록(us_symbols.txt)을 쓴다.
Barchart 와 맞춘 기준: 어제=1거래일 전, 1주 전=5거래일 전, 1달 전=20거래일 전. (2026-11-04 비교 차이 0~2%p)
build.py 가 build_breadth 다음에 부른다.
"""
import io, json, re, time
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).parent
OUT = ROOT / 'docs' / 'breadth.json'
CACHE = ROOT / 'us_symbols.txt'
NAMES = ROOT / 'us_names.json'   # 종목 → (영문 이름, 나스닥 상장 여부)
MEMBERS = ROOT / 'docs' / 'members.json'
MAS = [5, 20, 50, 100, 150, 200]
BACK = {'오늘': 0, '어제': 1, '1주 전': 5, '1달 전': 20}
BAD = re.compile(r'warrant|\bunits?\b|\bright(s)?\b|preferred|\bnotes?\b|debenture|% |subordinated|'
                 r'acquisition corp|beneficial interest|closed end|fund\b', re.I)


def symbols():
    try:
        rows = []
        for f, sym in (('nasdaqlisted', 'Symbol'), ('otherlisted', 'ACT Symbol')):
            r = requests.get(f'https://www.nasdaqtrader.com/dynamic/SymDir/{f}.txt', timeout=30)
            r.raise_for_status()
            d = pd.read_csv(io.StringIO(r.text), sep='|')[:-1]
            d = d[(d['ETF'] == 'N') & (d['Test Issue'] == 'N')]
            rows += [(s, n, f == 'nasdaqlisted') for s, n in zip(d[sym], d['Security Name'])]
        names = {str(s).replace('.', '-'): [re.split(r' - | Common Stock| Class [A-Z] ', n)[0].strip(), nq] for s, n, nq in rows
                 if isinstance(s, str) and isinstance(n, str) and not BAD.search(n)
                 and re.fullmatch(r'[A-Z]+(\.[A-Z])?', s)}
        tick = sorted(names)
        if len(tick) > 3000:
            CACHE.write_text('\n'.join(tick))
            NAMES.write_text(json.dumps(names, ensure_ascii=False, separators=(',', ':')))
            return tick
    except Exception as e:
        print('미국 종목 목록 받기 실패, 지난 목록 사용:', e)
    return CACHE.read_text().split()


def build_market_average():
    tick = symbols()
    start = (pd.Timestamp.today() - pd.DateOffset(days=420)).strftime('%Y-%m-%d')
    names = json.loads(NAMES.read_text()) if NAMES.exists() else {}
    try:
        from index_lists import build_lists
        lists = build_lists([t for t, v in names.items() if v[1]])
    except Exception as e:
        print('지수 목록 실패:', e); lists = {}
    extra = sorted({t for v in lists.values() for t in v} - set(tick))
    allt = tick + extra
    frames, vols = [], []
    for i in range(0, len(allt), 400):
        for n in range(3):
            try:
                raw = yf.download(allt[i:i + 400], start=start, progress=False, threads=True, auto_adjust=False)
                frames.append(raw['Close']); vols.append(raw['Volume'])
                break
            except Exception as e:
                print('받기 재시도', i, e); time.sleep(10)
    full = pd.concat(frames, axis=1).dropna(how='all')
    fvol = pd.concat(vols, axis=1).reindex(full.index)
    while full.iloc[-1].notna().mean() < 0.5:
        full = full.iloc[:-1]
    fvol = fvol.reindex(full.index)
    close = full[[t for t in tick if t in full]]
    # 마지막 날 값이 절반도 안 찬 날(야후가 아직 안 채움)은 버린다
    while close.iloc[-1].notna().mean() < 0.5:
        close = close.iloc[:-1]
    hist = close.notna().cumsum()
    roll = {n: close.rolling(n, min_periods=n).mean() for n in MAS}

    def pick(back):
        i = len(close) - 1 - back
        last = close.iloc[i]
        ok = (last > 2) & (hist.iloc[i] >= 126)
        row = {}
        for n in MAS:
            ma = roll[n].iloc[i]
            v = ok & ma.notna() & last.notna()
            row[str(n)] = round(float(((last > ma) & v).sum() / v.sum() * 100), 1)
        return row, int(ok.sum())

    table, count = {}, 0
    for k, b in BACK.items():
        table[k], c = pick(b)
        count = count or c
    data = json.loads(OUT.read_text())
    data['market'] = {'date': close.index[-1].strftime('%Y-%m-%d'), 'count': count, 'table': table}
    if lists:
        try:
            build_indexes(data, full, fvol, lists, names)
        except Exception as e:
            print('지수별 표 실패:', e)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    print(f"시장 흐름(미국 전체): {count}개 종목, 50일선 위 {table['오늘']['50']}%, 200일선 위 {table['오늘']['200']}%")


def build_indexes(data, full, fvol, lists, names):
    """Barchart 아래쪽 표(지수별)와 지수 구성 종목 페이지용 members.json"""
    from index_lists import TABLES
    roll = {n: full.rolling(n, min_periods=n).mean() for n in MAS}
    L = len(full) - 1
    above = {n: (full > roll[n]) & roll[n].notna() & full.notna() for n in MAS}

    hist = full.notna().cumsum()

    def table(cols, strict=False):
        out = {}
        for k, b in BACK.items():
            i = L - b
            row = {}
            for n in MAS:
                v = roll[n].iloc[i][cols].notna() & full.iloc[i][cols].notna()
                if strict:  # 나스닥 종합: 주가 $5 초과·6개월 이상 거래 종목 (2026-11-04 Barchart 와 0~2%p 로 가장 가까운 기준)
                    v &= (full.iloc[i][cols] > 5) & (hist.iloc[i][cols] >= 126)
                row[str(n)] = round(float(above[n].iloc[i][cols][v].sum() / max(v.sum(), 1) * 100), 1)
            out[k] = row
        return out

    ko = {}
    try:
        d = json.loads((ROOT / 'docs' / 'data.json').read_text())
        ko = {s['ticker'].replace('.', '-'): s['name'] for m in d['markets'] for s in m['stocks']}
    except Exception:
        pass
    groups, tables = {}, []
    for title, title_ko, rows in TABLES:
        out = []
        for key, name in rows:
            cols = [t for t in lists.get(key, []) if t in full]
            if not cols:
                continue
            groups[key] = cols
            out.append({'key': key, 'name': name, 'count': len(cols), 'table': table(cols, key == 'comp')})
        tables.append({'title': title, 'ko': title_ko, 'rows': out})
    data['indexes'] = tables
    used = sorted({t for v in groups.values() for t in v})
    last, prev, vol = full.iloc[L], full.iloc[L - 1], fvol.iloc[L]
    stocks = {}
    for t in used:
        if pd.isna(last[t]):
            continue
        flags = sum(1 << j for j, n in enumerate(MAS) if bool(above[n].iloc[L][t]))
        chg = None if pd.isna(prev[t]) or not prev[t] else round(float(last[t] / prev[t] * 100 - 100), 2)
        stocks[t] = [ko.get(t) or (names.get(t) or [t])[0], round(float(last[t]), 2), chg,
                     None if pd.isna(vol[t]) else int(vol[t]), flags]
    MEMBERS.write_text(json.dumps({'date': full.index[L].strftime('%Y-%m-%d'), 'stocks': stocks, 'groups': groups},
                                  ensure_ascii=False, separators=(',', ':')))
    print('지수별 표:', ', '.join(f"{r['name']} {r['count']}" for tb in tables for r in tb['rows'][:3]))


if __name__ == '__main__':
    build_market_average()
