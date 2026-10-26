"""S&P500 / 나스닥 / 코스피 / 코스닥 / 다우 상위 종목 데이터를 받아 docs/data.json 으로 저장한다.

GitHub Actions 가 매일 아침 이 스크립트를 실행하고, docs/index.html 이 data.json 을 읽어 차트를 그린다.
종목을 바꾸고 싶으면 아래 MARKETS 의 목록만 수정하면 된다.
"""
import json
import math
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from earnings import build_earnings
from segments import build_segments

DAYS = 90  # 차트 기간 (달력 기준 일수)

KOSPI_NAMES = {
    '005930': '삼성전자', '000660': 'SK하이닉스', '207940': '삼성바이오로직스',
    '035420': 'NAVER', '051910': 'LG화학', '005380': '현대차',
    '068270': '셀트리온', '035720': '카카오', '028260': '삼성물산',
    '012330': '현대모비스', '006400': '삼성SDI', '096770': 'SK이노베이션',
    '017670': 'SK텔레콤', '105560': 'KB금융', '034730': 'SK',
    '066570': 'LG전자', '015760': '한국전력', '018260': '삼성에스디에스',
    '032830': '삼성생명', '011170': '롯데케미칼', '055550': '신한지주',
    '051900': 'LG생활건강', '036570': '엔씨소프트', '034020': '두산에너빌리티',
    '018880': '한온시스템', '090430': '아모레퍼시픽', '010950': 'S-Oil',
    '010130': '고려아연', '011070': 'LG이노텍', '010140': '삼성중공업',
    '086790': '하나금융지주', '035250': '강원랜드', '161390': '한국타이어앤테크놀로지',
    '138930': 'BNK금융지주', '010060': 'OCI홀딩스', '097950': 'CJ제일제당',
    '251270': '넷마블', '009540': 'HD한국조선해양', '282330': 'BGF리테일',
    '028670': '팬오션', '011780': '금호석유화학', '014820': '동원시스템즈',
    '005490': 'POSCO홀딩스', '373220': 'LG에너지솔루션', '011790': 'SKC',
    '024110': '기업은행', '004020': '현대제철', '003490': '대한항공',
    '001040': 'CJ', '267250': 'HD현대',
}

KOSDAQ_NAMES = {
    '196170': '알테오젠', '247540': '에코프로비엠', '086520': '에코프로',
    '028300': 'HLB', '277810': '레인보우로보틱스', '141080': '리가켐바이오',
    '000250': '삼천당제약', '145020': '휴젤', '214150': '클래시스',
    '214450': '파마리서치', '087010': '펩트론', '298380': '에이비엘바이오',
    '950160': '코오롱티슈진', '058470': '리노공업', '039030': '이오테크닉스',
    '257720': '실리콘투', '310210': '보로노이', '068760': '셀트리온제약',
    '348370': '엔켐', '357780': '솔브레인', '403870': 'HPSP',
    '240810': '원익IPS', '095340': 'ISC', '036930': '주성엔지니어링',
    '005290': '동진쎄미켐', '214370': '케어젠', '263750': '펄어비스',
    '293490': '카카오게임즈', '035900': 'JYP Ent.', '041510': '에스엠',
}

NASDAQ = [
    'AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'TSLA', 'GOOG', 'AVGO', 'PEP',
    'COST', 'ADBE', 'CSCO', 'AMD', 'NFLX', 'TMUS', 'TXN', 'HON', 'QCOM', 'INTC',
    'AMGN', 'AMAT', 'INTU', 'SBUX', 'ADI', 'MU', 'MDLZ', 'GILD', 'ISRG', 'BKNG',
    'ADP', 'REGN', 'VRTX', 'LRCX', 'MRNA', 'PANW', 'SNPS', 'ASML', 'KLAC', 'FTNT',
    'CSX', 'MELI', 'MRVL', 'NXPI', 'PAYX', 'LULU', 'ROST', 'KDP', 'CDNS',
]

SP500 = [
    'AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'TSLA', 'GOOG', 'UNH', 'JNJ',
    'XOM', 'JPM', 'V', 'PG', 'LLY', 'MA', 'HD', 'CVX', 'MRK', 'PEP',
    'ABBV', 'KO', 'AVGO', 'COST', 'MCD', 'TMO', 'WMT', 'BAC', 'PFE', 'DIS',
    'CSCO', 'ADBE', 'NFLX', 'ABT', 'CRM', 'DHR', 'LIN', 'ACN', 'VZ', 'NEE',
    'TXN', 'NKE', 'WFC', 'PM', 'HON', 'ORCL', 'MS', 'INTC', 'AMD', 'UPS', 'LOW',
]

