# ======================
# TwLive3.0 - Scraper stabil (LiveOnSat + SportEventz)
# - Suport dată argv[1] = YYYY-MM-DD (altfel azi, Europe/Vienna)
# - SportEventz: requests + fallback Selenium când HTML-ul e creat în JS
# - Ore stabile: time_display = stringul exact din sursă (fără conversii)
# - Merge smart: dedupă pe timp +/- 2 min & fuzzy 65
# ======================
import os, re, json, sys, traceback, time
from datetime import datetime, timedelta, date
import pytz
import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz
from urllib.parse import quote
# Selenium (fallback pentru SportEventz când randarea e în JS)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
# --- Fuzzy matching: rapidfuzz (dacă e instalat) sau fallback cu difflib ---
try:
    from rapidfuzz import fuzz as _rf_fuzz  # rapid & corect
except Exception:
    _rf_fuzz = None
import difflib

def _token_set_ratio(a: str, b: str) -> int:
    """
    Scor 0..100 pe baza mulțimilor de token-uri.
    - Dacă rapidfuzz e disponibil: folosim token_set_ratio.
    - Altfel: fallback simplu cu difflib.
    """
    if _rf_fuzz is not None:
        return int(_rf_fuzz.token_set_ratio(a, b))
    # fallback: normalizare + SequenceMatcher
    def _norm(s: str) -> str:
        toks = [t for t in re.split(r"\s+", s.strip().lower()) if t]
        toks = sorted(set(toks))
        return " ".join(toks)
    a_n = _norm(a)
    b_n = _norm(b)
    return int(difflib.SequenceMatcher(None, a_n, b_n).ratio() * 100)

