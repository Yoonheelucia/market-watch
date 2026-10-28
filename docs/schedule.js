// 자료별 업데이트 시각 (한국시간). 바꾸면 .github/workflows/update.yml 의 cron 과 클라우드 브리핑 작업 시간도 같이 바꿔야 한다.
const SCHEDULE = {
  us: { times: ['06:15'], days: [2, 3, 4, 5, 6], what: '미국 주가' },  // 화~토, GitHub Actions
  kr: { times: ['18:03'], days: [1, 2, 3, 4, 5], what: '한국 주가' },  // 월~금, GitHub Actions
  brief: { times: ['02:00', '06:30', '11:00', '15:00', '16:30', '22:00', '23:30'], days: [0, 1, 2, 3, 4, 5, 6], what: '브리핑' },
};
const KST = 9 * 3600e3;
const WEEKDAY = ['일', '월', '화', '수', '목', '금', '토'];

// 예정 시각 목록을 now 기준 앞(dir=1) 또는 뒤(dir=-1)로 훑어 가장 가까운 시각을 찾는다
function scheduledRun(kind, dir = 1, now = Date.now()) {
  const { times, days } = SCHEDULE[kind], k = new Date(now + KST);
  for (let i = 0; i < 9; i++) {
    const add = dir > 0 ? i : -i;
    const day = Date.UTC(k.getUTCFullYear(), k.getUTCMonth(), k.getUTCDate() + add);
    if (!days.includes(new Date(day).getUTCDay())) continue;
    const list = times.map(t => { const [h, m] = t.split(':').map(Number); return day + (h * 60 + m) * 6e4 - KST; });
    const hit = dir > 0 ? list.find(t => t > now) : list.reverse().find(t => t <= now);
    if (hit != null) return hit;
  }
  return null;
}

function fmtKst(ms) {
  const d = new Date(ms + KST), p = n => String(n).padStart(2, '0');
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()}(${WEEKDAY[d.getUTCDay()]}) ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}
const parseKst = s => s ? Date.parse(s.replace(' KST', '').replace(' ', 'T') + ':00+09:00') : NaN;

// '마지막 업데이트 · 다음 업데이트 예정' 한 줄. 예정 시각이 지났는데 아직 안 바뀌었으면 늦어지고 있다고 알려 준다.
function stampText(kind, updated) {
  if (!kind) return '🕒 직접 정리한 내용이라 정해진 업데이트 시간이 없어요';
  const last = parseKst(updated), prev = scheduledRun(kind, -1), next = scheduledRun(kind, 1);
  const lastTxt = isNaN(last) ? '확인 못 함' : fmtKst(last);
  // 예정 시각보다 30분 넘게 지났는데 그 뒤 업데이트가 없으면 '늦어지는 중'
  if (!isNaN(last) && prev && last < prev - 10 * 6e4 && Date.now() - prev > 30 * 6e4)
    return `🕒 마지막 업데이트 ${lastTxt} · ${fmtKst(prev)} 업데이트가 늦어지고 있어요 (곧 바뀌어요)`;
  return `🕒 마지막 업데이트 ${lastTxt} · 다음 업데이트 예정 ${next ? fmtKst(next) : '–'}`;
}

// 페이지를 열어 둔 사이 새 자료가 올라오면, 보던 위치를 기억해 두고 새로 불러온다
function autoRefresh(files) {
  const KEY = 'autoRefreshScroll';
  try {
    const y = sessionStorage.getItem(KEY);
    if (y) { sessionStorage.removeItem(KEY); setTimeout(() => scrollTo(0, +y), 900); }
  } catch (e) {}
  const read = () => Promise.all(files.map(f => fetch(f, { cache: 'no-cache' }).then(r => r.json()).then(j => j.updated || j.asOf).catch(() => null)));
  let seen;
  read().then(v => { seen = v.join('|'); });
  const check = async () => {
    if (seen == null) return;
    const now = (await read()).join('|');
    if (now !== seen && !now.includes('null')) {
      try { sessionStorage.setItem(KEY, String(scrollY)); } catch (e) {}
      location.reload();
    }
  };
  setInterval(check, 5 * 60e3);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
}
