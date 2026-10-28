// 초보자 페이지(index.html)와 인스타 카드(cards.html)가 함께 쓰는 자료·도우미
const COMPANIES = {
  kr: ['005930.KS', '000660.KS', '005380.KS', '035420.KS', '035720.KS', '066570.KS', '207940.KS', '105560.KS', '090430.KS', '097950.KS'],
  us: ['AAPL', 'NVDA', 'MSFT', 'GOOG', 'AMZN', 'TSLA', 'META', 'NFLX', 'KO', 'MCD'],
};
const WEATHER = [
  { min: 2.5, ico: '☀️', word: '아주 맑음', say: '크게 올랐어요' },
  { min: 1, ico: '☀️', word: '맑음', say: '많이 올랐어요' },
  { min: 0.2, ico: '🌤️', word: '대체로 맑음', say: '조금 올랐어요' },
  { min: -0.2, ico: '☁️', word: '구름', say: '거의 그대로예요' },
  { min: -1, ico: '🌦️', word: '조금 흐림', say: '조금 내렸어요' },
  { min: -2.5, ico: '🌧️', word: '비', say: '많이 내렸어요' },
  { min: -Infinity, ico: '⛈️', word: '폭풍', say: '크게 내렸어요' },
];
const TERMS = [
  { w: '주가', en: 'Stock Price', d: '주식 1주의 가격이에요. 사려는 사람과 팔려는 사람이 만나는 값으로 매 순간 바뀌어요.', ex: '삼성전자 주가가 22만 원이면, 삼성전자 주식 1주를 22만 원에 살 수 있다는 뜻이에요.' },
  { w: '시가총액 (시총)', en: 'Market Cap', d: '회사 전체의 몸값이에요. 주가 × 주식 수로 계산해요.', ex: '주가 1만 원짜리 주식이 100만 주 있으면 시총은 100억 원이에요. 회사 크기를 비교할 때 써요.' },
  { w: '실적', en: 'Earnings', d: '회사가 일정 기간(보통 3개월) 동안 얼마를 벌었는지 보여 주는 성적표예요.', ex: '"삼성전자 실적 발표"는 지난 3개월 동안 얼마나 팔고 얼마나 남겼는지 공개하는 날이에요.' },
  { w: '매출', en: 'Revenue', d: '물건이나 서비스를 팔아서 들어온 돈 전체예요. 비용을 빼기 전 금액이에요.', ex: '빵집이 하루에 빵을 100만 원어치 팔았다면 매출은 100만 원이에요.' },
  { w: '영업이익', en: 'Operating Profit', d: '매출에서 재료비·월급·임대료 같은 장사 비용을 빼고 남은 돈이에요.', ex: '빵 100만 원어치를 팔고 비용이 80만 원이었다면 영업이익은 20만 원이에요.' },
  { w: 'EPS (주당순이익)', en: 'Earnings Per Share', d: '회사가 1년 동안 번 돈(순이익)을 주식 1주당으로 나눈 값이에요.', ex: '1년에 100억 원을 벌고 주식이 1억 주면 EPS는 100원이에요. "주식 1주가 1년에 100원을 벌어 온다"는 뜻이에요.' },
  { w: 'PER (주가수익비율)', en: 'Price to Earnings', d: '주가가 1주당 이익(EPS)의 몇 배인지예요. 이익에 비해 주가가 비싼지 싼지 볼 때 써요.', ex: '주가 2,000원, EPS 100원이면 PER은 20배예요. "지금 이익으로 20년 벌어야 주가만큼 된다"고 생각하면 쉬워요.' },
  { w: '배당', en: 'Dividend', d: '회사가 번 돈 일부를 주주에게 나눠 주는 거예요.', ex: '1주당 1,000원 배당이면 100주를 가진 사람은 10만 원(세금 떼기 전)을 받아요.' },
  { w: '금리', en: 'Interest Rate', d: '돈을 빌리거나 맡길 때 붙는 이자의 비율이에요. 나라 중앙은행이 기준 금리를 정해요.', ex: '금리가 오르면 예금 이자가 늘어 주식보다 예금이 매력적이 되고, 회사도 빌린 돈 이자 부담이 커져서 보통 주가에 나빠요.' },
  { w: '연준 (Fed)', en: 'Federal Reserve', d: '미국의 중앙은행이에요. 미국 금리를 정하는데, 전 세계 주식시장이 이 결정을 지켜봐요.', ex: '"연준이 금리를 동결했다"는 미국 금리를 그대로 두기로 했다는 뜻이에요.' },
  { w: 'FOMC', en: 'Federal Open Market Committee', d: '연준이 금리를 정하는 회의예요. 1년에 8번 열려요.', ex: 'FOMC가 끝나는 날(한국 시간 새벽)에는 주가가 크게 움직이는 경우가 많아요.' },
  { w: '물가 (CPI)', en: 'Consumer Price Index', d: '사람들이 사는 물건값이 1년 전보다 얼마나 올랐는지 보여 주는 숫자예요.', ex: '"CPI 3.7%"는 1년 전에 100원이던 물건들이 평균 103.7원이 됐다는 뜻이에요. 너무 높으면 금리 인상 걱정이 커져요.' },
  { w: '환율', en: 'Exchange Rate', d: '다른 나라 돈과 바꿀 때의 비율이에요. 보통 1달러가 몇 원인지로 말해요.', ex: '환율이 1,300원에서 1,400원으로 오르면, 미국 주식을 가진 사람은 주가가 그대로여도 원화로는 돈이 늘어요.' },
  { w: '지수', en: 'Index', d: '여러 회사의 주가를 모아서 하나로 만든 숫자예요. 시장 전체 분위기를 볼 때 써요.', ex: '"코스피가 1% 올랐다"는 한국 큰 회사들 주가가 평균적으로 1% 올랐다는 뜻이에요.' },
  { w: 'ETF', en: 'Exchange Traded Fund', d: '여러 주식을 한 바구니에 담아 주식처럼 사고팔 수 있게 만든 상품이에요.', ex: 'S&P 500 ETF 1주를 사면 미국 대표 회사 500곳을 조금씩 다 가진 셈이에요.' },
  { w: '상장', en: 'IPO / Listing', d: '회사가 주식시장에 처음 들어와서 누구나 그 회사 주식을 사고팔 수 있게 되는 거예요.', ex: '"앤트로픽이 상장한다"는 이제 일반 사람도 앤트로픽 주식을 살 수 있게 된다는 뜻이에요.' },
  { w: '컨센서스', en: 'Consensus', d: '전문가(애널리스트)들이 예상한 실적의 평균이에요.', ex: '실적이 컨센서스보다 좋으면 "어닝 서프라이즈", 나쁘면 "어닝 쇼크"라고 하고 주가가 크게 움직여요.' },
  { w: '호재 / 악재', en: 'Good / Bad News', d: '주가를 올릴 만한 좋은 소식이 호재, 내릴 만한 나쁜 소식이 악재예요.', ex: '전쟁이 끝났다는 소식은 호재, 금리가 오른다는 소식은 악재로 받아들여지는 경우가 많아요.' },
  { w: '매수 / 매도', en: 'Buy / Sell', d: '주식을 사는 게 매수, 파는 게 매도예요.', ex: '"외국인이 매도했다"는 외국인 투자자들이 판 주식이 산 주식보다 많았다는 뜻이에요.' },
  { w: '시장가 / 지정가', en: 'Market / Limit Order', d: '시장가는 지금 가격으로 바로 사고파는 주문, 지정가는 내가 정한 가격이 되면 사고파는 주문이에요.', ex: '"5만 원 지정가 매수"는 주가가 5만 원 이하로 내려와야 사진다는 뜻이에요.' },
  { w: '분산투자', en: 'Diversification', d: '돈을 여러 곳에 나눠서 투자하는 거예요. 한 곳이 망해도 크게 잃지 않게요.', ex: '"달걀을 한 바구니에 담지 말라"는 말이 바로 분산투자예요.' },
  { w: '변동성', en: 'Volatility', d: '주가가 얼마나 크게 오르내리는지예요. 변동성이 크면 하루에도 많이 움직여요.', ex: '작은 바이오 회사는 하루에 10%씩 움직이기도 하고, 코카콜라 같은 회사는 1%도 잘 안 움직여요.' },
  { w: '서머타임', en: 'Daylight Saving Time', d: '여름에 시계를 한 시간 앞당기는 제도예요. 미국은 3월부터 11월 초까지 해요.', ex: '서머타임이 끝나면 미국 주식시장이 한국 시간으로 한 시간 늦게 열리고 닫혀요.' },
  { w: '반도체', en: 'Semiconductor', d: '컴퓨터·휴대폰·자동차의 두뇌와 기억장치 역할을 하는 칩이에요. 한국 주식시장에서 가장 큰 산업이에요.', ex: '삼성전자·SK하이닉스는 기억을 담당하는 메모리 반도체, 엔비디아는 AI 계산용 칩을 만들어요.' },
  { w: '성장주 / 가치주', en: 'Growth / Value', d: '성장주는 앞으로 크게 클 것으로 기대받는 회사, 가치주는 이미 돈을 꾸준히 버는데 주가가 싼 편인 회사예요.', ex: '엔비디아·테슬라는 성장주, 은행이나 코카콜라는 가치주로 많이 불려요. 금리가 오르면 성장주가 더 흔들리는 편이에요.' },
  { w: '외국인 순매도', en: 'Foreign Net Selling', d: '외국 투자자들이 하루 동안 판 금액이 산 금액보다 많았다는 뜻이에요.', ex: '한국 시장은 외국인 비중이 커서, 외국인이 많이 팔면 코스피가 내리는 경우가 많아요.' },
  { w: '중간선거', en: 'Midterm Election', d: '미국 대통령 임기 중간(2년째)에 국회의원을 뽑는 선거예요.', ex: '어느 당이 이기느냐에 따라 세금·규제 정책이 바뀔 수 있어서 주식시장이 관심 있게 지켜봐요.' },
  { w: '유가', en: 'Oil Price', d: '석유 가격이에요. 보통 브렌트유·WTI(서부텍사스유) 1배럴 가격으로 말해요.', ex: '유가가 오르면 기름값·운송비가 올라 물가가 오르고, 금리 인상 걱정으로 이어져요.' },
];

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const cls = v => v > 0.05 ? 'up' : v < -0.05 ? 'down' : 'flat';
const pct = v => (v > 0 ? '+' : '') + v.toFixed(1) + '%';
const arrow = v => v > 0.05 ? '▲' : v < -0.05 ? '▼' : '–';
const DAYS = ['일', '월', '화', '수', '목', '금', '토'];
const fmtDate = s => { const d = new Date(s + 'T00:00:00'); return `${d.getMonth() + 1}월 ${d.getDate()}일(${DAYS[d.getDay()]})`; };

