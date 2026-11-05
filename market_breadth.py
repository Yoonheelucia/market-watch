"""미국 주식 전체로 '이동평균선 위 종목 비율'을 계산해 docs/breadth.json 의 market 칸에 넣는다.

Barchart Market Performance 의 'MARKET AVERAGE'($BCMM)와 같은 기준:
  SEC 공시 종목(ETF·우선주·워런트·유닛·펀드 제외), 6개월(126거래일) 이상 거래, 주가 $2 초과.
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
            rows += list(zip(d[sym], d['Security Name']))
        tick = sorted({str(s).replace('.', '-') for s, n in rows
                       if isinstance(s, str) and isinstance(n, str) and not BAD.search(n)
                       and re.fullmatch(r'[A-Z]+(\.[A-Z])?', s)})
        if len(tick) > 3000:
            CACHE.write_text('\n'.join(tick))
            return tick
    except Exception as e:
        print('미국 종목 목록 받기 실패, 지난 목록 사용:', e)
    return CACHE.read_text().split()


def build_market_average():
    tick = symbols()
    start = (pd.Timestamp.today() - pd.DateOffset(days=420)).strftime('%Y-%m-%d')
    frames = []
    for i in range(0, len(tick), 400):
        for n in range(3):
            try:
                frames.append(yf.download(tick[i:i + 400], start=start, progress=False, threads=True, auto_adjust=True)['Close'])
                break
            except Exception as e:
                print('받기 재시도', i, e); time.sleep(10)
    close = pd.concat(frames, axis=1).dropna(how='all')
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
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    print(f"시장 흐름(미국 전체): {count}개 종목, 50일선 위 {table['오늘']['50']}%, 200일선 위 {table['오늘']['200']}%")


if __name__ == '__main__':
    build_market_average()
