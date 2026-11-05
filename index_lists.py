"""Barchart Market Performance 아래쪽 표(More S&P / Russell / Dow Jones / Nasdaq Indexes)에 쓰는 지수별 종목 목록.

받지 못하면 lists_cache.json 에 저장된 지난 목록을 쓴다.
- S&P 500 업종: sp500.csv (breadth.py 가 받음)
- S&P 100·400·600, Nasdaq 100: 위키백과 구성 종목 표
- S&P 500 Growth·Value·ESG: SPDR ETF(SPYG·SPYV·EFIV) 보유 종목 (같은 지수를 그대로 따르는 ETF)
- Dow Industrials: docs/data.json 의 다우 30종목
- Nasdaq Composite: 나스닥 공식 목록 중 나스닥 상장 보통주 (market_breadth 가 넘겨줌)
- Russell 1000·2000·3000: 공식 목록을 받을 수 없어 미국 상장 주식 시가총액 1~1000위 / 1001~3000위 / 1~3000위로 근사
"""
import io, json
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).parent
CACHE = ROOT / 'lists_cache.json'
UA = {'User-Agent': 'market-watch/1.0 (github.com/Yoonheelucia/market-watch)'}
SSGA = 'https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{}.xlsx'
SECTORS = ['Consumer Discretionary', 'Consumer Staples', 'Energy', 'Financials', 'Health Care', 'Industrials',
           'Information Technology', 'Materials', 'Real Estate', 'Communication Services', 'Utilities']
SECTOR_SHORT = {'Communication Services': 'Comm Services'}


def norm(t):
    return str(t).strip().upper().replace('.', '-').replace('/', '-')


def wiki(page, col):
    h = requests.get('https://en.wikipedia.org/wiki/' + page, headers=UA, timeout=30).text
    for t in pd.read_html(io.StringIO(h)):
        if col in [str(c) for c in t.columns] and len(t) >= 90:
            return sorted({norm(x) for x in t[col].dropna()})
    raise ValueError(page + ' 표를 찾지 못함')


def ssga(fund):
    x = pd.read_excel(io.BytesIO(requests.get(SSGA.format(fund), headers=UA, timeout=60).content), header=None)
    head = next(i for i in range(15) if 'Ticker' in [str(v).strip() for v in x.iloc[i]])
    x.columns = [str(v).strip() for v in x.iloc[head]]
    x = x.iloc[head + 1:]
    return sorted({norm(t) for t in x['Ticker'].dropna() if str(t).strip() not in ('-', 'CASH_USD', 'nan') and str(t).strip().isascii()
                   and len(str(t).strip()) <= 6})


def russell(n_skip, n_take):
    """시가총액 순위로 러셀 지수 근사 (보통주, 주요 거래소)"""
    import yfinance as yf
    from yfinance import EquityQuery as Q
    q = Q('and', [Q('eq', ['region', 'us']), Q('is-in', ['exchange', 'NMS', 'NYQ', 'NGM', 'NCM', 'ASE'])])
    out = []
    for off in range(0, 3250, 250):
        r = yf.screen(q, sortField='intradaymarketcap', sortAsc=False, size=250, offset=off).get('quotes', [])
        out += [norm(x['symbol']) for x in r if x.get('quoteType') == 'EQUITY' and x.get('marketCap')]
        if not r:
            break
    out = list(dict.fromkeys(out))
    if len(out) < 2900:
        raise ValueError('시가총액 순위가 모자람')
    return out


def build_lists(nasdaq_listed):
    old = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    lists = {}

    def get(key, fn):
        try:
            v = fn()
            if len(v) < 20:
                raise ValueError('너무 적음')
            lists[key] = v
        except Exception as e:
            print(f'지수 목록 {key} 받기 실패, 지난 목록 사용: {e}')
            if key in old:
                lists[key] = old[key]

    sp = pd.read_csv(ROOT / 'sp500.csv')
    sp['t'] = sp['Symbol'].map(norm)
    lists['sp500'] = sorted(sp['t'])
    for s in SECTORS:
        lists['sp500:' + s] = sorted(sp.loc[sp['GICS Sector'] == s, 't'])
    get('sp100', lambda: wiki('S%26P_100', 'Symbol'))
    get('sp400', lambda: wiki('List_of_S%26P_400_companies', 'Symbol'))
    get('sp600', lambda: wiki('List_of_S%26P_600_companies', 'Symbol'))
    get('ndx', lambda: wiki('List_of_NASDAQ-100_companies', 'Ticker'))
    get('spesg', lambda: ssga('efiv'))
    get('spgrowth', lambda: ssga('spyg'))
    get('spvalue', lambda: ssga('spyv'))
    try:
        d = json.loads((ROOT / 'docs' / 'data.json').read_text())
        lists['dow'] = sorted(norm(s['ticker']) for m in d['markets'] if m['id'] == 'dow' for s in m['stocks'])
    except Exception:
        lists['dow'] = old.get('dow', [])
    lists['comp'] = sorted(nasdaq_listed)

    def rus():
        r = russell(0, 3000)
        return r[:3000]
    get('r3000', rus)
    if 'r3000' in lists:
        lists['r1000'] = lists['r3000'][:1000]
        lists['r2000'] = lists['r3000'][1000:3000]
    CACHE.write_text(json.dumps(lists, separators=(',', ':')))
    return lists


# 화면에 보여 줄 표 (Barchart 와 같은 순서·이름)
TABLES = [
    ('Percentage Of Large Cap Stocks Above Their Moving Averages', '대형주 (S&P 500 업종별)',
     [('sp500', 'S&P 500 Index')] + [('sp500:' + s, 'S&P 500 ' + SECTOR_SHORT.get(s, s)) for s in SECTORS]),
    ('More S&P Indexes', 'S&P 지수', [('sp100', 'S&P 100 Index'), ('sp500', 'S&P 500 Index'), ('spesg', 'S&P 500 ESG Index'),
                                    ('spgrowth', 'S&P 500 Growth Index'), ('spvalue', 'S&P 500 Value Index'),
                                    ('sp400', 'S&P Midcap 400'), ('sp600', 'S&P Smallcap 600')]),
    ('Russell Indexes', '러셀 지수', [('r1000', 'Russell 1000 Index'), ('r2000', 'Russell 2000 Index'), ('r3000', 'Russell 3000 Index')]),
    ('Dow Jones Indexes', '다우 지수', [('dow', 'Dow Industrials')]),
    ('Nasdaq Indexes', '나스닥 지수', [('ndx', 'Nasdaq 100'), ('comp', 'Nasdaq Composite')]),
]
