#!/usr/bin/env python3
"""한국경제TV '당잠사(당신이 잠든 사이에)' 요약을 사이트에 올린다.

(사이트 '당잠사 요약' 탭용. notes/ 메모를 만드는 dangjamsa.py 와는 별개)
평일 아침 라이브가 끝나고 자막이 생기면
  1) 재생목록에서 오늘 영상을 찾고
  2) 한국어 자동 자막을 받아
  3) claude -p 로 쉽게 요약해서
  4) docs/dangjamsa/YYYY-MM-DD.json + index.json 저장 → 커밋·푸시
이미 오늘 요약이 있으면 아무것도 안 한다. (launchd 가 30분마다 부름)

  python3 dj_site.py              # 오늘
  python3 dj_site.py --date 2026-11-05 --force
"""
import argparse, datetime as dt, glob, json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'docs', 'dangjamsa')
PLAYLIST = 'https://www.youtube.com/playlist?list=PLh6kUo7pqm_69KUuM0hOj-ClLo6GWdgUH'
CLAUDE = os.path.expanduser('~/.local/bin/claude')
KST = dt.timezone(dt.timedelta(hours=9))
YTDLP = [sys.executable, '-m', 'yt_dlp', '--extractor-args', 'youtube:lang=ko', '--no-warnings']

PROMPT = """아래는 한국경제TV 아침 라이브 '당신이 잠든 사이에(당잠사)' {date} 방송의 자동 자막이에요.
자동 자막이라 오타가 많아요(예: "SNP"→S&P, "데슬라"→테슬라, "효가"→유가). 문맥으로 바로잡아 주세요.
광고 문구는 무시하세요.

주식을 처음 하는 사람도 이해하게, 쉬운 말로 요약해 주세요.
- 숫자(지수 등락률, 금리, 유가, 실적 수치)는 방송에 나온 그대로 살리세요. 없는 숫자를 지어내지 마세요.
- 출연자 의견은 "○○ 출연자는 …라고 봤어요"처럼 누구 의견인지 밝혀 주세요.
- 문장은 "~했어요/~예요" 말투로.

JSON 한 덩어리만 출력하세요(코드블록·설명 없이). 형식:
{{
  "headline": "오늘 방송 핵심을 한 문장(40자 안팎)",
  "summary": "3~4문장 요약",
  "market": [{{"key": "아래 목록 중 하나", "name": "S&P500·나스닥·다우·유가·금리·달러 등", "move": "+1.2% 같은 수치 또는 짧은 설명", "why": "왜 그렇게 움직였는지 한 문장"}}],
  "corners": [{{"title": "자막에 [코너: …]로 표시된 코너 이름 그대로", "start": 코너 시작 초(숫자, 표시된 값 그대로), "one": "이 코너 한 줄 요약", "body": "코너 전체 흐름을 풀어 쓴 3~6문장 단락", "points": ["자세한 설명 문장", "..."]}}],
  "stocks": [{{"name": "종목 이름(한글)", "ticker": "야후 파이낸스 티커(예: AAPL, 005930.KS, 모르면 빈칸)", "move": "등락(나왔으면)", "why": "이유 한두 문장"}}],
  "experts": [{{"who": "출연자 이름·소속(자막에 나온 대로, 오타는 고쳐서)", "view": "핵심 의견 2~3문장"}}],
  "watch": ["오늘·이번 주 지켜볼 일정이나 포인트"]
}}
market 의 key: sp500, nasdaq, dow, sox(필라델피아 반도체지수·반도체 지수), wti, brent, us10y, us2y, us30y, dxy, usdkrw, gold, silver, btc, eth, vix 중 맞는 것. 해당 없으면 "other".
corners 는 자막에 [코너: …] 표시가 있는 코너를 순서대로 모두(광고·제목 없는 코너만 빼고), 코너는 자세히 쓰세요(이 요약만 읽어도 방송을 본 것처럼):
  - body: 코너에서 다룬 흐름을 3~6문장으로. 1분 미만 짧은 코너는 1~2문장.
  - points: 코너 길이에 맞춰 5분 미만 3~5개, 5~10분 5~8개, 10분 넘으면 7~10개.
  - 각 point 는 "무엇이 → 얼마나(숫자) → 왜"가 들어간 1~2문장. 종목·지표 이름과 수치, 전문가 이름과 의견, 앞으로 볼 포인트를 빠뜨리지 말 것.
  - 어려운 용어는 괄호로 짧게 풀어 주세요(예: 하이퍼스케일러(대형 클라우드 회사)).
[코너: …] 표시가 하나도 없으면, 진행자가 코너를 넘기는 말("마켓무버입니다", "글로벌 IB 리포트 보시죠" 등)과 [N초] 시각 표시를 보고
코너를 직접 나눠 corners 를 만드세요(이 방송의 코너 예: 글로벌 헤드라인, 앵커 오프닝, 메가캡 특징주, 마켓무버, 이슈인사이드,
글로벌 IB 리포트, 머니플로우, 글로벌 빅샷, 마감시황, 긴급진단). start 는 가장 가까운 [N초] 값. 방송에 없는 칸은 빈 배열로.

[자막]
{text}
"""


