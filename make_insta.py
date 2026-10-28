"""인스타그램 게시물을 한 번에 만든다.

  insta/<날짜>/
    post/01.png …     카드뉴스 (1080×1350) — 순서대로 캐러셀에 올리면 된다
    caption.txt       캡션 (복사해서 붙여 넣기)
    article.txt       thefirstclass.kr 에 올릴 '윤슬' 해설 글 초안 (브리핑 작업이 써 둔 것)
    article_images/   글에 넣는 이미지 (대표 · 등락 · 실적 반응 · 오늘 밤 체크 포인트)
    article.html      글 + 이미지를 한 화면에. '전체 복사' 버튼으로 글쓰기 창에 바로 붙여 넣기
    reel.mp4          릴스 영상 (1080×1920, 목소리·자막 포함)
    narration.txt     영상 대본

실행 (Stock 폴더에서):  .venv/bin/python make_insta.py
  --base http://localhost:8765/   내 컴퓨터에서 띄운 사이트로 만들기 (기본: 실제 사이트)
  --no-video                      카드뉴스·캡션만 만들기
  --voice Achird                  목소리 바꾸기 (gcloud-media 스킬 표 참고)
  --wait                          오늘 19:00 브리핑이 올라올 때까지 기다렸다가 만들기 (매일 자동 실행용)
매일 자동 실행: ~/Library/LaunchAgents/kr.yoonseul.insta.plist (19:40, 끝나면 맥 알림). 발행은 21:00 (더퍼스트클래스 글 → 릴스·카드뉴스)
처음 한 번만: .venv/bin/pip install playwright imageio-ffmpeg
목소리는 구글 클라우드 TTS 를 쓴다. 로그인이 풀리면: gcloud auth application-default login
"""
import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import time
import urllib.request
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
DAY = None  # --date 로 정한 날짜 (없으면 오늘)
KST = timezone(timedelta(hours=9))
FF = imageio_ffmpeg.get_ffmpeg_exe()
GMEDIA = Path.home() / '.claude/skills/gcloud-media/scripts/gmedia.py'
STYLE = '다정하고 자연스러운 30대 한국 여성. 친구에게 설명하듯 편안하게, 과장 없이'
GAP, SLIDE_GAP, LEAD = 0.2, 0.4, 0.3  # 문장 사이·장면 사이·처음 쉬는 시간(초)
TARGET, MAX_SPEED = 60, 1.15  # 릴스 목표 길이(초). 넘으면 목소리를 최대 1.15배까지 빠르게 한다


def open_cards(browser, base, fmt):
    page = browser.new_page(viewport={'width': 1080, 'height': 1920}, device_scale_factor=1)
    q = [('f', 'reel')] if fmt == 'reel' else []
    if DAY:
        q.append(('d', DAY))
    page.goto(f"{base}easy/cards.html" + ('?' + '&'.join(f'{k}={v}' for k, v in q) if q else ''), wait_until='domcontentloaded', timeout=30000)
    page.wait_for_function('document.body.dataset.ready', timeout=30000)
    if page.evaluate('document.body.dataset.ready') != '1':
        raise SystemExit('카드 자료를 불러오지 못했어요. 사이트가 열리는지 확인해 주세요.')
    return page


def make_post(browser, base, out):
    page = open_cards(browser, base, 'post')
    (out / 'post').mkdir(parents=True, exist_ok=True)
    slides = page.locator('.slide')
    for i in range(slides.count()):
        slides.nth(i).screenshot(path=str(out / 'post' / f'{i + 1:02d}.png'))
    (out / 'caption.txt').write_text(page.evaluate('window.CAPTION'), encoding='utf-8')
    print(f'카드뉴스 {slides.count()}장 · 캡션 저장')
    page.close()


def make_frames(browser, base, frames):
    """문장마다 자막을 바꿔 가며 릴스 화면을 캡처한다"""
    page = open_cards(browser, base, 'reel')
    script = page.evaluate('window.SLIDES')
    frames.mkdir(parents=True, exist_ok=True)
    slides = page.locator('.slide')
    shots = []  # (카드 번호, 이미지, 목소리 문장)
    for i, slide in enumerate(script):
        for j, ln in enumerate(slide['lines']):
            page.evaluate(f'setSub({i}, {j})')
            path = frames / f'{i + 1:02d}_{j + 1:02d}.png'
            slides.nth(i).screenshot(path=str(path))
            shots.append((i, path, ln['voice']))
    page.close()
    return shots


