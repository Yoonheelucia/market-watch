"""브리핑 탭 지도의 '프리장' 보기: 미국 프리장(동부 04:00~09:30) 가격을 받아 어제 종가 대비 등락률을 docs/premarket.json 에 쓴다.

GitHub Actions(premarket.yml)가 프리장 시간에 20분마다 돌린다. 프리장 시간이 아니면 아무것도 하지 않는다 (--force 로 강제 실행).
종목은 docs/heatmap.json 에 있는 지도 종목(S&P 500 · 나스닥 100 · 다우) 그대로.
"""
import datetime as dt, json, sys
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).parent
OUT = ROOT / 'docs' / 'premarket.json'
ET, KST = ZoneInfo('America/New_York'), ZoneInfo('Asia/Seoul')


def main():
    now = dt.datetime.now(ET)
    if '--force' not in sys.argv and (now.weekday() >= 5 or not dt.time(4, 0) <= now.time() <= dt.time(9, 50)):
        print('프리장 시간이 아니라서 건너뜀', now)
        return
    hm = json.loads((ROOT / 'docs' / 'heatmap.json').read_text())
    ticks = sorted({s[0] for m in hm['maps'].values() for x in m['sectors'] for i in x['ind'] for s in i['s']})
    today = now.date()
    # 야후 시세 조회(100종목씩): 프리장 가격과 마지막 정규장 종가(배당 조정 안 한 값, 지도와 같은 기준)
    from yfinance.data import YfData
    yd, chg, base_day, last = YfData(), {}, None, None
    for k in range(0, len(ticks), 100):
        r = yd.get_raw_json('https://query1.finance.yahoo.com/v7/finance/quote', params={
            'symbols': ','.join(ticks[k:k + 100]),
            'fields': 'preMarketPrice,preMarketTime,regularMarketPrice,regularMarketTime'})
        for q in r['quoteResponse']['result']:
            p, pt, c, ct = (q.get(x) for x in ('preMarketPrice', 'preMarketTime', 'regularMarketPrice', 'regularMarketTime'))
            if not (p and pt and c and ct):
                continue
            pt, ct = dt.datetime.fromtimestamp(pt, ET), dt.datetime.fromtimestamp(ct, ET)
            if pt.date() != today or ct.date() >= today:  # 오늘 프리장 거래가 아니거나, 이미 오늘 정규장 값이면 제외
                continue
            chg[q['symbol']] = round(p / c * 100 - 100, 2)
            base_day = max(base_day or ct.date(), ct.date())
            last = max(last or pt, pt)
    if len(chg) < len(ticks) * 0.3:
        print(f'오늘 프리장 가격이 모자람 ({len(chg)}/{len(ticks)}), 건너뜀'); return
    OUT.write_text(json.dumps({
        'date': today.isoformat(), 'base': base_day.isoformat(),
        'et': last.strftime('%H:%M'), 'kst': last.astimezone(KST).strftime('%H:%M'),
        'chg': chg}, ensure_ascii=False, separators=(',', ':')))
    print(f'프리장 {today} {last:%H:%M} ET 기준, {len(chg)}/{len(ticks)}종목 (기준 종가 {base_day})')


if __name__ == '__main__':
    main()