def now():
    return dt.datetime.now(KST)


def log(*a):
    print(now().strftime('%m-%d %H:%M'), *a, flush=True)


def find_video(day):
    """재생목록 최근 영상 중 제목에 [🔴MM/DD 가 있는 것."""
    r = subprocess.run(YTDLP + ['--flat-playlist', '-J', '--playlist-end', '30', PLAYLIST],
                       capture_output=True, text=True, timeout=180)
    if r.returncode:
        raise RuntimeError('재생목록 읽기 실패: ' + r.stderr[-300:])
    key = f'{day.month:02d}/{day.day:02d}'
    for e in json.loads(r.stdout)['entries']:
        if key in (e.get('title') or ''):
            return e['id']
    return None


def fetch(vid, tmp):
    """영상 정보 + 한국어 자막. 아직 라이브 중이거나 자막이 없으면 None."""
    url = f'https://www.youtube.com/watch?v={vid}'
    r = subprocess.run(YTDLP + ['-J', '--skip-download', url], capture_output=True, text=True, timeout=180)
    if r.returncode:
        raise RuntimeError('영상 정보 실패: ' + r.stderr[-300:])
    info = json.loads(r.stdout)
    if info.get('live_status') in ('is_live', 'is_upcoming', 'post_live'):
        log('아직 라이브/처리 중:', info.get('live_status'))
        return None
    subprocess.run(YTDLP + ['--skip-download', '--write-auto-subs', '--write-subs', '--sub-langs', 'ko,ko-orig',
                            '--sub-format', 'json3', '-o', os.path.join(tmp, 's'), url],
                   capture_output=True, text=True, timeout=180)
    files = sorted(glob.glob(os.path.join(tmp, 's*.json3')))
    if not files:
        log('자막 아직 없음')
        return None
    d = json.load(open(files[0]))
    chs = [c for c in (info.get('chapters') or []) if not (c.get('title') or '').startswith('<')]
    parts, ci, mark = [], 0, 0
    for e in d.get('events', []):
        t = (e.get('tStartMs') or 0) / 1000
        if not chs and t >= mark:  # 타임라인이 없으면 1분마다 시각 표시 → 코너를 자막에서 직접 나눈다
            parts.append(f' [{int(t)}초] '); mark += 60
        while ci < len(chs) and t >= chs[ci]['start_time']:
            c = chs[ci]; ci += 1
            parts.append(f"\n\n[코너: {c['title']} · 시작 {int(c['start_time'])}초]\n")
        parts.append(''.join(x.get('utf8', '') for x in e.get('segs') or []).replace('\n', ' '))
    text = re.sub(r' +', ' ', ''.join(parts))
    if len(text) < 3000:
        log('자막이 너무 짧음', len(text))
        return None
    return info, text