# ---------- CONSTANTE / CĂI ----------
VIENNA = pytz.timezone("Europe/Vienna")   # fusul nostru
ROOT = os.path.dirname(os.path.dirname(__file__))
WEB_DATA = os.path.join(ROOT, "web", "data")
os.makedirs(WEB_DATA, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
HIGHLIGHT = ["DAZN", "SKY SPORT", "CANAL PLUS ACTION", "CANAL + ACTION", "SPORTDIGITAL"]
STOPWORDS = set("fc cf afc sc ac fk sv cd aek csm club calcio de la el los the".split())

# ---------- HELPERI LOG / TIMP ----------
def now_vienna():
    """Ora curentă în Europe/Vienna (doar pentru log/metadata)."""
    return datetime.now(VIENNA)

def log(msg: str):
    """Scrie în consolă + în web/data/reload.log."""
    line = f"[{now_vienna():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with open(os.path.join(WEB_DATA, "reload.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")

def parse_time_local(date_iso: str, time_str: str) -> str:
    """
    Returnează 'YYYY-MM-DD HH:MM' ca *ora locală Viena*.
    Nu convertim fusuri; atașăm direct Europe/Vienna ca referință locală.
    """
    try:
        dt = datetime.strptime(f"{date_iso} {time_str}", "%Y-%m-%d %H:%M")
    except Exception:
        dt = now_vienna().replace(second=0, microsecond=0).replace(tzinfo=None)
    dt_local = VIENNA.localize(dt)  # atașăm tz (fără conversie)
    return dt_local.strftime("%Y-%m-%d %H:%M")

def dt_parse_local_str(s: str) -> datetime:
    """'YYYY-MM-DD HH:MM' -> datetime (naiv) pentru comparații rapide."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M")

def clean_name(name: str) -> str:
    """Normalizează pentru fuzzy-match: scoate semne, stopwords, vs/v/- etc."""
    s = re.sub(r"[^\w\s\-']", " ", name, flags=re.I).lower()
    s = re.sub(r"\b(vs?|versus)\b", " ", s)
    s = re.sub(r"[-:]", " ", s)
    toks = [t for t in re.split(r"\s+", s) if t and t not in STOPWORDS]
    return " ".join(toks)

def highlight_first(chs):
    """Canalele importante (DAZN/Sky/…) primele, apoi alfabetic; unicitate păstrată."""
    def k(c):
        u = c.upper()
        return (0, u) if any(h in u for h in HIGHLIGHT) else (1, u)
    uniq = list(dict.fromkeys([re.sub(r"\s+", " ", c).strip() for c in chs]))
    return sorted(uniq, key=k)

# =========================================================
#                 SPORTEVENTZ (component/magictable)
# =========================================================
SE_BASE = "https://sporteventz.com/de/component/magictable"
SE_PARAMS_BASE = {
    "se_module": "bW9kX3Nwb3J0ZXZlbnRzX2ZpbHRlcg==",
    "se_id": "U2NoZWR1bGU=",
    "Itemid": "0",
}
SE_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de,en;q=0.9",
    "Referer": "https://sporteventz.com/",
    "Connection": "keep-alive",
}

def sporteventz_url_for_date(d: date) -> str:
    """Construiește URL-ul ‘component/magictable’ cu se_date=MM/DD/YYYY 00:00:00"""
    se_date = d.strftime("%m/%d/%Y 00:00:00")
    params = SE_PARAMS_BASE.copy()
    params["se_date"] = se_date
    qp = "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items())
    return f"{SE_BASE}?{qp}"

def fetch_sporteventz_via_selenium(query_date_iso: str) -> BeautifulSoup:
    """
    Fallback: deschide pagina publică (soccer), lasă JS-ul să randeze,
    apoi returnează HTML-ul final.
    """
    url = "https://www.sporteventz.com/de/soccer"
    log(f"sporteventz: Selenium fallback -> {url} (date={query_date_iso})")
    opts = Options()
    # opțiunea 'new' elimină warning-uri pe Chrome 115+
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1366,900")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    try:
        driver.get(url)
        time.sleep(3.0)  # așteptăm rândurile
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)
        html = driver.page_source
        with open(os.path.join(WEB_DATA, "__sporteventz_selenium.html"),
                  "w", encoding="utf-8", errors="ignore") as f:
            f.write(html)
        return BeautifulSoup(html, "lxml")
    finally:
        driver.quit()

def fetch_sporteventz_html(d: date) -> BeautifulSoup:
    """Încercăm endpoint-ul component/magictable; dacă e doar șablon JS => Selenium."""
    url = sporteventz_url_for_date(d)
    try:
        r = requests.get(url, headers=SE_HEADERS, timeout=30)
        log(f"sporteventz: HTTP {r.status_code}, bytes={len(r.content)}, url={url}")
        r.raise_for_status()
        html = r.text
        with open(os.path.join(WEB_DATA, "__sporteventz.html"),
                  "w", encoding="utf-8", errors="ignore") as f:
            f.write(html)
        has_rows_marker = ("MagicTableRow" in html) or ("jtable-data-row" in html)
        log(f"sporteventz: has_rows_marker={has_rows_marker}")
        soup = BeautifulSoup(html, "lxml")
        # dacă markerii există, dar DOM-ul nu are elemente reale -> randare JS -> Selenium
        if has_rows_marker and not soup.select(".MagicTableRow"):
            return fetch_sporteventz_via_selenium(d.strftime("%Y-%m-%d"))
        return soup
    except requests.exceptions.RequestException as e:
        log(f"Error fetching SportEventz HTML: {e}")
        return None

def parse_sporteventz_soup(soup: BeautifulSoup, date_iso: str):
    """
    Parser robust pentru SportEventz:
    - <tr class="jtable-data-row"> > .MagicTableRow (varianta tabel)
    - .MagicTableRow direct (varianta div)
    Extrage:
      * echipe (Name) sau fallback din holder text (split pe vs / v / - / –)
      * ora din .MagicTableRowFootline h3
      * canale din .MagicTableRowMoreButton + fallback headline în .magictableSub h3
    """
    games = []
    # -- helpers interni pentru parsare --
    def extract_teams(row):
        h = row.select_one(".MagicTableRowMainHomeTeamName")
        a = row.select_one(".MagicTableRowMainAwayTeamName")
        if h and a:
            return h.get_text(" ", strip=True), a.get_text(" ", strip=True)
        holder = (row.select_one(".MagicTableRowMainDataHolder")
                  or row.select_one(".MagicTableRowMainData")
                  or row)
        raw = holder.get_text(" ", strip=True).replace("–", "-")
        m = re.search(r"(.+?)\s+(?:vs\.?|v|-)\s+(.+)", raw, flags=re.I)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return None, None
    def extract_time(row):
        tnode = row.select_one(".MagicTableRowFootline h3")
        if not tnode:
            return None
        m = re.search(r"(\d{1,2}:\d{2})", tnode.get_text(" ", strip=True))
        return m.group(1) if m else None
    def extract_channels(row):
        ch = []
        for btn in row.select(".MagicTableRowMoreButton"):
            txt = re.sub(r"\s+", " ", btn.get_text(" ", strip=True)).strip()
            if len(txt) >= 2:
                ch.append(txt)
        for sub in row.select(".magictableSub h3"):
            name = re.sub(r"\s+", " ", sub.get_text(" ", strip=True)).strip()
            name = re.sub(r"\s*[×x]\s*$", "", name)
            if len(name) >= 2:
                ch.append(name)
        return highlight_first(ch)
    # -- varianta tabel cu <tr> --
    rows = soup.select("tr.jtable-data-row")
    if rows:
        for tr in rows:
            row = tr.select_one(".MagicTableRow") or tr
            time_str = extract_time(row)
            if not time_str:
                continue
            home, away = extract_teams(row)
            if not (home and away):
                continue
            channels = extract_channels(row)
            games.append({
                "source": "SportEventz",
                "time_local": parse_time_local(date_iso, time_str),
                "time_str": time_str,
                "time_display": time_str,  # pentru UI
                "home": home, "away": away,
                "teams_display": f"{home} v {away}",
                "competition": (row.select_one(".MagicTableRowHeadline") or row).get_text(" ", strip=True),
                "channels": channels
            })
        log(f"SportEventz parsed games (tr variant): {len(games)}")
        if games:
            return games
    # -- varianta cu .MagicTableRow direct --
    for row in soup.select(".MagicTableRow"):
        time_str = extract_time(row)
        if not time_str:
            continue
        home, away = extract_teams(row)
        if not (home and away):
            continue
        channels = extract_channels(row)
        games.append({
            "source": "SportEventz",
            "time_local": parse_time_local(date_iso, time_str),
            "time_str": time_str,
            "time_display": time_str,
            "home": home, "away": away,
            "teams_display": f"{home} v {away}",
            "competition": (row.select_one(".MagicTableRowHeadline") or row).get_text(" ", strip=True),
            "channels": channels
        })
    log(f"SportEventz parsed games (div variant): {len(games)}")
    return games

# =========================================================
#                       LIVEONSAT (2day.php)
# =========================================================
import requests
from bs4 import BeautifulSoup
import re
import os
from datetime import date
import time  # Import the time module
# Assuming UA, WEB_DATA, log, parse_time_local, highlight_first are defined elsewhere in your code
# Replace these with your actual definitions
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'  # Example User-Agent
WEB_DATA = "./web_data"  # Example path, replace with your actual path

def log(message):
    print(message)

def parse_time_local(date_iso, time_str):
    return f"{date_iso} {time_str}"

def highlight_first(channels):
    return channels

def liveonsat_url_for_day(d: date) -> str:
    dd, mm, yy = f"{d.day:02d}", f"{d.month:02d}", f"{d.year:04d}"
    return ("https://liveonsat.com/2day.php?"
            f"start_dd={dd}&start_mm={mm}&start_yyyy={yy}"
            f"&end_dd={dd}&end_mm={mm}&start_yyyy={yy}")

def fetch_liveonsat_html(d: date) -> BeautifulSoup:
    """Cere pagina 2day.php pentru ziua d și returnează soup."""
    url = liveonsat_url_for_day(d)
    headers = {"User-Agent": UA}
    try:
        time.sleep(2)  # Wait 2 seconds before each request
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        log(f"liveonsat: HTTP {r.status_code}, bytes={len(r.content)}, url={url}")
        open(os.path.join(WEB_DATA, "__liveonsat.html"), "wb").write(r.content)
        return BeautifulSoup(r.text, "lxml")
    except requests.exceptions.RequestException as e:
        log(f"Error fetching {url}: {e}")
        return None

def choose_best_time(box) -> str | None:
    """
    Extrage ora corectă dintr-un 'box' LiveOnSat.
    1) Preferă eticheta ST (Start Time).
    2) Apoi KO/START/BEGIN/ANPFIFF/ANSTOSS.
    3) Dacă nu găsește etichete, ia o oră plauzibilă (preferă 09:00–23:59; altfel maxima).
    Returnează 'HH:MM' sau None.
    """
    # 1) adunăm textul din nodurile de timp; fallback pe tot box-ul
    time_nodes = box.select(".fLeft_time_live, .fLeft_time")
    fragments = [" ".join(t.stripped_strings) for t in time_nodes]
    if not fragments:
        fragments = [" ".join(box.stripped_strings)]
    text = "  ".join(fragments).replace("\xa0", " ")  # NBSP -> spațiu normal
    # 2) Căutăm etichete explicite cu HH:MM
    labeled = []
    label_regex = re.compile(
        r"\b(?:ST|KO|START|BEGIN|ANPFIFF|ANSTOSS)\b[^\d]{0,8}(\d{1,2}:\d{2})",
        flags=re.I
    )
    for m in label_regex.finditer(text):
        label_zone = m.group(0).upper()
        hhmm = m.group(1)
        if "ST" in label_zone:     # prioritate maximă pentru ST
            return hhmm
        labeled.append(hhmm)
    if labeled:
        return labeled[0]          # prima etichetă găsită (KO/START/etc.)
    # 3) Fără etichete: strângem TOATE HH:MM
    all_times = re.findall(r"\b(\d{1,2}:\d{2})\b", text)
    if not all_times:
        return None
    def to_minutes(hhmm: str) -> int:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    # unice + sortate
    candidates = sorted(set(all_times), key=to_minutes)
    # preferăm o fereastră "de zi": 09:00–23:59
    day_window = [t for t in candidates if 9*60 <= to_minutes(t) <= 23*60+59]
    if day_window:
        return day_window[0]       # cea mai mică din fereastră (startul)
    # fallback: cea mai mare (ex. de seară) – mai realistă decât 05:00
    return candidates[-1]

def find_los_competition(box) -> str:
    """
    În LiveOnSat, competiția e de multe ori într-un heading deasupra 'box'-ului.
    Mergem înapoi prin elementele precedente și căutăm un nod 'titlu'.
    Heuristică: clasă ce conține title/head/comp/league sau text cu termeni tipici.
    """
    KEY_CLASS = ("title", "head", "comp", "league", "country")
    KEY_WORDS = r"(UEFA|Liga|League|Cup|Cupa|Serie|Bundesliga|Premier|LaLiga|Conference|Europa|World|Qualifier|Qualification|Play[- ]?Off|Round|Week|Group|Women|Cupa|Romaniei|Puchar|Pohar|Copa)"
    node = box.find_previous(["div", "h1", "h2", "h3", "h4", "strong"])
    checks = 0
    while node and checks < 40:  # nu ne ducem prea departe
        txt = node.get_text(" ", strip=True)
        cls = " ".join((node.get("class") or [])).lower()
        if txt and any(k in cls for k in KEY_CLASS) and re.search(r"[A-Za-z]", txt):
            # filtrăm liniuțe decorative
            if len(txt) >= 3 and not re.fullmatch(r"[-–—\s]+", txt):
                return txt
        if txt and re.search(KEY_WORDS, txt, re.I):
            if len(txt) >= 3 and len(txt) < 200:
                return txt
        node = node.find_previous(["div", "h1", "h2", "h3", "h4", "strong"])
        checks += 1
    return ""

def parse_liveonsat_soup(soup: BeautifulSoup, date_iso: str):
    games = []
    for box in soup.select("div.blockfix"):
        # ORA
        time_str = choose_best_time(box)
        if not time_str:
            continue
        # ECHIPE
        fleft = box.select_one(".fix_text .fLeft")
        if not fleft:
            continue
        teams = fleft.get_text(" ", strip=True)
        m_teams = re.search(r"(.+?)\s+(?:v|vs\.?|–|-)\s+(.+)$", teams, re.I)
        if not m_teams:
            continue
        home, away = m_teams.group(1).strip(), m_teams.group(2).strip()
        # CANALE
        channels = []
        for a in box.select(".fLeft_live a"):
            txt = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
            if len(txt) >= 2:
                channels.append(txt)
        # COMPETIȚIA (heuristică din heading-urile anterioare)
        comp = find_los_competition(box)
        games.append({
            "source": "LiveOnSat",
            "time_local": parse_time_local(date_iso, time_str),
            "time_str": time_str,
            "time_display": time_str,
            "home": home, "away": away,
            "teams_display": f"{home} v {away}",
            "competition": comp,     # <— acum încercăm să o avem și din L-o-S
            "channels": highlight_first(channels)
        })
    log(f"LiveOnSat parsed games: {len(games)}")
    return games

# =========================================================
#                         MERGE
# =========================================================
def _date_part(g: dict) -> str:
    """YYYY-MM-DD din time_local."""
    return (g.get("time_local") or "")[:10]

def _hhmm_from_game(g: dict) -> str:
    """Ora HH:MM pentru afișare, luată determinist din game."""
    return g.get("time_display") or g.get("time_str") or (g.get("time_local","")[11:16] if g.get("time_local") else "")

def _dt_from_game(g: dict):
    """Datetime (naiv, local Vienna) construit din data + ora jocului."""
    d = _date_part(g) or f"{now_vienna():%Y-%m-%d}"
    t = _hhmm_from_game(g) or "00:00"
    try:
        return datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
    except Exception:
        return datetime.strptime(f"{now_vienna():%Y-%m-%d} 00:00", "%Y-%m-%d %H:%M")

def _mins_diff(g1: dict, g2: dict) -> int:
    """|g1 - g2| în minute pe baza datei locale + HH:MM din game."""
    dt1, dt2 = _dt_from_game(g1), _dt_from_game(g2)
    return int(abs((dt1 - dt2).total_seconds()) // 60)

def is_same_game(g1, g2) -> bool:
    """Aceeași partidă dacă kick-off-urile sunt la max ±65 min și echipele se potrivesc fuzzy."""
    # timp: tolerăm diferență de până la 65 minute (timezone/selector)
    if _mins_diff(g1, g2) > 300:
        return False
    a1, b1 = clean_name(g1["home"]), clean_name(g1["away"])
    a2, b2 = clean_name(g2["home"]), clean_name(g2["away"])
    direct = (_token_set_ratio(a1, a2) + _token_set_ratio(b1, b2)) / 2
    cross  = (_token_set_ratio(a1, b2) + _token_set_ratio(b1, a2)) / 2
    return max(direct, cross) >= 70

# === adaugă asta undeva deasupra lui merge_all (ex. sub is_same_game) ===
def pick_time_display(g: dict) -> str:
    """
    Alege șirul pentru afișare:
    - preferă 'time_display' (din parser)
    - apoi 'time_str'
    - apoi fallback la fragmentul HH:MM din 'time_local'
    """
    if g.get("time_display"):
        return g["time_display"]
    if g.get("time_str"):
        return g["time_str"]
    tl = g.get("time_local", "")
    return tl[11:16] if len(tl) >= 16 else ""

# === ÎNLOCUIEȘTE complet funcția merge_all cu varianta de mai jos ===
def merge_all(los, se):
    merged, used = [], [False] * len(se)
    for g in los:
        matched_h = None
        matched_i = -1
        for i, h in enumerate(se):
            if used[i]:
                continue
            if is_same_game(g, h):
                matched_h = h
                matched_i = i
                break
        # începem cu datele din LiveOnSat
        ch = list(dict.fromkeys(g["channels"]))
        sources = {"LiveOnSat"}
        # ora/ziua pentru output
        tdisp = _hhmm_from_game(g)
        date_iso = _date_part(g) or f"{now_vienna():%Y-%m-%d}"
        # competiția – după regulile cerute:
        # - doar LiveOnSat  -> competiția L-o-S
        # - doar SportEventz -> competiția S-E  (vezi bucla de mai jos)
        # - ambele -> competiția S-E
        comp = g.get("competition", "") or ""
        if matched_h is not None:
            used[matched_i] = True
            # unește canalele și sursele
            ch = list(dict.fromkeys(ch + matched_h["channels"]))
            sources.add("SportEventz")
            # ora: preferăm din SportEventz (e mai stabilă la TZ)
            tdisp = _hhmm_from_game(matched_h) or tdisp
            # competiție: preferăm SportEventz când avem ambele
            comp = matched_h.get("competition", "") or comp
        merged.append(
            {
                "time_local": f"{date_iso} {tdisp}",
                "time_display": tdisp,
                "teams_display": g["teams_display"],  # denumire după LiveOnSat (cum ai cerut)
                "competition": comp,
                "channels": highlight_first(ch),
                "sources": sorted(sources),
            }
        )
    # ce rămâne doar în SportEventz
    for i, h in enumerate(se):
        if used[i]:
            continue
        merged.append(
            {
                "time_local": h["time_local"],
                "time_display": _hhmm_from_game(h),
                "teams_display": h["teams_display"],
                "competition": h.get("competition", "") or "",
                "channels": highlight_first(h["channels"]),
                "sources": ["SportEventz"],
            }
        )
    merged.sort(key=lambda x: (x["time_local"], x["teams_display"].lower()))
    return merged

# =========================================================
#                         MAIN
# =========================================================
def main(query_date_str=None):
    try:
        # --- dată din argument sau azi (Viena) ---
        if query_date_str:
            query_date = date.fromisoformat(query_date_str)
        elif len(sys.argv) >= 2:
            query_date = date.fromisoformat(sys.argv[1])
        else:
            query_date = now_vienna().date()
        date_iso = query_date.strftime("%Y-%m-%d")
        log(f"Scrape start for {date_iso}")
        # --- fetch + parse pentru ziua cerută ---
        los_soup = fetch_liveonsat_html(query_date)
        if los_soup is None:
            raise Exception("Failed to fetch LiveOnSat HTML")
        se_soup = fetch_sporteventz_html(query_date)
        if se_soup is None:
            raise Exception("Failed to fetch SportEventz HTML")
        los = parse_liveonsat_soup(los_soup, date_iso)
        log(f"LiveOnSat: {len(los)}")
        se = parse_sporteventz_soup(se_soup, date_iso)
        log(f"SportEventz: {len(se)}")
        merged = merge_all(los, se)
        log(f"Merged total: {len(merged)}")
        out = {
            "date": date_iso,
            "generated_at": f"{now_vienna():%Y-%m-%d %H:%M:%S}",
            "counters": {"LiveOnSat": len(los), "SportEventz": len(se), "Total": len(merged)},
            "timezone": "Europe/Vienna (GMT+2)",
            "games": merged,
        }
        with open(os.path.join(WEB_DATA, "merged.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        log("OK: JSON written.")
        return out  # Return the data
    except Exception as e:
        # scriem eroarea în merged.json ca UI-ul să aibă ce citi
        log("ERROR: " + str(e))
        log(traceback.format_exc())
        err = {
            "date": f"{now_vienna():%Y-%m-%d}",
            "generated_at": f"{now_vienna():%Y-%m-%d %H:%M:%S}",
            "error": str(e),
            "games": [],
        }
        with open(os.path.join(WEB_DATA, "merged.json"), "w", encoding="utf-8") as f:
            json.dump(err, f, ensure_ascii=False, indent=2)
        return err  # Return the error

if __name__ == "__main__":
    sys.exit(main())
