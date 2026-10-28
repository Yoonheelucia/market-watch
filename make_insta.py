"""인스타그램 게시물을 한 번에 만든다.

  insta/<날짜>/
    post/01.png …     카드뉴스 (1080×1350) — 순서대로 캐러셀에 올리면 된다
    caption.txt       캡션 (복사해서 붙여 넣기)
    reel.mp4          릴스 영상 (1080×1920, 목소리·자막 포함)
    narration.txt     영상 대본

실행 (Stock 폴더에서):  .venv/bin/python make_insta.py
  --base http://localhost:8765/   내 컴퓨터에서 띄운 사이트로 만들기 (기본: 실제 사이트)
  --no-video                      카드뉴스·캡션만 만들기
  --voice Achird                  목소리 바꾸기 (gcloud-media 스킬 표 참고)
  --wait                          오늘 아침 미국 주가·브리핑이 올라올 때까지 기다렸다가 만들기 (매일 자동 실행용)
매일 아침 자동 실행: ~/Library/LaunchAgents/kr.yoonseul.insta.plist (07:10, 끝나면 맥 알림)
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
KST = timezone(timedelta(hours=9))
FF = imageio_ffmpeg.get_ffmpeg_exe()
GMEDIA = Path.home() / '.claude/skills/gcloud-media/scripts/gmedia.py'
STYLE = '밝고 친근한 20~30대 한국 여성 경제 크리에이터. 또렷하고 자연스럽게, 살짝 빠른 속도로 설명하듯이'
GAP, SLIDE_GAP, LEAD = 0.25, 0.5, 0.3  # 문장 사이·장면 사이·처음 쉬는 시간(초)
TARGET, MAX_SPEED = 60, 1.15  # 릴스 목표 길이(초). 넘으면 목소리를 최대 1.15배까지 빠르게 한다


def open_cards(browser, base, fmt):
    page = browser.new_page(viewport={'width': 1080, 'height': 1920}, device_scale_factor=1)
    page.goto(f"{base}easy/cards.html{'?f=reel' if fmt == 'reel' else ''}", wait_until='domcontentloaded', timeout=30000)
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
    """오늘 아침 미국 주가(06:37)와 브리핑(06:30 이후)이 올라왔는지"""
    def get(name):
        with urllib.request.urlopen(f'{base}{name}?t={time.time():.0f}', timeout=30) as r:
            return json.load(r)
    now = datetime.now(KST)
    data, brief = get('data.json'), get('briefing.json')
    sp = next(m for m in data['markets'] if m['id'] == 'sp500')
    return (kst(sp.get('updated', data['updated'])) >= now.replace(hour=6, minute=37, second=0, microsecond=0)
            and kst(brief['updated']) >= now.replace(hour=6, minute=30, second=0, microsecond=0))


def notify(text):
    subprocess.run(['osascript', '-e', f'display notification "{text}" with title "윤슬 주식 인스타"'], check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='https://yoonheelucia.github.io/market-watch/')
    ap.add_argument('--voice', default='Achird')
    ap.add_argument('--no-video', action='store_true')
    ap.add_argument('--wait', action='store_true')
    a = ap.parse_args()
    base = a.base.rstrip('/') + '/'
    if a.wait:  # 10분마다 확인, 낮 12시까지
        while not ready(base):
            if datetime.now(KST).hour >= 12:
                notify('오늘 자료가 아직 안 올라와서 못 만들었어요')
                raise SystemExit('오늘 자료가 12시까지 올라오지 않았어요')
            print(datetime.now(KST).strftime('%H:%M'), '자료 기다리는 중…', flush=True)
            time.sleep(600)
    out = ROOT / 'insta' / datetime.now(KST).strftime('%Y-%m-%d')
    if (out / 'post').exists():
        shutil.rmtree(out / 'post')
    out.mkdir(parents=True, exist_ok=True)

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

    print(f'\n완성: {out}')
    if a.wait:
        notify('오늘 카드뉴스·릴스가 준비됐어요')
        subprocess.run(['open', str(out)], check=False)


if __name__ == '__main__':
    main()