def summarize(day, text):
    env = dict(os.environ, USER=os.environ.get('USER') or 'lucialee')
    env.setdefault('CLAUDE_CONFIG_DIR', os.path.expanduser('~/.claude-personal'))
    for k in ('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_CHILD_SESSION'):
        env.pop(k, None)
    prompt = PROMPT.format(date=f'{day.month}월 {day.day}일', text=text)
    r = subprocess.run([CLAUDE, '-p', '--model', 'sonnet'], input=prompt, capture_output=True,
                       text=True, timeout=900, env=env, cwd=tempfile.gettempdir())
    out = r.stdout.strip()
    m = re.search(r'\{.*\}', out, re.S)
    if r.returncode or not m:
        raise RuntimeError('요약 실패: ' + (r.stderr or out)[-400:])
    s = json.loads(m.group(0))
    assert s.get('headline') and (s.get('corners') or s.get('topics')), '요약 형식 이상'
    return s


# 간밤 시장 항목에 실제 마감 값 붙이기 (방송 전날 미국 날짜 기준)
YF = {'wti': ('CL=F', '$', 2), 'brent': ('BZ=F', '$', 2), 'us10y': ('^TNX', '%', 3),
      'dxy': ('DX-Y.NYB', '', 2), 'usdkrw': ('KRW=X', '원', 1), 'gold': ('GC=F', '$', 1), 'silver': ('SI=F', '$', 2),
      'btc': ('BTC-USD', '$', 0), 'sox': ('^SOX', '', 2), 'us30y': ('^TYX', '%', 3), 'eth': ('ETH-USD', '$', 0), 'vix': ('^VIX', '', 2)}


