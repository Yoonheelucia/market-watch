"""S&P 500 전체 종목으로 '시장 흐름(브레드스)' 지표를 계산해 docs/breadth.json 으로 저장한다.

Barchart 의 Market Performance Indicator 와 같은 방식이다 (대상 종목만 S&P 500 으로 좁힘).
- 이동평균선 위 종목 비율: 5·20·50·100·150·200일선, 오늘·어제·1주 전·1달 전, 그리고 1년 추이
- 신고가·신저가 종목 수: 5일·1달·3달·6달·52주·연초 이후
- 상승·하락 종목 수, 거래대금(주가 × 거래량) 상위 종목
build.py 가 호출한다.
"""
import io
import json
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf
from yfinance import EquityQuery as Q

OUT = Path(__file__).parent / 'docs' / 'breadth.json'
LIST_CACHE = Path(__file__).parent / 'sp500.csv'
LIST_URL = 'https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv'
MAS = [5, 20, 50, 100, 150, 200]
WINDOWS = [('5일', 5), ('1달', 21), ('3달', 63), ('6달', 126), ('52주', 252)]
HISTORY = 252  # 추이 그래프 기간 (거래일)


def constituents():
    """S&P 500 종목 목록. 받아오지 못하면 지난번에 저장한 목록을 쓴다."""
    try:
        r = requests.get(LIST_URL, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        if len(df) > 450:
            df.to_csv(LIST_CACHE, index=False)
    except Exception:
        df = pd.read_csv(LIST_CACHE)
    return {row['Symbol'].replace('.', '-'): row['Security'] for _, row in df.iterrows()}


def market_leaders(korean_names, count=15):
    """미국 상장 주식 전체에서 거래대금(주가 × 거래량) 상위 종목.
    전체 5,000여 종목을 매일 받는 대신, 야후 종목 검색기로 거래량 상위 500개와 시총 상위 500개를 받아
    그 안에서 거래대금 순으로 정렬한다. 거래대금 상위 종목은 거의 항상 이 두 묶음 안에 있다."""
    q = Q('and', [Q('eq', ['region', 'us']), Q('gt', ['intradayprice', 2]),
                  Q('is-in', ['exchange', 'NMS', 'NYQ', 'NGM', 'NCM', 'ASE', 'PCX', 'BTS'])])
    rows = {}
    for sort in ('dayvolume', 'intradaymarketcap'):
        for offset in (0, 250):
            for x in yf.screen(q, sortField=sort, sortAsc=False, size=250, offset=offset).get('quotes', []):
                p, v = x.get('regularMarketPrice'), x.get('regularMarketVolume')
                if x.get('quoteType') == 'EQUITY' and p and v:
                    rows[x['symbol']] = x
    top = sorted(rows.values(), key=lambda x: -x['regularMarketPrice'] * x['regularMarketVolume'])[:count]
    return [{
        'ticker': x['symbol'], 'name': korean_names.get(x['symbol']) or (x.get('shortName') or x['symbol']).strip(),
        'price': round(x['regularMarketPrice'], 2), 'chg': round(x.get('regularMarketChangePercent') or 0, 2),
        'volume': int(x['regularMarketVolume']), 'pv': round(x['regularMarketPrice'] * x['regularMarketVolume'] / 1e6),
    } for x in top]


def build_breadth(download, korean_names):
    names = constituents()
    tickers = sorted(names)
    start = (pd.Timestamp.today() - pd.DateOffset(days=760)).strftime('%Y-%m-%d')
    raw = download(tickers + ['^GSPC'], start, auto_adjust=True)

    close = pd.DataFrame({t: raw[t]['Close'] for t in tickers}).dropna(how='all')
    high = pd.DataFrame({t: raw[t]['High'] for t in tickers}).reindex(close.index)
    low = pd.DataFrame({t: raw[t]['Low'] for t in tickers}).reindex(close.index)
    vol = pd.DataFrame({t: raw[t]['Volume'] for t in tickers}).reindex(close.index)
    index = raw['^GSPC']['Close'].reindex(close.index)
    dates = close.index

    # 이동평균선 위 비율 (해당 기간만큼 거래 이력이 있는 종목만 센다)
    above = {}
    for n in MAS:
        ma = close.rolling(n, min_periods=n).mean()
        valid = ma.notna() & close.notna()
        above[n] = ((close > ma) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, pd.NA) * 100

    def pick(back):
        i = len(dates) - 1 - back
        return {str(n): round(float(above[n].iloc[i]), 1) for n in MAS}

    table = {'오늘': pick(0), '어제': pick(1), '1주 전': pick(5), '1달 전': pick(21)}

    # 신고가·신저가: 오늘 고가(저가)가 직전 N-1 거래일의 최고(최저)보다 높으면(낮으면)
    last = len(dates) - 1
    hl = []
    year_start = dates[dates.year == dates[-1].year][0]
    windows = WINDOWS + [('연초 이후', last - dates.get_loc(year_start) + 1)]
    for label, n in windows:
        prev_hi = high.iloc[last - n + 1:last].max()
        prev_lo = low.iloc[last - n + 1:last].min()
        hi = int((high.iloc[last] > prev_hi).sum())
        lo = int((low.iloc[last] < prev_lo).sum())
        hl.append({'label': label, 'highs': hi, 'lows': lo})

    chg = close.iloc[-1] / close.iloc[-2] - 1
    adv = {'up': int((chg > 0).sum()), 'flat': int((chg == 0).sum()), 'down': int((chg < 0).sum())}

    try:
        leaders = market_leaders(korean_names)
        leaders_scope = 'us'
    except Exception as e:
        print(f'거래대금 상위(미국 전체) 실패, S&P 500 으로 대신함: {e}')
        leaders, leaders_scope = None, 'sp500'
    pv = (close.iloc[-1] * vol.iloc[-1]).dropna().sort_values(ascending=False).head(15)
    leaders = leaders or [{
        'ticker': t, 'name': korean_names.get(t) or names[t], 'en': names[t],
        'price': round(float(close[t].iloc[-1]), 2), 'chg': round(float(chg[t] * 100), 2),
        'volume': int(vol[t].iloc[-1]), 'pv': round(float(v) / 1e6),  # 백만 달러
    } for t, v in pv.items()]

    hist = dates[-HISTORY:]
    data = {
        'date': dates[-1].strftime('%Y-%m-%d'), 'count': int(close.iloc[-1].notna().sum()),
        'table': table, 'highsLows': hl, 'advance': adv, 'leaders': leaders, 'leadersScope': leaders_scope,
        'history': {
            'dates': [d.strftime('%Y-%m-%d') for d in hist],
            **{str(n): [None if pd.isna(v) else round(float(v), 1) for v in above[n].loc[hist]] for n in (20, 50, 200)},
            'index': [None if pd.isna(v) else round(float(v), 2) for v in index.loc[hist]],
        },
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    print(f"시장 흐름: S&P 500 {data['count']}개 종목, 50일선 위 {table['오늘']['50']}%, 200일선 위 {table['오늘']['200']}%")
