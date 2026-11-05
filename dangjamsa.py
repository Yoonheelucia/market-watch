"""한국경제TV '당신이 잠든 사이(당잠사)' 평일 아침 방송을 참고 메모로 정리한다.

평일 05:30 라이브 → 끝난 뒤 저장된 영상의 한국어 자막을 받아(yt-dlp),
로컬 claude CLI 로 '사실·숫자·원인·오늘 볼 일정' 메모로 요약해 notes/dangjamsa/<날짜>.md 에 저장·푸시한다.
자막 원문은 저장소에 올리지 않는다(요약 메모만). 클라우드 브리핑(11:00·15:00)이 이 메모를 참고한다.
매일 자동 실행: ~/Library/LaunchAgents/kr.yoonseul.dangjamsa.plist (평일 08:00, 10:30 까지 30분마다 재시도)
"""
import json, os, re, subprocess, sys, time, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
KST = timezone(timedelta(hours=9))
PLAYLIST = 'https://www.youtube.com/playlist?list=PLh6kUo7pqm_69KUuM0hOj-ClLo6GWdgUH'
YTDLP = next((p for p in ['/Library/Frameworks/Python.framework/Versions/3.12/bin/yt-dlp', '/opt/homebrew/bin/yt-dlp'] if Path(p).exists()), 'yt-dlp')
CLAUDE = str(Path.home() / '.local/bin/claude')
PROMPT = """아래는 한국경제TV '당신이 잠든 사이' {md} 방송의 자동 자막(오타 많음)이야. 미국 주식 해설 글을 쓰는 사람이 참고할 메모로 정리해.
형식(마크다운, 한국어):
# 당잠사 메모 {date}
- 방송: {title} ({url})
## 어젯밤 미국장 핵심 (지수·업종·종목, 방송에서 말한 숫자 그대로, 자막 오타로 숫자가 의심되면 '(확인 필요)')
## 방송이 꼽은 원인·해석 (누가 그렇게 봤는지 함께)
## 실적·지표·정책 소식 (회사·숫자)
## 오늘 밤·이번 주 볼 일정
## 한국 시장에 미칠 영향으로 언급된 것
규칙: 방송 문장을 길게 베끼지 말고 짧은 요약 문장으로. 광고·인사·잡담은 빼. 자막이 불분명한 고유명사·숫자는 추측하지 말고 '(확인 필요)'. 1,500자 안팎.

자막:
{text}"""


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def latest(today):
    md = f'{today:%m/%d}'
    r = run([YTDLP, '--flat-playlist', '--playlist-end', '8', '--print', '%(id)s\t%(title)s', PLAYLIST], timeout=120)
    for line in r.stdout.splitlines():
        vid, _, title = line.partition('\t')
        if md in title and '당잠사' in title:
            return vid, title
    return None, None


def captions(vid, tmp):
    run([YTDLP, '--skip-download', '--write-auto-subs', '--write-subs', '--sub-langs', 'ko', '--sub-format', 'vtt',
         '-o', f'{tmp}/%(id)s.%(ext)s', f'https://www.youtube.com/watch?v={vid}'], timeout=300)
    f = Path(tmp) / f'{vid}.ko.vtt'
    if not f.exists():
        return ''
    out = []
    for l in f.read_text(encoding='utf-8').splitlines():
        if '-->' in l or not l.strip() or l.startswith(('WEBVTT', 'Kind:', 'Language:')):
            continue
        l = re.sub(r'<[^>]+>', '', l).strip()
        if not out or l != out[-1]:
            out.append(l)
    return ' '.join(dict.fromkeys(out))


def main():
    today = datetime.now(KST)
    date = f'{today:%Y-%m-%d}'
    dst = ROOT / 'notes' / 'dangjamsa' / f'{date}.md'
    if dst.exists():
        print('이미 있어요:', dst); return
    vid, title = latest(today)
    if not vid:
        print(today.strftime('%H:%M'), '오늘 당잠사 영상이 아직 없어요'); sys.exit(2)
    with tempfile.TemporaryDirectory() as tmp:
        text = captions(vid, tmp)
    if len(text) < 2000:
        print('자막이 아직 없어요 (라이브 직후일 수 있음)'); sys.exit(2)
    url = f'https://www.youtube.com/watch?v={vid}'
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(Path.home() / '.claude-personal'))
    r = run([CLAUDE, '-p', PROMPT.format(md=f'{today:%m/%d}', date=date, title=title, url=url, text=text[:60000])],
            env=env, timeout=600)
    note = r.stdout.strip()
    if not note.startswith('#'):
        print('요약 실패:', (r.stderr or r.stdout)[-300:]); sys.exit(1)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(note + '\n', encoding='utf-8')
    git = lambda *a: run(['git', '-C', str(ROOT), *a])
    git('add', str(dst)); git('commit', '-m', f'당잠사 메모 {date}')
    for _ in range(3):
        git('pull', '--rebase', '--autostash')
        if git('push').returncode == 0:
            print('저장·푸시:', dst); return
        time.sleep(10)
    print('푸시 실패 (다음 실행에 다시)')


if __name__ == '__main__':
    main()