def enrich(s, day):
    last = str(day - dt.timedelta(days=1))
    data = json.load(open(os.path.join(ROOT, 'docs', 'data.json')))
    want = [m.get('key') for m in s.get('market', [])]
    closes = {}
    for m in data['markets']:
        if m['id'] in ('sp500', 'nasdaq', 'dow'):
            ix = [i for i, d in enumerate(m['dates']) if d <= last]
            if len(ix) >= 2:
                c = m['index']['c']; closes[m['id']] = (c[ix[-1]], c[ix[-2]], '', 2, m['dates'][ix[-1]])
    stk = {x['ticker'].strip().upper() for x in s.get('stocks', []) if (x.get('ticker') or '').strip()}
    alias = {'GOOG': 'GOOGL', 'GOOGL': 'GOOG', 'BRK-B': 'BRK.B'}
    for m in data['markets']:  # 사이트 데이터에 있는 종목은 그 종가를 먼저 쓴다
        ix = [i for i, d in enumerate(m['dates']) if d <= last]
        if len(ix) < 2:
            continue
        for st in m.get('stocks', []):
            for t in [st['ticker']] + ([alias[st['ticker']]] if st['ticker'] in alias else []):
                if t in stk and '@' + t not in closes:
                    c = st['c']
                    if c[ix[-1]] and c[ix[-2]]:
                        kr = t.endswith(('.KS', '.KQ'))
                        closes['@' + t] = (c[ix[-1]], c[ix[-2]], '원' if kr else '$', 0 if kr else 2, m['dates'][ix[-1]])
    stk = {t for t in stk if '@' + t not in closes}
    tick = [YF[k][0] for k in want if k in YF] + sorted(stk)
    if tick:
        try:
            import yfinance as yf
            import time
            for n in range(4):  # 가끔 받기 실패 → 잠깐 쉬고 다시
                df = yf.download(tick, start=str(day - dt.timedelta(days=12)), end=str(day + dt.timedelta(days=1)), progress=False,
                                 auto_adjust=False)['Close']
                if len(df.columns) and df.notna().any().mean() > 0.7:
                    break
                time.sleep(20)
            for k in want:
                if k not in YF or YF[k][0] not in df:
                    continue
                col = df[YF[k][0]].dropna()
                col = col[col.index.strftime('%Y-%m-%d') <= last]
                if len(col) >= 2:
                    closes[k] = (float(col.iloc[-1]), float(col.iloc[-2]), YF[k][1], YF[k][2], col.index[-1].strftime('%Y-%m-%d'))
            for t in stk:
                if t not in df:
                    continue
                col = df[t].dropna()
                col = col[col.index.strftime('%Y-%m-%d') <= last]
                if len(col) >= 2:
                    closes['@' + t] = (float(col.iloc[-1]), float(col.iloc[-2]), '원' if t.endswith(('.KS', '.KQ')) else '$',
                                       0 if t.endswith(('.KS', '.KQ')) else 2, col.index[-1].strftime('%Y-%m-%d'))
        except Exception as e:
            log('시세 붙이기 실패:', e)
    # 일봉 칸이 비어 있으면 야후 '최근 체결가'로 채운다 (장 마감 직후 흔함)
    ref0 = closes['sp500'][4] if 'sp500' in closes else last
    for k in [k for k, v in closes.items() if k.startswith('@') and v[4] != ref0]:
        del closes[k]  # 하루 묵은 값은 버리고 최근 체결가로 다시 시도
    for t in stk:
        if '@' + t in closes:
            continue
        try:
            import requests
            from zoneinfo import ZoneInfo
            r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=10d&interval=1d',
                             headers={'User-Agent': 'Mozilla/5.0'}, timeout=20).json()['chart']['result'][0]
            meta, ts = r['meta'], r.get('timestamp') or []
            cl = r['indicators']['quote'][0]['close']
            on = dt.datetime.fromtimestamp(meta['regularMarketTime'], ZoneInfo('America/New_York')).date().isoformat()
            if on != ref0:
                continue
            prev = [c for x, c in zip(ts, cl) if c and dt.datetime.fromtimestamp(x, ZoneInfo('America/New_York')).date().isoformat() < on]
            if prev:
                kr = t.endswith(('.KS', '.KQ'))
                closes['@' + t] = (float(meta['regularMarketPrice']), float(prev[-1]), '원' if kr else '$', 0 if kr else 2, on)
        except Exception as e:
            log('최근 체결가 실패', t, e)
    ref = closes['sp500'][4] if 'sp500' in closes else None  # 날짜가 다른(하루 묵은) 값은 안 붙인다
    for x in s.get('stocks', []):
        x['key'] = '@' + (x.get('ticker') or '').strip().upper()
    for m in s.get('market', []) + s.get('stocks', []):
        k = m.get('key')
        if k not in closes or (ref and closes[k][4] != ref):
            continue
        v, prev, unit, nd, on = closes[k]
        num = f'{v:,.{nd}f}'
        m['level'] = (f'${num}' if unit == '$' else f'{num}{unit}')
        if unit == '%':
            m['chg'] = f'{(v - prev) * 100:+.1f}bp'
        else:
            m['chg'] = f'{(v / prev - 1) * 100:+.2f}%'
        m['on'] = on
    return s


def publish(day):
    ds = day.isoformat()
    items = []
    for f in sorted(glob.glob(os.path.join(OUT, '20*.json')), reverse=True):
        d = json.load(open(f))
        items.append({'date': d['date'], 'title': d['title'], 'headline': d['headline']})
    json.dump({'updated': now().strftime('%Y-%m-%d %H:%M KST'), 'items': items[:60]},
              open(os.path.join(OUT, 'index.json'), 'w'), ensure_ascii=False, indent=1)
    git = lambda *a: subprocess.run(['git', '-C', ROOT, *a], capture_output=True, text=True)
    git('add', 'docs/dangjamsa')
    c = git('commit', '-m', f'당잠사 요약 {ds}', '--', 'docs/dangjamsa')
    if c.returncode and 'nothing' not in c.stdout:
        raise RuntimeError('커밋 실패: ' + c.stdout + c.stderr)
    for _ in range(3):
        if git('push').returncode == 0:
            log('올림 완료', ds)
            return
        git('pull', '--rebase', '--autostash')
    raise RuntimeError('푸시 실패')


