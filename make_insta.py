"""인스타그램 게시물을 한 번에 만든다.

  insta/<날짜>/
    post/01.png …     카드뉴스 (1080×1350) — 순서대로 캐러셀에 올리면 된다
    caption.txt       캡션 (복사해서 붙여 넣기)
    article.txt       thefirstclass.kr 에 올릴 '윤슬' 해설 글 초안 (브리핑 작업이 써 둔 것)
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


def save_article(base, out):
    with urllib.request.urlopen(f'{base}briefing.json?t={time.time():.0f}', timeout=30) as r:
        art = json.load(r).get('easy', {}).get('article')
    if art and art.get('body'):
        (out / 'article.txt').write_text(f"{art['title']}\n\n{art['body'].strip()}\n", encoding='utf-8')
        print(f"해설 글 초안 저장 ({len(art['body'])}자)")
    else:
        print('해설 글 초안이 아직 브리핑에 없어요')


# 글 소제목에 맞춰 넣을 이미지. article_images/ 에 있으면 그것을, 없으면 카드뉴스 이미지를 쓴다
ARTICLE_IMAGES = [('', ['article_images/1_thumb.png', 'post/01.png']),
                  ('왜 이렇게', ['article_images/2_movers.png']),
                  ('눈에 띈 회사', ['article_images/3_earn.png', 'post/04.png']),
                  ('체크 포인트', ['article_images/4_check.png'])]


def article_html(out):
    """article.txt 와 이미지를 한 페이지로 묶는다. 이미지는 파일 안에 넣어서 복사·붙여 넣기 때 같이 따라가게 한다"""
    import base64
    import html
    src = out / 'article.txt'
    if not src.exists():
        return None
    title, _, body = src.read_text(encoding='utf-8').partition('\n')

    def img(key):
        for cand in dict(ARTICLE_IMAGES)[key]:
            f = out / cand
            if f.exists():
                data = base64.b64encode(f.read_bytes()).decode()
                return (f'<figure><img src="data:image/png;base64,{data}" alt="">'
                        f'<button type="button" class="ci">이미지만 복사</button></figure>')
        return ''

    parts, para = [img('')], []
    flush = lambda: para and (parts.append('<p>' + '<br>'.join(html.escape(x) for x in para) + '</p>'), para.clear())
    for ln in body.strip().splitlines():
        t = ln.strip()
        if not t:
            flush()
        elif t.startswith('■'):
            flush()
            parts.append(f'<h2>{html.escape(t)}</h2>')
            parts += [img(k) for k, _ in ARTICLE_IMAGES[1:] if k in t]
        else:
            para.append(ln.rstrip())
    flush()
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ --bg: #f4f5f1; --paper: #fff; --ink: #1d1f24; --muted: #646b73; --accent: #0f8a7e; --line: #e2e4dc; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font: 17px/1.8 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif; word-break: keep-all; }}
.bar {{ position: sticky; top: 0; background: var(--ink); color: #fff; padding: 12px 20px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; z-index: 2; }}
.bar button {{ font: inherit; font-size: 15px; font-weight: 700; border: 0; border-radius: 999px; padding: 8px 18px; cursor: pointer; background: #fff; color: var(--ink); }}
.bar button.main {{ background: var(--accent); color: #fff; }}
.bar span {{ font-size: 14px; opacity: .8; }}
article {{ max-width: 760px; margin: 24px auto 80px; background: var(--paper); border: 1px solid var(--line); border-radius: 16px; padding: 36px 40px; }}
h1 {{ font-size: 27px; line-height: 1.4; margin: 0 0 20px; }}
h2 {{ font-size: 20px; margin: 34px 0 10px; }}
p {{ margin: 0 0 16px; }}
figure {{ margin: 18px 0 24px; position: relative; }}
figure img {{ width: 100%; border-radius: 10px; display: block; }}
.ci {{ position: absolute; right: 10px; bottom: 10px; font-size: 13px; border: 0; border-radius: 999px; padding: 5px 12px; background: rgba(0,0,0,.65); color: #fff; cursor: pointer; }}
</style></head><body>
<div class="bar"><button type="button" class="main" id="all">글 전체 복사 (이미지 포함)</button><button type="button" id="title">제목만 복사</button><button type="button" id="text">글자만 복사</button><span id="msg">복사한 뒤 더퍼스트클래스 글쓰기 창에 붙여 넣으세요</span></div>
<article><h1 id="h">{html.escape(title)}</h1><div id="body">{''.join(parts)}</div></article>
<script>
const msg = t => {{ document.getElementById('msg').textContent = t; }};
const body = document.getElementById('body');
async function copyHtml(node) {{
  const clone = node.cloneNode(true); clone.querySelectorAll('.ci').forEach(b => b.remove());
  try {{
    await navigator.clipboard.write([new ClipboardItem({{ 'text/html': new Blob([clone.innerHTML], {{ type: 'text/html' }}), 'text/plain': new Blob([clone.innerText], {{ type: 'text/plain' }}) }})]);
    msg('✅ 복사했어요. 글쓰기 창에 붙여 넣으세요 (이미지가 안 붙으면 이미지만 따로 복사)');
  }} catch (e) {{
    const r = document.createRange(); r.selectNodeContents(node); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    document.execCommand('copy'); msg('✅ 선택해서 복사했어요');
  }}
}}
document.getElementById('all').onclick = () => copyHtml(body);
document.getElementById('title').onclick = () => navigator.clipboard.writeText(document.getElementById('h').innerText).then(() => msg('✅ 제목을 복사했어요'));
document.getElementById('text').onclick = () => {{ const c = body.cloneNode(true); c.querySelectorAll('figure').forEach(f => f.remove());
  navigator.clipboard.writeText(c.innerText).then(() => msg('✅ 글자만 복사했어요')); }};
document.querySelectorAll('.ci').forEach(b => b.onclick = async () => {{
  const blob = await (await fetch(b.previousElementSibling.src)).blob();
  try {{ await navigator.clipboard.write([new ClipboardItem({{ 'image/png': blob }})]); msg('✅ 이미지를 복사했어요'); }}
  catch (e) {{ msg('이미지 복사가 안 돼요. 이미지를 오른쪽 클릭 → 이미지 복사를 써 주세요'); }}
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