async function load(url) {
  try { const r = await fetch(url, { cache: 'no-cache' }); return r.ok ? r.json() : null; } catch (e) { return null; }
}

// 값이 있는 마지막 두 날의 위치
function lastTwo(arr) {
  const idx = [];
  for (let i = arr.length - 1; i >= 0 && idx.length < 2; i--) if (arr[i] != null) idx.unshift(i);
  return idx;
}
function firstIdx(arr) { return arr.findIndex(v => v != null); }

function spark(values, color) {
  const pts = values.map((v, i) => [i, v]).filter(p => p[1] != null);
  if (pts.length < 2) return '';
  const xs = values.length - 1, ys = pts.map(p => p[1]);
  const lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
  const d = pts.map(([i, v], k) => `${k ? 'L' : 'M'}${(i / xs * 200).toFixed(1)},${(36 - (v - lo) / span * 32).toFixed(1)}`).join('');
  return `<svg viewBox="0 0 200 40" preserveAspectRatio="none" aria-hidden="true"><path d="${d}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
}
const lineColor = v => getComputedStyle(document.documentElement).getPropertyValue(v > 0 ? '--up' : v < 0 ? '--down' : '--muted').trim();

// 데이터를 받은 시각에 그 날 장이 끝났는지 (끝났으면 '마감', 아니면 '장중')
function sessionState(data, id, day) {
  const m = data.markets.find(x => x.id === id);
  const at = new Date((m?.updated || data.updated).replace(' ', 'T').replace(' KST', ':00+09:00'));
  const d = new Date(day + 'T00:00:00Z'), y = d.getUTCFullYear();
  let h = [6, 45];  // 한국: 15:30 마감 (+여유 15분)
  if (!['kospi', 'kosdaq'].includes(id)) {  // 미국: 뉴욕 16:00 마감, 서머타임(3월 둘째 일요일 ~ 11월 첫째 일요일)이면 UTC 20시
    const sun = (m, n) => { const x = new Date(Date.UTC(y, m, 1)); return Date.UTC(y, m, 1 + (7 - x.getUTCDay()) % 7 + 7 * (n - 1)); };
    h = d >= sun(2, 2) && d < sun(10, 1) ? [20, 15] : [21, 15];
  }
  return at >= Date.UTC(y, d.getUTCMonth(), d.getUTCDate(), ...h) ? '장 마감 기준' : '장중 (아직 마감 전)';
}

// 지금 PER 을 지난 5년 분기별 PER 의 가운데 값과 비교
function priceLevel(e) {
  if (!e || !(e.pe > 0)) return { dot: '⚪', text: '판단하기 어려워요', why: '최근 이익이 너무 적거나 손실이라 비교할 수 없어요.' };
  const hist = (e.quarters || []).map(q => q.pe).filter(v => v > 0).sort((a, b) => a - b);
  if (hist.length < 8) return { dot: '⚪', text: '판단하기 어려워요', why: '비교할 과거 기록이 부족해요.' };
  const mid = hist[Math.floor(hist.length / 2)], r = e.pe / mid;
  const base = `지난 5년 보통 PER ${mid.toFixed(0)}배 → 지금 ${e.pe.toFixed(0)}배`;
  if (r < 0.85) return { dot: '🟢', text: '평소보다 싼 편이에요', why: base };
  if (r > 1.15) return { dot: '🔴', text: '평소보다 비싼 편이에요', why: base };
  return { dot: '🟡', text: '평소와 비슷한 수준이에요', why: base };
}

// 오늘의 용어 번호 (1월 1일부터 센 날짜). 매일 0시에 바뀐다.
function termOfDay(now = new Date()) {
  return Math.floor((now - new Date(now.getFullYear(), 0, 0)) / 864e5);
}