def tts_all(texts, voice, cache):
    """같은 문장·목소리는 다시 만들지 않는다 (cache 폴더에 보관)"""
    spec = importlib.util.spec_from_file_location('gmedia', GMEDIA)
    gm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gm)
    proj = gm.project()
    cache.mkdir(parents=True, exist_ok=True)

    def one(text):
        path = cache / (hashlib.sha1(f'{voice}|{STYLE}|{text}'.encode()).hexdigest()[:16] + '.wav')
        if not path.exists():
            for attempt in range(3):
                try:
                    gm.tts(text, voice, STYLE, str(path), proj)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    print('  다시 시도:', e)
        return path

    with ThreadPoolExecutor(4) as pool:
        return list(pool.map(one, texts))


def seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def make_reel(shots, audio, out, tmp):
    """문장 하나 = 화면 한 장 + 목소리. 조각을 만든 뒤 이어 붙인다. 돌려주는 값: (길이, 목소리 속도)"""
    gaps = [SLIDE_GAP if k == len(shots) - 1 or shots[k + 1][0] != s else GAP for k, (s, _, _) in enumerate(shots)]
    speech = sum(seconds(w) for w in audio)
    speed = min(MAX_SPEED, max(1.0, speech / (TARGET - LEAD - sum(gaps))))
    parts, total = [], 0
    for k, ((slide, img, text), wav) in enumerate(zip(shots, audio)):
        pre = LEAD if k == 0 else 0
        dur = pre + seconds(wav) / speed + gaps[k]
        total += dur
        part = tmp / f'part{k:03d}.mp4'
        subprocess.run([FF, '-loglevel', 'error', '-y', '-loop', '1', '-framerate', '30', '-i', str(img), '-i', str(wav),
                        '-filter_complex', f'[1:a]atempo={speed:.4f},adelay={int(pre * 1000)}:all=1,apad,atrim=0:{dur:.3f}[a]',
                        '-map', '0:v', '-map', '[a]', '-t', f'{dur:.3f}',
                        '-c:v', 'libx264', '-preset', 'medium', '-tune', 'stillimage', '-pix_fmt', 'yuv420p', '-r', '30',
                        '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-ac', '2', str(part)], check=True)
        parts.append(part)
    lst = tmp / 'list.txt'
    lst.write_text(''.join(f"file '{p.name}'\n" for p in parts))
    subprocess.run([FF, '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(lst),
                    '-c:v', 'copy', '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11', '-c:a', 'aac', '-b:a', '160k', '-ar', '48000',
                    '-movflags', '+faststart', str(out)], check=True)
    return total, speed


def kst(s):
    return datetime.strptime(s.replace(' KST', ''), '%Y-%m-%d %H:%M').replace(tzinfo=KST)


def ready(base):
    """오늘 미국 주가(06:15)와 저녁 브리핑(19:00 이후)이 올라왔는지"""
    def get(name):
        with urllib.request.urlopen(f'{base}{name}?t={time.time():.0f}', timeout=30) as r:
            return json.load(r)
    now = datetime.now(KST)
    data, brief = get('data.json'), get('briefing.json')
    sp = next(m for m in data['markets'] if m['id'] == 'sp500')
    return (kst(sp.get('updated', data['updated'])) >= now.replace(hour=6, minute=15, second=0, microsecond=0)
            and kst(brief['updated']) >= now.replace(hour=19, minute=0, second=0, microsecond=0))


FIGS = [('thumb', '1_thumb'), ('movers', '2_movers'), ('earn', '3_earn'), ('check', '4_check')]


def make_figs(browser, base, out):
    """해설 글 이미지 4장 (docs/easy/figs.html). 이미 있으면(직접 고친 이미지) 그대로 둔다"""
    dst = out / 'article_images'
    if dst.exists():
        return
    page = browser.new_page(viewport={'width': 1300, 'height': 900}, device_scale_factor=2)
    page.goto(f"{base}easy/figs.html{'?d=' + DAY if DAY else ''}", wait_until='domcontentloaded', timeout=30000)
    page.wait_for_function('document.body.dataset.ready', timeout=30000)
    dst.mkdir(parents=True)
    made = []
    for el, name in FIGS:
        loc = page.locator(f'#{el}')
        if loc.get_attribute('data-skip') is None:
            loc.screenshot(path=str(dst / f'{name}.png'))
            made.append(name)
    page.close()
    print(f'글 이미지 {len(made)}장: {", ".join(made)}')