US_NAMES = {
    'AAPL': '애플', 'MSFT': '마이크로소프트', 'NVDA': '엔비디아', 'AMZN': '아마존',
    'META': '메타', 'TSLA': '테슬라', 'GOOG': '알파벳(구글)', 'AVGO': '브로드컴',
    'PEP': '펩시코', 'COST': '코스트코', 'ADBE': '어도비', 'CSCO': '시스코',
    'AMD': 'AMD', 'NFLX': '넷플릭스', 'TMUS': 'T모바일 US', 'TXN': '텍사스인스트루먼트',
    'HON': '하니웰', 'QCOM': '퀄컴', 'INTC': '인텔', 'AMGN': '암젠',
    'AMAT': '어플라이드머티리얼즈', 'INTU': '인튜이트', 'SBUX': '스타벅스', 'ADI': '아날로그디바이스',
    'MU': '마이크론', 'MDLZ': '몬델리즈', 'GILD': '길리어드', 'ISRG': '인튜이티브서지컬',
    'BKNG': '부킹홀딩스', 'ADP': 'ADP', 'REGN': '리제네론', 'VRTX': '버텍스',
    'LRCX': '램리서치', 'MRNA': '모더나', 'PANW': '팔로알토네트웍스', 'SNPS': '시놉시스',
    'ASML': 'ASML', 'KLAC': 'KLA', 'FTNT': '포티넷', 'CSX': 'CSX',
    'MELI': '메르카도리브레', 'MRVL': '마벨테크놀로지', 'NXPI': 'NXP반도체', 'PAYX': '페이첵스',
    'LULU': '룰루레몬', 'ROST': '로스스토어스', 'KDP': '큐리그닥터페퍼', 'CDNS': '케이던스',
    'UNH': '유나이티드헬스', 'JNJ': '존슨앤드존슨', 'XOM': '엑슨모빌', 'JPM': 'JP모건',
    'V': '비자', 'PG': 'P&G', 'LLY': '일라이릴리', 'MA': '마스터카드',
    'HD': '홈디포', 'CVX': '셰브론', 'MRK': '머크', 'ABBV': '애브비',
    'KO': '코카콜라', 'MCD': '맥도날드', 'TMO': '써모피셔', 'WMT': '월마트',
    'BAC': '뱅크오브아메리카', 'PFE': '화이자', 'DIS': '디즈니', 'ABT': '애보트',
    'CRM': '세일즈포스', 'DHR': '다나허', 'LIN': '린데', 'ACN': '액센츄어',
    'VZ': '버라이즌', 'NEE': '넥스트에라에너지', 'NKE': '나이키', 'WFC': '웰스파고',
    'PM': '필립모리스', 'ORCL': '오라클', 'MS': '모건스탠리', 'UPS': 'UPS', 'LOW': '로우스',
    'AXP': '아메리칸익스프레스', 'BA': '보잉', 'CAT': '캐터필러', 'GS': '골드만삭스',
    'IBM': 'IBM', 'MMM': '3M', 'SHW': '셔윈윌리엄스', 'TRV': '트래블러스',
}

DOW = [
    'AAPL', 'AMGN', 'AMZN', 'AXP', 'BA', 'CAT', 'CRM', 'CSCO', 'CVX', 'DIS',
    'GS', 'HD', 'HON', 'IBM', 'JNJ', 'JPM', 'KO', 'MCD', 'MMM', 'MRK',
    'MSFT', 'NKE', 'NVDA', 'PG', 'SHW', 'TRV', 'UNH', 'V', 'VZ', 'WMT',
]

MARKETS = [
    {'id': 'sp500', 'label': 'S&P 500', 'currency': 'USD',
     'index': ('^GSPC', 'S&P 500'), 'pe_etf': 'SPY',
     'stocks': [(s, US_NAMES.get(s, s)) for s in SP500]},
    {'id': 'nasdaq', 'label': '나스닥', 'currency': 'USD',
     'index': ('^IXIC', 'NASDAQ'), 'pe_etf': 'ONEQ',
     'stocks': [(s, US_NAMES.get(s, s)) for s in NASDAQ]},
    {'id': 'kospi', 'label': '코스피', 'currency': 'KRW',
     'index': ('^KS11', 'KOSPI'),
     'stocks': [(f'{code}.KS', name) for code, name in KOSPI_NAMES.items()]},
    {'id': 'kosdaq', 'label': '코스닥', 'currency': 'KRW',
     'index': ('^KQ11', 'KOSDAQ'),
     'stocks': [(f'{code}.KQ', name) for code, name in KOSDAQ_NAMES.items()]},
    {'id': 'dow', 'label': '다우', 'currency': 'USD',
     'index': ('^DJI', 'Dow Jones'), 'pe_etf': 'DIA',
     'stocks': [(s, US_NAMES.get(s, s)) for s in DOW]},
]

warnings.filterwarnings('ignore')

OUT = Path(__file__).parent / 'docs' / 'data.json'
EARNINGS_OUT = OUT.with_name('earnings.json')


def clean(values, digits):
    return [None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), digits)
            for v in values]


