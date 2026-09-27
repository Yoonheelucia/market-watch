"""코스피 / 나스닥 / S&P500 상위 종목 데이터를 받아 docs/data.json 으로 저장한다.

GitHub Actions 가 매일 아침 이 스크립트를 실행하고, docs/index.html 이 data.json 을 읽어 차트를 그린다.
종목을 바꾸고 싶으면 아래 MARKETS 의 목록만 수정하면 된다.
"""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

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

MARKETS = [
    {'id': 'kospi', 'label': '코스피', 'currency': 'KRW',
     'index': ('^KS11', 'KOSPI'),
     'stocks': [(f'{code}.KS', name) for code, name in KOSPI_NAMES.items()]},
    {'id': 'nasdaq', 'label': '나스닥', 'currency': 'USD',
     'index': ('^IXIC', 'NASDAQ'),
     'stocks': [(s, s) for s in NASDAQ]},
    {'id': 'sp500', 'label': 'S&P 500', 'currency': 'USD',
     'index': ('^GSPC', 'S&P 500'),
     'stocks': [(s, s) for s in SP500]},
]

OUT = Path(__file__).parent / 'docs' / 'data.json'


def clean(values, digits):
    return [None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), digits)
            for v in values]


def build_market(m, start):
    index_ticker, index_name = m['index']
    tickers = [index_ticker] + [t for t, _ in m['stocks']]
    raw = yf.download(tickers, start=start, group_by='ticker', progress=False, threads=True)

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
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    print(f'저장: {OUT} ({OUT.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()