def save_article(base, out):
    with urllib.request.urlopen(f'{base}briefing.json?t={time.time():.0f}', timeout=30) as r:
        art = json.load(r).get('easy', {}).get('article')
    if art and art.get('body'):
        (out / 'article.txt').write_text(f"{art['title']}\n\n{art['body'].strip()}\n", encoding='utf-8')
        meta = {'tags': art.get('tags', ''), 'summary': art.get('summary', '')}
        (out / 'article_meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f"해설 글 초안 저장 ({len(art['body'])}자)")
    else:
        print('해설 글 초안이 아직 브리핑에 없어요')


SITE = 'https://yoonheelucia.github.io/market-watch/'


def publish_images(out):
    """글 이미지를 사이트(docs/articles/<날짜>/)에 올린다. 글쓰기 창에 HTML 로 넣을 때 이미지 주소가 필요해서"""
    src = out / 'article_images'
    if not src.exists():
        return
    dst = ROOT / 'docs' / 'articles' / out.name
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob('*.png'):
        shutil.copy2(f, dst / f.name)
    git = lambda *a: subprocess.run(['git', '-C', str(ROOT), *a], capture_output=True, text=True)
    git('add', str(dst))
    if git('diff', '--cached', '--quiet').returncode == 0:
        return
    git('commit', '-m', f'해설 글 이미지 {out.name}')
    for _ in range(3):
        if git('pull', '--rebase', '--autostash').returncode == 0 and git('push').returncode == 0:
            print(f'글 이미지 사이트에 올림: {SITE}articles/{out.name}/')
            return
        time.sleep(5)
    print('글 이미지를 사이트에 올리지 못했어요 (git push 실패)')


# 글 소제목에 맞춰 넣을 이미지 (글에 [[이미지 이름]] 줄이 없을 때)
ARTICLE_IMAGES = [('', '1_thumb'), ('왜 이렇게', '2_movers'), ('실적 발표', '3_earn'), ('체크 포인트', '4_check')]
UP, DOWN = '#e0314b', '#2463eb'


def article_html(out):
    """더퍼스트클래스에 올릴 것을 한 페이지에: 태그·제목·요약 칸, HTML 코드(이미지는 사이트 주소), 미리 보기"""
    import html
    import re
    src = out / 'article.txt'
    if not src.exists():
        return None
    title, _, body = src.read_text(encoding='utf-8').partition('\n')
    meta_f = out / 'article_meta.json'
    meta = json.loads(meta_f.read_text(encoding='utf-8')) if meta_f.exists() else {}
    have = {f.stem for f in (out / 'article_images').glob('*.png')} if (out / 'article_images').exists() else set()

    def color(s):  # 오른 건 빨강, 내린 건 파랑
        s = re.sub(r'(▲[\d.,]+%)', rf'<span style="color:{UP};font-weight:700">\1</span>', s)
        return re.sub(r'(▼[\d.,]+%)', rf'<span style="color:{DOWN};font-weight:700">\1</span>', s)

    def blocks(img_src):
        """글을 HTML 조각으로. img_src(이름) → 이미지 주소"""
        out_, para, items = [], [], []
        def img(name):
            return f'<p><img src="{img_src(name)}" alt="" style="max-width:100%;height:auto"></p>' if name in have else ''
        def flush():
            if para:
                out_.append('<p>' + '<br>'.join(color(html.escape(x)) for x in para) + '</p>')
                para.clear()
            if items:
                out_.append('<ul>' + ''.join(f'<li>{color(html.escape(x))}</li>' for x in items) + '</ul>')
                items.clear()
        marked = '[[' in body  # 대표 이미지(1_thumb)는 대표 이미지 칸에 따로 올리므로 본문에는 넣지 않는다
        for ln in body.strip().splitlines():
            t = ln.strip()
            if not t:
                flush()
            elif t.startswith('[[') and t.endswith(']]'):
                flush(); out_.append(img(t[2:-2]))
            elif t.startswith('■'):
                flush(); out_.append(f'<h3>{html.escape(t.lstrip("■ ").strip())}</h3>')
                if not marked:
                    out_ += [img(n) for k, n in ARTICLE_IMAGES[1:] if k in t]
            elif t.startswith('- '):
                if para:
                    flush()
                items.append(t[2:])
            elif re.match(r'^[①-⑩]', t):
                flush(); out_.append(f'<p><strong>{html.escape(t)}</strong></p>')
            else:
                if items:
                    flush()
                para.append(t)
        flush()
        return ''.join(x for x in out_ if x)

    ver = lambda n: int((out / 'article_images' / f'{n}.png').stat().st_mtime)  # 이미지를 고치면 주소가 바뀌어 예전 그림이 남지 않게
    code = blocks(lambda n: f'{SITE}articles/{out.name}/{n}.png?v={ver(n)}')
    preview = blocks(lambda n: f'article_images/{n}.png')
    field = lambda key, label, val, rows=1: (
        f'<div class="f"><div class="lb">{label}<button type="button" data-copy="{key}">복사</button></div>'
        + (f'<textarea id="{key}" rows="{rows}" readonly>{html.escape(val)}</textarea>' if rows > 1 else f'<input id="{key}" readonly value="{html.escape(val)}">') + '</div>')
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body {{ margin: 0; background: #f4f5f1; color: #1d1f24; font: 16px/1.75 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif; word-break: keep-all; }}
.wrap {{ max-width: 820px; margin: 0 auto; padding: 24px 16px 80px; }}
h1.pg {{ font-size: 20px; margin: 0 0 4px; }} .sub {{ color: #646b73; font-size: 14px; margin: 0 0 18px; }}
.box {{ background: #fff; border: 1px solid #e2e4dc; border-radius: 14px; padding: 18px 20px; margin-bottom: 18px; }}
.box h2 {{ font-size: 16px; margin: 0 0 12px; }}
.f {{ margin-bottom: 12px; }} .lb {{ font-size: 14px; font-weight: 700; margin-bottom: 4px; display: flex; gap: 8px; align-items: center; }}
input, textarea {{ width: 100%; box-sizing: border-box; font: 14px/1.6 inherit; font-family: inherit; border: 1px solid #d7d9d1; border-radius: 10px; padding: 9px 12px; background: #fafaf8; }}
textarea.code {{ font: 12px/1.5 ui-monospace, Menlo, monospace; height: 180px; }}
button {{ font: inherit; font-size: 13px; font-weight: 700; border: 0; border-radius: 999px; padding: 4px 14px; cursor: pointer; background: #0f8a7e; color: #fff; }}
.msg {{ font-size: 13px; color: #0f8a7e; min-height: 20px; }}
article {{ background: #fff; border: 1px solid #e2e4dc; border-radius: 14px; padding: 28px 32px; }}
article h1 {{ font-size: 24px; line-height: 1.4; margin: 0 0 16px; }} article h3 {{ font-size: 19px; margin: 30px 0 8px; }}
article img {{ border-radius: 8px; }} article ul {{ padding-left: 22px; }}
</style></head><body><div class="wrap">
<h1 class="pg">더퍼스트클래스 올리기</h1>
<p class="sub">칸마다 '복사'를 눌러 글쓰기 화면의 같은 칸에 붙여 넣으세요. 본문은 HTML 코드를 HTML 입력 칸에 넣으면 이미지까지 같이 들어가요.</p>
<div class="box"><h2>⓪ 대표 이미지</h2>
<p class="sub" style="margin:0 0 10px">이미지를 끌어다 글쓰기 화면의 대표 이미지 칸에 놓으세요. 파일: {html.escape(str((out / 'article_images' / '1_thumb.png').resolve()))}</p>
<img src="article_images/1_thumb.png" alt="대표 이미지" style="width:100%;border-radius:10px;display:block"></div>
<div class="box"><h2>① 태그 · 제목 · 요약</h2>
{field('tags', '태그', meta.get('tags', ''))}
{field('title', '제목', title)}
{field('summary', '요약 — 목록·알림에 쓰여요', meta.get('summary', ''), 3)}
</div>
<div class="box"><h2>② 본문 HTML 코드</h2>
<div class="f"><div class="lb">HTML<button type="button" data-copy="code">HTML 코드 복사</button></div><textarea id="code" class="code" readonly>{html.escape(code)}</textarea></div>
<div class="msg" id="msg"></div></div>
<div class="box"><h2>③ 미리 보기</h2><article><h1>{html.escape(title)}</h1>{preview}</article></div>
</div>
<script>
document.querySelectorAll('[data-copy]').forEach(b => b.onclick = async () => {{
  const el = document.getElementById(b.dataset.copy), m = document.getElementById('msg');
  try {{ await navigator.clipboard.writeText(el.value); }} catch (e) {{ el.select(); document.execCommand('copy'); }}
  const old = b.textContent; b.textContent = '✅ 복사됨'; setTimeout(() => b.textContent = old, 1500);
}});
</script></body></html>"""
    dst = out / 'article.html'
    dst.write_text(page, encoding='utf-8')
    return dst


def notify(text):
    subprocess.run(['osascript', '-e', f'display notification "{text}" with title "윤슬 주식 인스타"'], check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='https://yoonheelucia.github.io/market-watch/')
    ap.add_argument('--voice', default='Sulafat')  # 목소리 샘플: insta/voice_samples/
    ap.add_argument('--no-video', action='store_true')
    ap.add_argument('--wait', action='store_true')
    ap.add_argument('--date', help='YYYY-MM-DD. 자정을 넘겨 전날 것을 만들 때')
    a = ap.parse_args()
    global DAY
    DAY = a.date
    base = a.base.rstrip('/') + '/'
    if a.wait:  # 5분마다 확인, 20:40 까지 (21:00 발행)
        while not ready(base):
            if datetime.now(KST) >= datetime.now(KST).replace(hour=20, minute=40):
                notify('저녁 브리핑이 아직 안 올라와서 못 만들었어요. 직접 실행해 주세요')
                raise SystemExit('저녁 브리핑이 20:40 까지 올라오지 않았어요')
            print(datetime.now(KST).strftime('%H:%M'), '자료 기다리는 중…', flush=True)
            time.sleep(300)
    out = ROOT / 'insta' / (DAY or datetime.now(KST).strftime('%Y-%m-%d'))
    if (out / 'post').exists():
        shutil.rmtree(out / 'post')
    out.mkdir(parents=True, exist_ok=True)

    save_article(base, out)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome')
        make_post(browser, base, out)
        make_figs(browser, base, out)
        if not a.no_video:
            tmp = out / '.work'
            shutil.rmtree(tmp, ignore_errors=True)
            shots = make_frames(browser, base, tmp / 'frames')
        browser.close()

    if not a.no_video:
        texts = [t for _, _, t in shots]
        (out / 'narration.txt').write_text('\n'.join(texts) + '\n', encoding='utf-8')
        print(f'목소리 만드는 중… ({len(texts)}문장, 목소리 {a.voice})')
        audio = tts_all(texts, a.voice, ROOT / 'insta' / '.tts-cache')
        # 글자 수에 비해 너무 짧거나 긴 음성은 잘못 만들어졌을 수 있다 → 지우고 한 번 다시 만든다
        odd = [i for i, (t, w) in enumerate(zip(texts, audio)) if not 3.5 <= len(t.replace(' ', '')) / seconds(w) <= 11]
        if odd:
            print(f'  속도가 이상한 문장 {len(odd)}개 다시 만듦')
            for i in odd:
                audio[i].unlink()
            audio = tts_all(texts, a.voice, ROOT / 'insta' / '.tts-cache')
        print('영상 만드는 중…')
        total, speed = make_reel(shots, audio, out / 'reel.mp4', tmp)
        shutil.rmtree(tmp)
        print(f'릴스 저장: {total:.0f}초' + (f' (목소리 {speed:.2f}배속)' if speed > 1 else '')
              + (f' — 목표 {TARGET}초보다 길어요. 대본을 줄여야 해요' if total > TARGET + 3 else ''))

    publish_images(out)
    page = article_html(out)
    if page:
        print(f'글 페이지: {page}')
    print(f'\n완성: {out}')
    if a.wait:
        notify('오늘 밤 9시에 올릴 글·카드뉴스·릴스가 준비됐어요')
        subprocess.run(['open', str(out)], check=False)
        if page:
            subprocess.run(['open', '-a', 'Google Chrome', str(page)], check=False)


if __name__ == '__main__':
    main()
