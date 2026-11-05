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
  "topics": [{{"title": "주제 제목", "points": ["쉬운 설명 문장", "..."]}}],
  "stocks": [{{"name": "종목 이름", "move": "등락(나왔으면)", "why": "이유 한두 문장"}}],
  "experts": [{{"who": "출연자 이름·소속(자막에 나온 대로, 오타는 고쳐서)", "view": "핵심 의견 2~3문장"}}],
  "watch": ["오늘·이번 주 지켜볼 일정이나 포인트"]
}}
market 의 key: sp500, nasdaq, dow, wti, brent, us10y, us2y, dxy, usdkrw, gold, silver, btc, eth, vix 중 맞는 것. 해당 없으면 "other".
topics 는 4~7개, 각 points 2~4개. 방송에 없는 칸은 빈 배열로.

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
    text = ''.join(s.get('utf8', '') for e in d.get('events', []) for s in e.get('segs') or [])
    text = re.sub(r'\n+', ' ', text)
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
    assert s.get('headline') and s.get('topics'), '요약 형식 이상'
    return s


# 간밤 시장 항목에 실제 마감 값 붙이기 (방송 전날 미국 날짜 기준)
YF = {'wti': ('CL=F', '$', 2), 'brent': ('BZ=F', '$', 2), 'us10y': ('^TNX', '%', 3), 'us2y': ('2YY=F', '%', 3),
      'dxy': ('DX-Y.NYB', '', 2), 'usdkrw': ('KRW=X', '원', 1), 'gold': ('GC=F', '$', 1), 'silver': ('SI=F', '$', 2),
      'btc': ('BTC-USD', '$', 0), 'eth': ('ETH-USD', '$', 0), 'vix': ('^VIX', '', 2)}


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
    tick = [YF[k][0] for k in want if k in YF]
    if tick:
        try:
            import yfinance as yf
            df = yf.download(tick, start=str(day - dt.timedelta(days=12)), end=str(day), progress=False,
                             auto_adjust=False)['Close']
            for k in want:
                if k not in YF or YF[k][0] not in df:
                    continue
                col = df[YF[k][0]].dropna()
                col = col[col.index.strftime('%Y-%m-%d') <= last]
                if len(col) >= 2:
                    closes[k] = (float(col.iloc[-1]), float(col.iloc[-2]), YF[k][1], YF[k][2], col.index[-1].strftime('%Y-%m-%d'))
        except Exception as e:
            log('시세 붙이기 실패:', e)
    ref = closes['sp500'][4] if 'sp500' in closes else None  # 날짜가 다른(하루 묵은) 값은 안 붙인다
    for m in s.get('market', []):
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--no-push', action='store_true')
    a = ap.parse_args()
    day = dt.date.fromisoformat(a.date) if a.date else now().date()
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f'{day}.json')
    if not a.force:
        if day.weekday() >= 5 or os.path.exists(path):
            return
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
