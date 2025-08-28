/* TwLive3.0 UI – curat (un singur header)
   - Filtre: .filters .chip[data-filter="DAZN"|"SKY SPORT"|"*"]
*/

const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

// --- DOM
const LIST        = $("#list");
const LOG         = $("#log");
const BTN_RELOAD  = $("#reloadBtn");
const DATE_INPUT  = $("#datePick");
const SEARCH      = $("#q");
const CHIP_BTNS   = $$(".filters .chip");
const COUNTER_LOS = $("#c_los");
const COUNTER_SE  = $("#c_se");
const COUNTER_TOT = $("#c_total");

// --- state
let LAST_DATA = null;
let FILTER_CHIP = "*";
let QUERY = "";
let TOPBAR = null;
let CURRENT_DATE = new Date(); // Store the current date

// =============== utils
function isoFromPicker(){
  let v = (DATE_INPUT?.value || "").trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return v;

  // If date input is empty or invalid, use the CURRENT_DATE
  const d = CURRENT_DATE;
  const mm = String(d.getMonth()+1).padStart(2,"0");
  const dd = String(d.getDate()).padStart(2,"0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

function safe(a){ return Array.isArray(a) ? a : []; }
function fmtTime(g){ return g?.time_display || (g?.time_local?.slice(11,16) || ""); }
function isHL(chan){
  const u = (chan||"").toUpperCase();
  return u.includes("DAZN") || u.includes("SKY SPORT") ||
         u.includes("CANAL PLUS ACTION") || u.includes("CANAL + ACTION") ||
         u.includes("SPORTDIGITAL");
}
function badge(txt, hl=false){ return `<span class="badge ${hl?'hl':''}">${txt}</span>`; }
function setCounters(data){
  const los = data?.counters?.LiveOnSat ?? 0;
  const se  = data?.counters?.SportEventz ?? 0;
  const tot = data?.counters?.Total ?? (data?.games?.length ?? 0);
  if (COUNTER_LOS) COUNTER_LOS.textContent = `LiveOnSat: ${los}`;
  if (COUNTER_SE)  COUNTER_SE.textContent  = `SportEventz: ${se}`;
  if (COUNTER_TOT) COUNTER_TOT.textContent = `Total: ${tot}`;
}
function appendLog(t){
  if (!LOG) return;
  LOG.textContent = (LOG.textContent || "") + t + (t.endsWith("\n")?"":"\n");
  LOG.scrollTop = LOG.scrollHeight;
}

// =============== filters + sort
function applyFilters(games){
  let out = games.slice();
  if (FILTER_CHIP === "DAZN"){
    out = out.filter(g => safe(g.channels).some(c => (c||"").toUpperCase().includes("DAZN")));
  } else if (FILTER_CHIP === "SKY SPORT"){
    out = out.filter(g => safe(g.channels).some(c => (c||"").toUpperCase().includes("SKY SPORT")));
  }
  const q = (QUERY||"").trim().toLowerCase();
  if (q){
    const terms = q.split(/[,\s]+/).filter(Boolean);
    out = out.filter(g => {
      const hay = [g.teams_display||"", g.competition||"", ...safe(g.channels), ...safe(g.sources)]
                  .join(" | ").toLowerCase();
      return terms.every(t => hay.includes(t));
    });
  }
  out.sort((a,b) =>
    (a.time_local||"").localeCompare(b.time_local||"") ||
    (a.teams_display||"").localeCompare(b.teams_display||""));
  return out;
}

// =============== render
function draw(){
  const games = applyFilters(Array.isArray(LAST_DATA?.games) ? LAST_DATA.games : []);
  LIST.innerHTML = "";
  for (const g of games){
    const time = fmtTime(g);
    const srcs = safe(g.sources).join(" + ");
    const chansHTML = safe(g.channels).map(c => badge(c, isHL(c))).join(" ");
    const row = document.createElement("div");
    row.className = "rowgame";
    row.innerHTML = `
      <div class="time">${time}</div>
      <div>
        <div class="teams">${g.teams_display || ""}</div>
        <div class="comp">${(g.competition || "")} &nbsp; ${srcs ? badge(srcs) : ""}</div>
      </div>
      <div class="tv">${chansHTML}</div>`;
    LIST.appendChild(row);
  }
  if (games.length === 0){
    LIST.innerHTML = `<div style="padding:14px 18px;color:#a9b2c3;">Niciun meci pentru filtrele curente.</div>`;
  }
}

// =============== fetch
async function loadLog(){
  try{
    const r = await fetch("/api/log");
    if (!r.ok) return;
    const j = await r.json();
    if (j?.log){ LOG.textContent = j.log; LOG.scrollTop = LOG.scrollHeight; }
  }catch{}
}

async function loadGames(date) {
    try {
        const d = date ? formatDate(date) : isoFromPicker(); // Use provided date or datepicker value
        const r = await fetch(`/api/games?date=${d}`); // Pass the date to the API
        LAST_DATA = await r.json();
        setCounters(LAST_DATA);
        draw();
    } catch (e) {
        appendLog("[UI] loadGames error: " + (e?.message || e));
    }
}

async function doReload(){
  try{
    TOPBAR?.classList.add('loading');            // pornește mingea
    BTN_RELOAD.disabled = true; BTN_RELOAD.textContent = "Loading...";
    const d  = isoFromPicker(); // Get the date from the datepicker
    const t0 = performance.now();
    const r  = await fetch("/api/reload", { method:"POST", headers:{ "Content-Type":"application/json" }, body:JSON.stringify({date:d}) });
    const j  = await r.json();
    appendLog(`[UI] Reload ${j?.status || r.status} in ${((performance.now()-t0)/1000).toFixed(2)}s`);
    await loadLog(); await loadGames();
  }catch(e){
    appendLog("[UI] Reload error: " + (e?.message || e));
    alert("Reload error. Vezi logul.");
  }finally{
    TOPBAR?.classList.remove('loading');         // oprește mingea
    BTN_RELOAD.disabled = false; BTN_RELOAD.textContent = "Reload";
  }
}

// Function to format date as YYYY-MM-DD
function formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

// =============== init (UN SINGUR wire)
function wire(){
  // 1) elimină .topbar în plus, dacă există din greșeală
  const bars = document.querySelectorAll('.topbar');
  bars.forEach((el, i) => { if (i > 0) el.remove(); });
  TOPBAR = bars[0] || document.querySelector('.topbar');
  // 2) injectează mingea o singură dată
  if (TOPBAR && !TOPBAR.querySelector('.reload-ball')){
    const ball = document.createElement('div');
    ball.className = 'reload-ball'; ball.setAttribute('aria-hidden','true'); ball.textContent = '⚽';
    TOPBAR.appendChild(ball);
  }
  // curăță eventuale mingi duplicate rămase din istoric
  const balls = document.querySelectorAll('.reload-ball');
  balls.forEach((b, i) => { if (i > 0) b.remove(); });

  // 3) filtre
  CHIP_BTNS.forEach(btn => {
    btn.addEventListener("click", () => {
      FILTER_CHIP = btn.getAttribute("data-filter") || "*";
      CHIP_BTNS.forEach(b => b.classList.toggle("chip-active", b === btn));
      draw();
    });
  });

  // 4) search (debounce)
  if (SEARCH){
    let t;
    SEARCH.addEventListener("input", (e) => {
      clearTimeout(t);
      t = setTimeout(() => { QUERY = (e.target.value || "").trim(); draw(); }, 200);
    });
  }

  // 5) reload
  BTN_RELOAD?.addEventListener("click", doReload);

  // 6) primele încărcări
  loadLog();
  loadGames(); // Load games for the current date

  // 7) auto-refresh orar
  setInterval(doReload, 60*60*1000);

    // 8) Datepicker event listener
    if (DATE_INPUT) {
        DATE_INPUT.addEventListener("change", () => {
            CURRENT_DATE = new Date(DATE_INPUT.value); // Update CURRENT_DATE
            loadGames(CURRENT_DATE); // Load games for the selected date
        });

        // Set initial date to today
        DATE_INPUT.value = formatDate(CURRENT_DATE);
    }
}

document.addEventListener("DOMContentLoaded", wire);