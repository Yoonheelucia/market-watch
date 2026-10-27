"""영상 찍기 전에 실제 사이트가 잘 돌아가는지 한 번에 점검한다.

1) 페이지·데이터 파일이 열리는지
2) 데이터가 예정대로 최신인지 (미국·한국 주가, 브리핑, 실적)
3) 각 탭·초보자 페이지가 화면에 제대로 그려지는지 (크롬을 화면 없이 띄워 실제로 그려 본 결과로 확인)

실행 (Stock 폴더에서): .venv/bin/python check_site.py                         (실제 사이트)
                       .venv/bin/python check_site.py http://localhost:8765/   (내 컴퓨터에서 띄운 사이트)
처음 한 번만: python3 -m venv .venv && .venv/bin/pip install playwright  (화면 점검에 컴퓨터의 크롬을 그대로 씀)
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'https://yoonheelucia.github.io/market-watch/').rstrip('/') + '/'
KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)

results = []  # (통과 여부, 항목, 설명)


def check(ok, name, detail=''):
    results.append((bool(ok), name, detail))


def get(path):
    sep = '&' if '?' in path else '?'
    with urllib.request.urlopen(f'{BASE}{path}{sep}nocache={NOW.timestamp():.0f}', timeout=30) as r:
        return r.status, r.read().decode('utf-8')


def kst(s):
    return datetime.strptime(s.replace(' KST', ''), '%Y-%m-%d %H:%M').replace(tzinfo=KST)


def last_scheduled(times, days):
    """가장 최근에 지나간 예정 시각 (days: 0=일 … 6=토)"""
    for back in range(8):
        day = (NOW - timedelta(days=back)).date()
        weekday = (day.weekday() + 1) % 7
        if weekday not in days:
            continue
        for t in sorted(times, reverse=True):
            h, m = map(int, t.split(':'))
            at = datetime(day.year, day.month, day.day, h, m, tzinfo=KST)
            if at <= NOW:
                return at
    return None


def fresh(name, updated, times, days, grace_min=60):
    """예정 시각이 지난 뒤 grace_min 분 넘게 지났는데 그 뒤 업데이트가 없으면 실패"""
    prev = last_scheduled(times, days)
    if prev and NOW - prev > timedelta(minutes=grace_min) and updated < prev - timedelta(minutes=10):
        check(False, name, f'마지막 {updated:%m/%d %H:%M}, 예정 {prev:%m/%d %H:%M} 업데이트가 아직 안 됨')
    else:
        check(True, name, f'마지막 {updated:%m/%d %H:%M}')


# ── 1. 파일이 열리는지 ──
files = {}
for path in ['', 'easy/', 'schedule.js', 'data.json', 'briefing.json', 'earnings.json',
             'business.json', 'segments.json', 'breadth.json']:
    try:
        status, body = get(path)
        files[path] = body
        check(status == 200, f'열림: /{path}', f'{len(body) // 1024} KB')
    except Exception as e:
        check(False, f'열림: /{path}', str(e))

# ── 2. 데이터가 최신인지 ──
if 'data.json' in files:
    data = json.loads(files['data.json'])
    for m in data['markets']:
        kr = m['id'] in ('kospi', 'kosdaq')
        upd = kst(m.get('updated', data['updated']))
        fresh(f"주가 최신: {m['label']}", upd, ['18:03'] if kr else ['06:37'], [1, 2, 3, 4, 5] if kr else [2, 3, 4, 5, 6])
        empty = [s['name'] for s in m['stocks'] if s['c'][-1] is None]
        check(not empty and m['index']['c'][-1] is not None, f"마지막 날 값: {m['label']}",
              f"{m['dates'][-1]} 기준" + (f", 빈 종목 {len(empty)}개: {', '.join(empty[:5])}" if empty else ''))
    check(data.get('usdkrw'), '환율', f"{data.get('usdkrw')}")

if 'briefing.json' in files:
    b = json.loads(files['briefing.json'])
    upd = kst(b.get('updated') or b['asOf'] + ' 00:00')
    fresh('브리핑 최신', upd, ['02:00', '06:30', '11:00', '15:00', '19:00', '22:00', '23:30'], list(range(7)), grace_min=40)
    easy = b.get('easy', {})
    check(b.get('factors') and b.get('week') is not None and b.get('month'), '브리핑 내용', f"요인 {len(b.get('factors', []))}개, 이번 주 {len(b.get('week', []))}일, 한 달 {len(b.get('month', []))}줄")
    check('weekPast' in b, '지난 일정·주가 반응', f"{sum(len(d['items']) for d in b.get('weekPast') or [])}건")
    check(easy.get('why') and easy.get('news') and easy.get('week'), '초보자용 브리핑', f"이유 {len(easy.get('why', []))}줄, 소식 {len(easy.get('news', []))}개")

if 'earnings.json' in files:
    e = json.loads(files['earnings.json'])
    check(len(e['stocks']) >= 150, '실적 조회 종목 수', f"{len(e['stocks'])}개")
    check('VRT' in e['stocks'], '실적 조회: 버티브홀딩스')

# ── 3. 화면이 제대로 그려지는지 (설치된 크롬을 아이패드 화면 크기로 띄워 실제로 눌러 본다) ──
ODD = re.compile(r'불러오지 못했|찾지 못했습니다|undefined|NaN')
pages = [
    # (이름, 주소, 다 그려졌다고 볼 요소, 최소 개수)
    ('S&P 500 탭', '#sp500', '#tbody tr', 40),
    ('나스닥 탭', '#nasdaq', '#tbody tr', 40),
    ('다우 탭', '#dow', '#tbody tr', 25),
    ('코스피 탭', '#kospi', '#tbody tr', 40),
    ('코스닥 탭', '#kosdaq', '#tbody tr', 25),
    ('브리핑·일정 탭', '#brief', '.factor', 5),
    ('시장 흐름 탭', '#breadth', '.br-table', 1),
    ('실적 조회: 애플', '#earnings/AAPL', '.er-head', 1),
    ('실적 조회: 삼성전자', '#earnings/005930.KS', '.er-head', 1),
    ('실적 조회: 버티브', '#earnings/VRT', '.er-head', 1),
    ('용어 설명 탭', '#glossary', '.gl', 3),
    ('초보자 페이지', 'easy/', '#cos .card', 8),
]
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    check(False, '화면 점검', 'Playwright 가 없어요. Stock 폴더에서 .venv/bin/python check_site.py 로 실행하세요')
else:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome')  # 컴퓨터에 설치된 크롬을 그대로 쓴다
        ipad = dict(viewport={'width': 1024, 'height': 1366}, device_scale_factor=2, is_mobile=True, has_touch=True)
        for name, path, ready, need in pages:
            page = browser.new_page(**ipad)
            js_errors = []
            page.on('pageerror', lambda e: js_errors.append(str(e)))
            try:
                page.goto(BASE + path, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_function(f'document.querySelectorAll({json.dumps(ready)}).length >= {need}', timeout=20000)
                text = page.inner_text('body')
                stamp = page.locator('#stamp, .stamp').first.inner_text().strip() if page.locator('#stamp, .stamp').count() else ''
                odd = sorted(set(ODD.findall(text)))
                detail = f"{page.locator(ready).count()}개 그려짐" + (f" · 이상한 글자: {', '.join(odd)}" if odd else '') \
                    + (f" · 스크립트 오류: {js_errors[0][:80]}" if js_errors else '') + (f" · {stamp[:60]}" if stamp else '')
                check(not odd and not js_errors, f'화면: {name}', detail)
            except Exception as e:
                check(False, f'화면: {name}', f"{ready} 가 {need}개 이상 안 그려짐 ({type(e).__name__})" + (f" · 스크립트 오류: {js_errors[0][:80]}" if js_errors else ''))
            page.close()

        # 실적 조회 검색: 회사 이름 일부를 치면 목록이 뜨고, 눌러야 이동하는지
        page = browser.new_page(**ipad)
        try:
            page.goto(BASE + '#earnings/AAPL', wait_until='domcontentloaded', timeout=30000)
            page.wait_for_selector('.er-head', timeout=20000)
            page.click('#erInput')
            page.keyboard.type('버티')
            page.wait_for_selector('#erSugg button', timeout=5000)
            still = '#earnings/AAPL' in page.url  # 치는 동안 저절로 이동하면 안 된다
            page.click('#erSugg button')
            page.wait_for_function("document.querySelector('.er-head h3')?.textContent.includes('버티브')", timeout=20000)
            check(still, '실적 조회 검색', "'버티' 입력 → 목록에서 선택 → 버티브홀딩스로 이동" + ('' if still else ' (입력 중에 저절로 이동함)'))
        except Exception as e:
            check(False, '실적 조회 검색', f'목록이 안 뜨거나 이동이 안 됨 ({type(e).__name__})')
        page.close()

        # 초보자 페이지: 한국/미국 버튼
        page = browser.new_page(**ipad)
        try:
            page.goto(BASE + 'easy/', wait_until='domcontentloaded', timeout=30000)
            page.wait_for_selector('#cos .card', timeout=20000)
            page.click('.seg button[data-c="us"]')
            page.wait_for_function("document.querySelector('#cos .nm')?.textContent === '애플'", timeout=5000)
            weather = page.locator('#wx .card').count()
            check(weather == 3, '초보자 페이지 버튼', f'날씨 카드 {weather}개 · 미국 버튼 누르면 애플부터 나옴')
        except Exception as e:
            check(False, '초보자 페이지 버튼', f'미국 버튼이 안 먹음 ({type(e).__name__})')
        page.close()
        browser.close()

# ── 결과 ──
width = max(len(n) for _, n, _ in results)
print(f'\n점검 대상: {BASE}   ({NOW:%Y-%m-%d %H:%M} KST)\n')
for ok, name, detail in results:
    print(f"{'✅' if ok else '❌'} {name.ljust(width)}  {detail}")
fails = [n for ok, n, _ in results if not ok]
print(f"\n{len(results) - len(fails)}/{len(results)} 통과" + (f" — 확인 필요: {', '.join(fails)}" if fails else ' — 영상 찍어도 좋아요 🎬'))
sys.exit(1 if fails else 0)