def refill(day):
    """이미 만든 요약에 종목 티커·실제 값만 다시 붙인다."""
    path = os.path.join(OUT, f'{day}.json')
    s = json.load(open(path))
    need = [x['name'] for x in s.get('stocks', []) if not x.get('ticker')]
    if need:
        env = dict(os.environ, USER=os.environ.get('USER') or 'lucialee')
        for k in ('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_CHILD_SESSION'):
            env.pop(k, None)
        q = ('다음 종목들의 야후 파이낸스 티커를 JSON 객체 {"이름": "티커"} 하나로만 답해. 상장 안 됐거나 모르면 "". '
             '한국 종목은 005930.KS 형식, 여러 종목이 묶인 이름은 첫 종목.\n' + json.dumps(need, ensure_ascii=False))
        r = subprocess.run([CLAUDE, '-p', '--model', 'sonnet'], input=q, capture_output=True, text=True,
                           timeout=300, env=env, cwd=tempfile.gettempdir())
        mp = json.loads(re.search(r'\{.*\}', r.stdout, re.S).group(0))
        for x in s['stocks']:
            x.setdefault('ticker', mp.get(x['name'], ''))
    for m in s.get('market', []) + s.get('stocks', []):
        for k in ('level', 'chg', 'on'):
            m.pop(k, None)
    for m in s.get('market', []):
        n = m['name']
        if m.get('key') in (None, 'other'):
            m['key'] = 'sox' if '반도체' in n else 'us30y' if '30년' in n else m.get('key', 'other')
    enrich(s, day)
    json.dump(s, open(path, 'w'), ensure_ascii=False, indent=1)
    log('값 다시 붙임', day, sum(1 for x in s.get('stocks', []) if x.get('level')), '/', len(s.get('stocks', [])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--no-push', action='store_true')
    ap.add_argument('--refill', action='store_true')
    a = ap.parse_args()
    day = dt.date.fromisoformat(a.date) if a.date else now().date()
    if a.refill:
        return refill(day)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f'{day}.json')
    if not a.force:
        if day.weekday() >= 5:
            return
        if os.path.exists(path):
            old = json.load(open(path))
            if old.get('chapters') != 'auto' or a.date or not (6 <= now().hour < 14):
                return
            r = subprocess.run(YTDLP + ['-J', '--skip-download', old['url']], capture_output=True, text=True, timeout=180)
            if r.returncode or not json.loads(r.stdout).get('chapters'):
                return
            log('타임라인이 생겨서 코너별로 다시 요약')
        if not a.date and not (6 <= now().hour < 14):
            return
    vid = find_video(day)
    if not vid:
        log('오늘 영상 아직 없음', day)
        return
    with tempfile.TemporaryDirectory() as tmp:
        got = fetch(vid, tmp)
    if not got:
        return
    info, text = got
    s = summarize(day, text)
    enrich(s, day)
    chs = [c for c in (info.get('chapters') or []) if not (c.get('title') or '').startswith('<')]
    s['chapters'] = 'youtube' if chs else 'auto'
    if chs and s.get('corners'):
        have = {c['title'] for c in s['corners']}
        for c in chs:  # 요약이 빠진 짧은 코너도 이름은 남긴다
            if c['title'] not in have:
                s['corners'].append({'title': c['title'], 'start': int(c['start_time']), 'one': '짧은 코너라 따로 요약할 내용이 적어요.', 'points': []})
        st = {c['title']: int(c['start_time']) for c in chs}
        for c in s['corners']:
            c['start'] = st.get(c['title'], c.get('start') or 0)
            c['end'] = next((int(x['end_time']) for x in chs if x['title'] == c['title']), None)
        s['corners'].sort(key=lambda c: c['start'])
    s.update(date=str(day), title=info.get('title', ''), video=vid,
             url=f'https://www.youtube.com/watch?v={vid}', duration=info.get('duration'),
             made=now().strftime('%Y-%m-%d %H:%M KST'))
    json.dump(s, open(path, 'w'), ensure_ascii=False, indent=1)
    log('요약 저장', path)
    if not a.no_push:
        publish(day)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log('오류:', e)
        sys.exit(1)