def download(tickers, start, **kw):
    raw = yf.download(tickers, start=start, group_by='ticker', progress=False, threads=True, **kw)

    # 야후가 가끔 일부 종목을 빈 값으로 돌려주므로, 비어 있는 종목만 한 번 더 받는다
    empty = [t for t in tickers if raw[t]['Close'].notna().sum() == 0]
    if empty:
        time.sleep(3)
        retry = yf.download(empty, start=start, group_by='ticker', progress=False, threads=False, **kw)
        for t in empty:
            got = retry[t]
            if got['Close'].notna().any():
                raw = raw.drop(columns=t, level=0).join(pd.concat({t: got}, axis=1), how='outer')
    return raw


def index_pe(etf):
    """지수 자체의 PER 은 야후에 없어서, 지수를 그대로 따라가는 ETF 의 PER 을 쓴다."""
    try:
        v = yf.Ticker(etf).info.get('trailingPE')
        return round(float(v), 1) if v else None
    except Exception:
        return None


def usd_krw():
    for attempt in range(2):
        try:
            v = yf.Ticker('KRW=X').history(period='5d')['Close'].dropna().iloc[-1]
            return round(float(v), 2)
        except Exception:
            time.sleep(2)
    return None


def market_cap(ticker):
    for attempt in range(2):
        try:
            v = yf.Ticker(ticker).fast_info['marketCap']
            return None if v is None or math.isnan(v) else float(v)
        except Exception:
            time.sleep(2)
    return None


def add_market_caps(markets):
    """종목별 시총을 붙이고, 각 시장 목록 안에서 시총 순위를 매긴다."""
    tickers = sorted({s['ticker'] for m in markets for s in m['stocks']})
    with ThreadPoolExecutor(4) as ex:
        caps = dict(zip(tickers, ex.map(market_cap, tickers)))
    print(f"시총: {sum(v is not None for v in caps.values())}/{len(tickers)}개 종목")
    for m in markets:
        for s in m['stocks']:
            s['cap'] = caps[s['ticker']]
        ranked = sorted((s for s in m['stocks'] if s['cap']), key=lambda s: -s['cap'])
        for rank, s in enumerate(ranked, 1):
            s['rank'] = rank


def build_market(m, start):
    index_ticker, index_name = m['index']
    tickers = [index_ticker] + [t for t, _ in m['stocks']]
    raw = download(tickers, start)

    index = raw[index_ticker][['Close']].dropna()
    if index.empty:
        raise RuntimeError(f"{m['label']} 지수 데이터를 받지 못했습니다 ({index_ticker})")
    dates = index.index
    digits = 0 if m['currency'] == 'KRW' else 2

    stocks, missing = [], []
    for ticker, name in m['stocks']:
        df = raw[ticker][['Open', 'High', 'Low', 'Close']].reindex(dates)
        if df['Close'].notna().sum() < len(dates) * 0.5:
            missing.append(ticker)
            continue
        stocks.append({
            'ticker': ticker, 'name': name,
            'o': clean(df['Open'], digits), 'h': clean(df['High'], digits),
            'l': clean(df['Low'], digits), 'c': clean(df['Close'], digits),
        })

    if len(stocks) < len(m['stocks']) * 0.5:
        raise RuntimeError(f"{m['label']} 종목 절반 이상이 비어 있습니다: {missing}")
    print(f"{m['label']}: {len(stocks)}개 종목, {len(dates)}거래일, 누락 {missing}")

    return {
        'id': m['id'], 'label': m['label'], 'currency': m['currency'],
        'dates': [d.strftime('%Y-%m-%d') for d in dates],
        'index': {'ticker': index_ticker, 'name': index_name, 'c': clean(index['Close'], 2)},
        'stocks': stocks, 'missing': missing,
    }


def main():
    start = (pd.Timestamp.today() - pd.DateOffset(days=DAYS)).strftime('%Y-%m-%d')
    data = {
        'updated': datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M KST'),
        'start': start,
        'markets': [build_market(m, start) for m in MARKETS],
    }
    add_market_caps(data['markets'])
    for m, spec in zip(data['markets'], MARKETS):
        if spec.get('pe_etf'):
            m['index']['pe'] = {'value': index_pe(spec['pe_etf']), 'etf': spec['pe_etf']}
    data['usdkrw'] = usd_krw()
    print(f"원/달러 환율: {data['usdkrw']}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    print(f'저장: {OUT} ({OUT.stat().st_size // 1024} KB)')

    names = {s['ticker']: s['name'] for m in data['markets'] for s in m['stocks']}
    earnings = {'updated': data['updated'], 'stocks': build_earnings(names, download, EARNINGS_OUT)}
    EARNINGS_OUT.write_text(json.dumps(earnings, ensure_ascii=False, separators=(',', ':')))
    print(f'저장: {EARNINGS_OUT} ({EARNINGS_OUT.stat().st_size // 1024} KB)')

    # 미국 종목 사업부별 분기 매출 (SEC 공시)
    build_segments(sorted(t for t in names if not t.endswith(('.KS', '.KQ'))))


if __name__ == '__main__':
    main()
