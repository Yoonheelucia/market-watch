#!/bin/bash
# GitHub 예약 실행이 빠지는 날을 대비한 맥 예비 확인 (launchd: kr.yoonseul.databackup, 30분마다)
# 사이트의 데이터가 그날 마감 뒤로 업데이트되지 않았으면 GitHub Actions 업데이트를 대신 실행한다.
# 업데이트 작업은 이미 최신이면 아무것도 하지 않으므로, 여러 번 돌아도 안전하다.
cd "$(dirname "$0")"
now=$(TZ=Asia/Seoul date +%H%M); dow=$(TZ=Asia/Seoul date +%u); today=$(TZ=Asia/Seoul date +%F)
upd() {  # 시장 id → 사이트에 올라간 업데이트 시각 'YYYY-MM-DD HH:MM'
  curl -s --max-time 20 "https://yoonheelucia.github.io/market-watch/data.json?t=$(date +%s)" |
    python3 -c "import json,sys;d=json.load(sys.stdin);print(next(m for m in d['markets'] if m['id']=='$1').get('updated','')[:16])" 2>/dev/null
}
run() {  # 이미 돌고 있는 실행이 있으면 또 시키지 않는다
  if gh run list --workflow update.yml -L 3 --json status -q '.[].status' | grep -qE 'queued|in_progress'; then return; fi
  echo "$(TZ=Asia/Seoul date '+%F %H:%M') $1 데이터가 늦어서 대신 실행"
  gh workflow run update.yml -f region="$1"
}
# 한국: 월~금 18:30 이후, 그날 18:03 이후 업데이트가 없으면
if [ "$dow" -le 5 ] && [ "$now" -ge 1830 ]; then
  u=$(upd kospi); [ -n "$u" ] && [[ "$u" < "$today 18:03" ]] && run kr
fi
# 미국: 화~토 06:45 이후, 그날 06:15 이후 업데이트가 없으면
if [ "$dow" -ge 2 ] && [ "$dow" -le 6 ] && [ "$now" -ge 0645 ]; then
  u=$(upd sp500); [ -n "$u" ] && [[ "$u" < "$today 06:15" ]] && run us
fi
exit 0
