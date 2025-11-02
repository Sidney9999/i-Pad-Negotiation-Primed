# app.py
import streamlit as st

# -*- coding: utf-8 -*-
# =============================================================================
# Verhandlung – iPad (neutral vs. power)
# - Start-Screen mit Instruktion + Start-Button (Timer startet erst dann)
# - 15-Minuten Timer (Deadline-Logik)
# - eBay-Chat-UI (Bubbles, Header, Item-Karte)
# - Farben je Modus (neutral=blau, power=rot) und passende Avatare
# - Tipp-Indikator, Power-Druckeinwürfe (Pausen/Zeitmarken)
# - Verbessertes Preisverhalten: monotones Absenken, realistische Re-Anchors, nie < 900 €
# - Survey nach Deal/Abbruch
# - CSV-Logging: transcript/outcomes/survey inkl. condition
# =============================================================================

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import csv, re, random, time

# ----------------------------- [1] GRUNDKONFIG -----------------------------
st.set_page_config(page_title="Verhandlung – iPad (A/B)", page_icon="🤝", layout="centered")

ORIGINAL_PRICE = 1000
RESERVATION_PRICE = 900                   # harter Floor – niemals nennen!
TIME_LIMIT_SECONDS = 15 * 60              # 15 min
MAX_ROUNDS = 12                           # max. numerische Nutzerangebote
MAX_BOT_TURNS = 36

# Avatar-URLs (bei Bedarf ersetzen)
NEUTRAL_AVATAR_URL = "https://i.pravatar.cc/120?img=47"  # lächelnde junge Frau
POWER_AVATAR_URL   = "https://images.unsplash.com/photo-1520975916090-3105956dac38?q=80&w=256&auto=format&fit=crop"  # älterer Herr im Anzug, ernst

# ---------------------- [2] LOGGING ------------------------
LOG_DIR = Path("logs"); LOG_DIR.mkdir(exist_ok=True)
def _session_id():
    if "session_id" not in st.session_state:
        st.session_state.session_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    return st.session_state.session_id
def _transcript_path(): return LOG_DIR / f"transcript_{_session_id()}.csv"
def _outcomes_path():   return LOG_DIR / "outcomes.csv"
def _survey_path():     return LOG_DIR / "survey.csv"

# ---------------------- [3] BEDINGUNG (A/B) ------------------------------
qp = st.experimental_get_query_params()
COND = qp.get("cond", ["neutral"])[0].lower()
if COND not in {"neutral","power"}: COND = "neutral"
with st.sidebar:
    st.markdown("### Experiment-Setup")
    COND = st.selectbox("Bedingung", ["neutral", "power"], index=0 if COND=="neutral" else 1)

# ------------------------- [4] STATE ------------------------
def _init_state():
    ss = st.session_state
    ss.setdefault("started", False)                     # Start-Screen
    ss.setdefault("chat", [])
    ss.setdefault("bot_turns", 0)
    ss.setdefault("round_idx", 0)                      # # numerischer Nutzerangebote
    ss.setdefault("current_offer", ORIGINAL_PRICE)     # Bot-Angebot, monoton fallend
    ss.setdefault("deal_reached", False)
    ss.setdefault("final_price", None)
    ss.setdefault("start_time", datetime.utcnow())     # wird bei Start-Button neu gesetzt
    ss.setdefault("best_user_offer", None)
    ss.setdefault("outcome_logged", False)
    ss.setdefault("last_bot_time", datetime.utcnow())
    ss.setdefault("last_user_time", None)
    ss.setdefault("nag_stage", 0)                      # 5/10/13-Min Nudges
    ss.setdefault("show_survey", False)
_init_state()

# --------------------------- [5] NLP ----------------------
def _parse_price(text: str):
    if not text: return None
    t = text.replace(" ", "")
    m = re.search(r"(\d+(?:[.,]\d{1,2})?)", t)
    if not m: return None
    raw = m.group(1).replace(".", "").replace(",", ".")
    try: return int(round(float(raw)))
    except: return None

def _classify_args(text: str):
    t = text.lower()
    return {
        "student": any(w in t for w in ["student","studium","uni"]),
        "budget": any(w in t for w in ["budget","teuer","kann mir nicht leisten","knapp","pleite"]),
        "cheaper": any(w in t for w in ["günstiger","billiger","angebot","preisvergleich","idealo","woanders"]),
        "condition": any(w in t for w in ["gebraucht","kratzer","zustand"]),
        "immediacy": any(w in t for w in ["dringend","eilig","heute","sofort","morgen"]),
        "cash": any(w in t for w in ["bar","cash"]),
        "pickup": any(w in t for w in ["abholen","abholung"]),
        "shipping": any(w in t for w in ["versand","schicken"]),
        "warranty": any(w in t for w in ["garantie","gewährleistung","rechnung","applecare"]),
    }

# -------------------------- [6] Textbausteine ------------------
EMPATHY = ["Verstehe Ihren Punkt.","Danke für die Offenheit.","Kann ich nachvollziehen.","Klingt nachvollziehbar.","Ich sehe, worauf Sie hinauswollen."]
JUSTIFICATIONS = [
    "Es handelt sich um ein **neues, originalverpacktes** Gerät – ohne Nutzungsspuren.",
    "Sie haben es **sofort** verfügbar, ohne Lieferzeiten.",
    "Der **Originalpreis liegt bei 1.000 €**; knapp darunter ist für Neuware fair.",
    "Neu/OVP hält den Wiederverkaufswert deutlich besser.",
    "Im Vergleich zu Gebrauchtware vermeiden Sie jedes Risiko.",
]
ARG_BANK = {
    "student":[ "Gerade fürs Studium zählt Verlässlichkeit – neu/OVP liefert genau das.","Ich komme Ihnen etwas entgegen, damit es zügig klappt." ],
    "budget":[ "Ich weiß, ein Budget ist eng – ich bewege mich vorsichtig, aber nicht unter Wert.","Fairness ja, Unterwert nein." ],
    "cheaper":[ "Viele vermeintlich günstigere Angebote sind Aktionen, ältere Chargen oder Vorführware.","Bei billigeren Anzeigen ist es oft nicht wirklich neu/OVP." ],
    "condition":[ "Hier ist es **OVP** – das ist preislich ein Unterschied zu 'wie neu'.","Neu bedeutet: null Zyklen, keine Überraschungen – das rechtfertigt knapp unter Neupreis." ],
    "immediacy":[ "Wenn es eilig ist, haben Sie es heute/zeitnah – das ist ein Vorteil.","Zeit sparen hat auch einen Preis." ],
    "cash":[ "Barzahlung ist möglich – das macht es unkompliziert." ],
    "pickup":[ "Abholung ist gern möglich – Versiegelung können Sie direkt prüfen." ],
    "shipping":[ "Versand ist ordentlich verpackt möglich; Abholung ist bequemer." ],
    "warranty":[ "Herstellersupport greift ab Aktivierung." ],
}
CLOSERS_NEUTRAL = ["Wie klingt das für Sie?","Wäre das für Sie in Ordnung?","Können wir uns darauf verständigen?","Passt das für Sie?"]

POWER_OPENERS = [
    "Ich setze den Rahmen bei **{x} €**. In diesem Bereich schließe ich ab.",
    "Lassen Sie uns effizient sein: Aktuell steht der Preis bei **{x} €**.",
    "Ich priorisiere feste Käufer. Der aktuelle Rahmen liegt bei **{x} €**.",
]
POWER_PUSH = [
    "Nennen Sie mir bitte Ihr **bestes** aktuelles Angebot – kurz und konkret.",
    "Begründen Sie, warum ich tiefer gehen sollte.",
    "Wenn **{x} €** nicht passt, schließen wir es lieber sauber ab.",
]
POWER_REJECT_LOW = [
    "Das liegt **weit** außerhalb des Rahmens für Neuware/OVP.",
    "Das Angebot ist **deutlich** unter Marktwert.",
    "Unter **{floor} €** gebe ich nicht ab – darauf möchte ich mich gar nicht zubewegen.",
]
POWER_CLOSERS = [
    "Ich bleibe bei **{x} €** – passt das, machen wir den Deal.",
    "Für **{x} €** halte ich den Slot kurz – ansonsten beenden wir es fair.",
    "Wenn **{x} €** passt, schließen wir es jetzt ab.",
]
POWER_NUDGE_PAUSE = ["Ich habe nicht ewig Zeit.","Es gibt genug andere Interessenten.","Wenn Sie kein verbindliches Angebot haben, beenden wir es lieber."]
POWER_NUDGE_TIMED = ["Ich habe gleich einen Termin – lassen Sie uns das abschließen.","Gleich schaut sich jemand anders das iPad an.","Ich halte das Angebot nicht lang offen."]

def _pick(lines, k=1):
    k = min(k, len(lines))
    return random.sample(lines, k) if k>0 else []

def _compose_argument_response(flags):
    chosen=[]
    for key in ["student","budget","cheaper","condition","immediacy","pickup","cash","shipping","warranty"]:
        if flags.get(key, False) and key in ARG_BANK:
            chosen.extend(_pick(ARG_BANK[key],1))
        if len(chosen)>=2: break
    return " ".join(chosen) if chosen else random.choice(JUSTIFICATIONS)

# --------------------------- [7] LOG/CHAT ---------------------------
def _save_transcript_row(role, text, current_offer):
    file=_transcript_path(); is_new=not file.exists()
    with file.open("a",newline="",encoding="utf-8") as f:
        w=csv.writer(f)
        if is_new: w.writerow(["timestamp_utc","session_id","condition","role","text","current_offer_eur"])
        w.writerow([datetime.utcnow().isoformat(), _session_id(), COND, role, text, current_offer])

def _save_outcome_once(final_price, ended_by, turns_user, duration_s):
    if st.session_state.get("outcome_logged"): return
    file=_outcomes_path(); is_new=not file.exists()
    with file.open("a",newline="",encoding="utf-8") as f:
        w=csv.writer(f)
        if is_new: w.writerow(["timestamp_utc","session_id","condition","item","original_price_eur","final_price_eur","ended_by","user_turns","duration_seconds"])
        w.writerow([datetime.utcnow().isoformat(), _session_id(), COND, "iPad (neu, OVP)", ORIGINAL_PRICE, final_price, ended_by, turns_user, duration_s])
    st.session_state.outcome_logged=True

def _save_survey_row(payload: dict):
    file=_survey_path(); is_new=not file.exists()
    with file.open("a",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=["timestamp_utc","session_id","condition","final_price_eur","ended_by","dominance","pressure","fairness","satisfaction","trust","expertise","recommend","manipulation_power","comment"])
        if is_new: w.writeheader()
        w.writerow(payload)

def _bot_say(md:str):
    st.session_state.bot_turns += 1
    st.session_state.last_bot_time = datetime.utcnow()
    st.chat_message("assistant").markdown(md)
    st.session_state.chat.append(("bot", md))
    _save_transcript_row("bot", md, st.session_state.current_offer)

def _user_say(md:str):
    st.session_state.last_user_time = datetime.utcnow()
    st.chat_message("user").markdown(md)
    st.session_state.chat.append(("user", md))
    _save_transcript_row("user", md, st.session_state.current_offer)

def _detect_deal(text:str):
    if not text: return False, None
    tl=text.lower(); keys=["deal","einverstanden","akzeptiere","passt","nehme ich","agree","accepted"]
    return any(k in tl for k in keys), _parse_price(text)

def _finish(final_price:int, ended_by:str):
    st.session_state.deal_reached=True
    st.session_state.final_price=final_price
    _bot_say(f"Einverstanden – **{final_price} €**. Vielen Dank! 🤝")
    dur=int((datetime.utcnow()-st.session_state.start_time).total_seconds())
    turns=sum(1 for r,_ in st.session_state.chat if r=="user")
    _save_outcome_once(final_price, ended_by, turns, dur)
    st.session_state.show_survey=True

def _polite_decline():
    _bot_say(random.choice([
        "Schade – darunter gebe ich es nicht ab. Ich bleibe bei meinem Rahmen.",
        "Danke für die Verhandlung! Preislich liege ich höher; so komme ich nicht mit.",
        "Ich verstehe Ihren Punkt, aber unter meinem Rahmen schließe ich nicht ab.",
    ]))
    dur=int((datetime.utcnow()-st.session_state.start_time).total_seconds())
    turns=sum(1 for r,_ in st.session_state.chat if r=="user")
    _save_outcome_once(0, "walkaway_or_too_low", turns, dur)
    st.session_state.show_survey=True

# --------------------------- [8] STRATEGIE ---------------------------
def _opening_line():
    if COND=="power":
        return random.choice(POWER_OPENERS).format(x=ORIGINAL_PRICE) + " Das Gerät ist **neu & OVP**. " + random.choice(POWER_PUSH).format(x=ORIGINAL_PRICE)
    return "Hallo! Danke für Ihr Interesse 😊 Das iPad ist **neu & originalverpackt**. Der Neupreis liegt bei **1.000 €**. Woran denken Sie preislich?"

def _round_params():
    return ({"min_gap_first":[80,60,40], "step_after":10, "mid_pull":0.25} if COND=="power"
            else {"min_gap_first":[60,40,30], "step_after":20, "mid_pull":0.45})

def _compose_reply(flags, base):
    return f"{random.choice(EMPATHY)} {_compose_argument_response(flags)} {base}"

def _bounded(value, lo, hi): return max(lo, min(hi, value))

def _propose_below_current(target:int):
    """
    Sicherstellen: Vorschlag <= current_offer (monoton fallend) und >= RESERVATION_PRICE.
    """
    cur = st.session_state.current_offer
    target = _bounded(target, RESERVATION_PRICE, ORIGINAL_PRICE)
    target = min(target, cur)  # nie über aktuelles eigenes Angebot
    return int(round(target/5)*5)

def _compute_counter(user_text:str):
    u = _parse_price(user_text)
    flags=_classify_args(user_text)

    # kein Preis -> nachhaken
    if u is None:
        if COND=="power":
            return f"Der Neupreis liegt bei **{ORIGINAL_PRICE} €**. " + random.choice(POWER_PUSH).format(x=ORIGINAL_PRICE), st.session_state.current_offer
        return f"{random.choice(EMPATHY)} Der Neupreis liegt bei **{ORIGINAL_PRICE} €**. Woran denken Sie preislich?", st.session_state.current_offer

    st.session_state.round_idx += 1
    st.session_state.best_user_offer = max(st.session_state.best_user_offer or 0, u)

    # extreme Lowballs → deutlicher Re-Anchor, aber NICHT zurück auf 1000
    if u <= 600:
        # z.B. 980, 975 ... aber <= current_offer
        step = 20 + 5*max(0, st.session_state.round_idx-1)     # 20, 25, 30...
        proposal = 980 - step                                  # 960.., glaubwürdig statt 1000
        proposal = max(proposal, u + 140)                      # klar über dem Lowball
        proposal = _propose_below_current(proposal)
        msg = (random.choice(POWER_REJECT_LOW).format(floor=RESERVATION_PRICE) if COND=="power" else "Das ist deutlich unter Wert.")
        return f"{msg} {_compose_argument_response(flags)} Ich liege bei **{proposal} €**.", proposal

    params=_round_params()
    cur=st.session_state.current_offer

    # Nutzer ≥ 1000 → fairer Abschlussvorschlag bei 1000
    if u >= ORIGINAL_PRICE:
        return f"{_compose_argument_response(flags)} Bei **1.000 €** können wir direkt abschließen.", ORIGINAL_PRICE

    # Runden 1–3: stets klar über u bleiben, aber unter eigenem aktuellen/Anker Schritt für Schritt runter
    if st.session_state.round_idx <= 3:
        min_gap = params["min_gap_first"][st.session_state.round_idx-1]
        target = max(u + min_gap, ORIGINAL_PRICE - 10*st.session_state.round_idx)  # 990, 980, 970 ...
        proposal = _propose_below_current(target)
        return f"{_compose_argument_response(flags)} Für Neuware halte ich **{proposal} €** für angemessen.", proposal

    # Ab Runde 4: kleine Schritte Richtung gewichteter Mitte; > u; >= 900
    mid_pull = params["mid_pull"]; step_after=params["step_after"]
    weighted_mid = int(round(mid_pull*max(u,RESERVATION_PRICE) + (1-mid_pull)*cur))
    target = max(weighted_mid, u + (50 if COND=="power" else 25))
    target = min(target, cur - step_after)  # klein bewegen
    proposal = _propose_below_current(target)
    return f"{_compose_argument_response(flags)} Ich kann auf **{proposal} €** gehen – darunter schließe ich nicht ab.", proposal

def _time_guard_and_finish_if_needed(latest_user_price: Optional[int]):
    if st.session_state.deal_reached or not st.session_state.started: return
    elapsed = (datetime.utcnow() - st.session_state.start_time).total_seconds()
    if elapsed < TIME_LIMIT_SECONDS: return
    best = st.session_state.best_user_offer or (latest_user_price or 0)
    if best >= RESERVATION_PRICE:
        final = _bounded(best, RESERVATION_PRICE, ORIGINAL_PRICE)
        if COND=="power": _bot_say(f"Ich setze auf Abschluss: **{final} €**. Wenn das passt, machen wir es jetzt fix.")
        _finish(final, "time_finalization")
    else:
        _polite_decline()

# --------------------------- [9] UI (Look & Start) ---------------------------
PRIMARY = "#1f6feb" if COND=="neutral" else "#d93a3a"   # blau vs rot
BG_GRAY = "#f5f5f5"; BOT_BG = "#ffffff"
USER_BG = "#d6e4ff" if COND=="neutral" else "#ffd6d6"
USER_BORDER = "#b5ccff" if COND=="neutral" else "#ffb3b3"
AVATAR_URL = NEUTRAL_AVATAR_URL if COND=="neutral" else POWER_AVATAR_URL

st.markdown(f"""
<style>
  .main .block-container {{ padding-top: 1.0rem; padding-bottom: 6rem; }}
  body {{ background: {BG_GRAY}; }}
  .ek-header {{
    position: sticky; top: 0; z-index: 10;
    background: white; border-bottom: 1px solid #e6e6e6;
    padding: 0.75rem 0.5rem; display: flex; align-items: center; gap: 12px;
  }}
  .ek-ava {{ width: 40px; height: 40px; border-radius: 50%; object-fit: cover; }}
  .ek-title {{ display: flex; flex-direction: column; line-height: 1.2; }}
  .ek-name {{ font-weight: 700; }}
  .ek-online {{ font-size: 12px; color: #5f6b6b; }}
  .ek-online .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; background:{PRIMARY}; margin-right:6px; }}
  .ek-item {{ margin-top: 4px; font-size: 13px; color:#3a3a3a; }}
  .ek-price {{ color: {PRIMARY}; font-weight: 700; }}
  .ek-card {{
    background: white; border: 1px solid #e9e9e9; border-radius: 10px;
    padding: 10px 12px; margin: 10px 0 8px 0; display:flex; gap:12px; align-items:center;
  }}
  .ek-thumb {{ width: 56px; height: 56px; border-radius: 8px; background:#eee; display:flex; align-items:center; justify-content:center; font-size:24px; }}
  .ek-card-title {{ font-weight:600; }}
  .ek-meta {{ font-size: 12px; color:#666; }}
  .chat-wrap {{ display:flex; flex-direction:column; gap:8px; margin-top:8px; }}
  .bubble {{ max-width: 80%; padding: 10px 12px; border-radius: 14px; box-shadow: 0 1px 0 rgba(0,0,0,0.05); font-size: 15px; line-height: 1.25; word-wrap: break-word; }}
  .bot-row {{ display:flex; justify-content:flex-start; }}
  .user-row {{ display:flex; justify-content:flex-end; }}
  .bot-bubble {{ background:{BOT_BG}; border:1px solid #e9e9e9; }}
  .user-bubble {{ background:{USER_BG}; border:1px solid {USER_BORDER}; }}
  .timestamp {{ font-size: 11px; color:#8e8e8e; margin-top:4px; }}
  .typing {{ display:flex; gap:6px; align-items:center; font-size:13px; color:#666; margin: 4px 0 0 6px; }}
  .dot1,.dot2,.dot3 {{ width:6px; height:6px; border-radius:50%; background:#aaa; animation: blink 1.4s infinite; }}
  .dot2 {{ animation-delay: .2s; }} .dot3 {{ animation-delay: .4s; }}
  @keyframes blink {{ 0%{{opacity:.2}} 20%{{opacity:1}} 100%{{opacity:.2}} }}
  .timer-box {{ background:white; border:1px solid #eee; border-radius:10px; padding:8px 12px; margin:8px 0; display:flex; justify-content:space-between; align-items:center; }}
  .timer-label {{ color:#666; font-size:13px; }} .timer-value {{ color:{PRIMARY}; font-weight:700; }}
  .start-card {{ background:white; border:1px solid #e9e9e9; border-radius:10px; padding:16px; }}
  .start-h1 {{ margin:0 0 6px 0; font-size:20px; font-weight:700; }}
  .start-li {{ font-size:14px; color:#333; margin-left: 1rem; }}
</style>
""", unsafe_allow_html=True)

# Header
st.markdown(f"""
<div class="ek-header">
  <img src="{AVATAR_URL}" class="ek-ava"/>
  <div class="ek-title">
    <div class="ek-name">Verkäufer · Privat</div>
    <div class="ek-online"><span class="dot"></span>Online</div>
    <div class="ek-item">iPad (neu, OVP) · <span class="ek-price">{ORIGINAL_PRICE} €</span> VB</div>
  </div>
</div>
""", unsafe_allow_html=True)

# Start-Screen (Instruktion + Start)
if not st.session_state.started:
    st.markdown(f"""
    <div class="start-card">
      <div class="start-h1">Kurze Instruktion</div>
      <ul>
        <li class="start-li">Du verhandelst in einem Chat über den Preis eines neuen iPads (OVP).</li>
        <li class="start-li">Formuliere frei. Nenne bei Bedarf konkrete Euro-Beträge.</li>
        <li class="start-li">Ziel: <b>Einigt euch auf einen Preis</b> – oder brich ab, wenn es nicht passt.</li>
        <li class="start-li">Die maximale Verhandlungszeit beträgt <b>15 Minuten</b>.</li>
      </ul>
    </div>
    """, unsafe_allow_html=True)
    if st.button("▶️ Verhandlung starten", use_container_width=True):
        st.session_state.started = True
        st.session_state.start_time = datetime.utcnow()
        st.experimental_rerun()
    st.stop()

# Item-Karte + Timer
st.markdown(f"""
<div class="ek-card">
  <div class="ek-thumb">📦</div>
  <div>
    <div class="ek-card-title">Apple iPad · Neu & OVP</div>
    <div class="ek-meta">Abholung möglich · Barzahlung ok · Herstellergarantie ab Aktivierung</div>
  </div>
</div>
""", unsafe_allow_html=True)

# Timeranzeige
elapsed = (datetime.utcnow() - st.session_state.start_time).total_seconds()
remaining = max(0, TIME_LIMIT_SECONDS - int(elapsed))
mins, secs = divmod(remaining, 60)
st.markdown(f"""
<div class="timer-box"><div class="timer-label">Verfügbare Verhandlungszeit</div>
<div class="timer-value">{mins:02d}:{secs:02d}</div></div>
""", unsafe_allow_html=True)
st.progress(remaining / TIME_LIMIT_SECONDS if TIME_LIMIT_SECONDS else 0.0)

# Erste Bot-Nachricht
if len(st.session_state.chat)==0:
    def _opening_line():
        if COND=="power":
            return random.choice(POWER_OPENERS).format(x=ORIGINAL_PRICE) + " Das Gerät ist **neu & OVP**. " + random.choice(POWER_PUSH).format(x=ORIGINAL_PRICE)
        return "Hallo! Danke für Ihr Interesse 😊 Das iPad ist **neu & originalverpackt**. Der Neupreis liegt bei **1.000 €**. Woran denken Sie preislich?"
    _bot_say(_opening_line())

# Zeit-Nudges (Power) 5/10/13 min
def _maybe_timed_nudge():
    if COND!="power" or st.session_state.deal_reached or st.session_state.show_survey: return
    em = elapsed/60
    if st.session_state.nag_stage==0 and em>=5:  _bot_say(random.choice(POWER_NUDGE_TIMED)); st.session_state.nag_stage=1
    elif st.session_state.nag_stage==1 and em>=10: _bot_say(random.choice(POWER_NUDGE_TIMED)); st.session_state.nag_stage=2
    elif st.session_state.nag_stage==2 and em>=13: _bot_say(random.choice(POWER_NUDGE_TIMED)); st.session_state.nag_stage=3
_maybe_timed_nudge()

# Chatverlauf
def _fake_time_offset(idx:int):
    ts = datetime.utcnow() - timedelta(minutes=max(0,(len(st.session_state.chat)-idx)//2))
    return ts.strftime("%H:%M")
st.markdown('<div class="chat-wrap">', unsafe_allow_html=True)
for i,(role,text) in enumerate(st.session_state.chat, start=1):
    row_cls = "bot-row" if role=="bot" else "user-row"
    bub_cls = "bot-bubble" if role=="bot" else "user-bubble"
    ts=_fake_time_offset(i)
    st.markdown(f'''
    <div class="{row_cls}">
      <div class="bubble {bub_cls}">
        {text}
        <div class="timestamp">{ts}</div>
      </div>
    </div>
    ''', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# Quickchips (optional)
q1,q2,q3,q4 = st.columns(4)
with q1:
    if st.button("900 € vorschlagen", use_container_width=True): st.session_state._inject_click="Ich biete 900 €"
with q2:
    if st.button("930 € vorschlagen", use_container_width=True): st.session_state._inject_click="Ich könnte 930 € zahlen"
with q3:
    if st.button("950 € vorschlagen", use_container_width=True): st.session_state._inject_click="Wären 950 € denkbar?"
with q4:
    if st.button("1000 € nehmen", use_container_width=True):   st.session_state._inject_click="Deal bei 1000 €"

# Tipp-Indikator
def _typing_indicator(duration_s: float):
    ph = st.empty()
    with ph.container():
        st.markdown('<div class="typing"><span>Verkäufer tippt</span><div class="dot1"></div><div class="dot2"></div><div class="dot3"></div></div>', unsafe_allow_html=True)
    time.sleep(max(0.0,duration_s)); ph.empty()

def _tail_for(price:int):
    return (random.choice(POWER_CLOSERS).format(x=price) if COND=="power" else random.choice(CLOSERS_NEUTRAL))

# Pause-Nudge (Power) bei >40s
def _maybe_pause_nudge():
    if COND!="power" or st.session_state.deal_reached or st.session_state.show_survey: return
    last = max(st.session_state.last_bot_time, st.session_state.last_user_time or st.session_state.last_bot_time)
    if (datetime.utcnow()-last).total_seconds() >= 40:
        _bot_say(random.choice(POWER_NUDGE_PAUSE))

# -------------- Verhandlungslogik-Helfer (aus früherem Block) --------------
def _round_params():
    return ({"min_gap_first":[80,60,40], "step_after":10, "mid_pull":0.25} if COND=="power"
            else {"min_gap_first":[60,40,30], "step_after":20, "mid_pull":0.45})

def _bounded(value, lo, hi): return max(lo, min(hi, value))

def _propose_below_current(target:int):
    cur = st.session_state.current_offer
    target = _bounded(target, RESERVATION_PRICE, ORIGINAL_PRICE)
    target = min(target, cur)
    return int(round(target/5)*5)

def _compute_counter(user_text:str):
    u = _parse_price(user_text)
    flags=_classify_args(user_text)
    if u is None:
        if COND=="power": return f"Der Neupreis liegt bei **{ORIGINAL_PRICE} €**. " + random.choice(POWER_PUSH).format(x=ORIGINAL_PRICE), st.session_state.current_offer
        return f"{random.choice(EMPATHY)} Der Neupreis liegt bei **{ORIGINAL_PRICE} €**. Woran denken Sie preislich?", st.session_state.current_offer
    st.session_state.round_idx += 1
    st.session_state.best_user_offer = max(st.session_state.best_user_offer or 0, u)

    if u <= 600:
        step = 20 + 5*max(0, st.session_state.round_idx-1)   # 20,25,30...
        proposal = 980 - step                                # 960.., realistisch
        proposal = max(proposal, u + 140)
        proposal = _propose_below_current(proposal)
        msg = random.choice(POWER_REJECT_LOW).format(floor=RESERVATION_PRICE) if COND=="power" else "Das ist deutlich unter Wert."
        return f"{msg} {_compose_argument_response(flags)} Ich liege bei **{proposal} €**.", proposal

    params=_round_params(); cur=st.session_state.current_offer
    if u >= ORIGINAL_PRICE:
        return f"{_compose_argument_response(flags)} Bei **1.000 €** können wir direkt abschließen.", ORIGINAL_PRICE

    if st.session_state.round_idx <= 3:
        min_gap = params["min_gap_first"][st.session_state.round_idx-1]
        target = max(u + min_gap, ORIGINAL_PRICE - 10*st.session_state.round_idx)  # 990/980/970
        proposal = _propose_below_current(target)
        return f"{_compose_argument_response(flags)} Für Neuware halte ich **{proposal} €** für angemessen.", proposal

    mid_pull = params["mid_pull"]; step_after=params["step_after"]
    weighted_mid = int(round(mid_pull*max(u,RESERVATION_PRICE) + (1-mid_pull)*cur))
    target = max(weighted_mid, u + (50 if COND=="power" else 25))
    target = min(target, cur - step_after)
    proposal = _propose_below_current(target)
    return f"{_compose_argument_response(flags)} Ich kann auf **{proposal} €** gehen – darunter schließe ich nicht ab.", proposal

def _handle_text(text:str):
    _maybe_pause_nudge()
    _typing_indicator(random.uniform(0.3,0.9) if COND=="neutral" else random.uniform(0.2,0.6))
    expl, p = _detect_deal(text)
    if expl:
        if p is None:
            if st.session_state.current_offer >= RESERVATION_PRICE: _finish(st.session_state.current_offer,"user_says_deal_no_price")
            else: _polite_decline()
        else:
            if RESERVATION_PRICE <= p <= ORIGINAL_PRICE: _finish(p,"user_says_deal_with_price")
            else:
                reply, new = _compute_counter(text); st.session_state.current_offer = new; _bot_say(reply+" "+_tail_for(new))
    else:
        reply, new = _compute_counter(text); st.session_state.current_offer = new; _bot_say(reply+" "+_tail_for(new))
    _time_guard_and_finish_if_needed(_parse_price(text))

# Eingaben + Buttons
user_input = st.chat_input("Nachricht schreiben …")
c1,c2 = st.columns(2)
with c1: deal_click   = st.button("✅ Ich nehme das Angebot", use_container_width=True)
with c2: cancel_click = st.button("✖️ Nicht mehr interessiert", use_container_width=True)

if deal_click and not st.session_state.deal_reached and not st.session_state.show_survey:
    if st.session_state.current_offer >= RESERVATION_PRICE: _finish(st.session_state.current_offer,"deal_button")
    else: _polite_decline()

if cancel_click and not st.session_state.deal_reached and not st.session_state.show_survey:
    _polite_decline()

if st.session_state.get("_inject_click") and not st.session_state.deal_reached and not st.session_state.show_survey:
    txt = st.session_state._inject_click; del st.session_state._inject_click
    _user_say(txt); _handle_text(txt)

if user_input and not st.session_state.deal_reached and not st.session_state.show_survey:
    _user_say(user_input); _handle_text(user_input)

# Caps & Deadline
if (not st.session_state.deal_reached) and st.session_state.round_idx >= MAX_ROUNDS and not st.session_state.show_survey:
    if st.session_state.current_offer >= RESERVATION_PRICE:
        _bot_say(f"Ich bleibe bei **{st.session_state.current_offer} €**. Sonst beenden wir es hier.")
    _polite_decline()
if (not st.session_state.deal_reached) and st.session_state.bot_turns >= MAX_BOT_TURNS and not st.session_state.show_survey:
    _polite_decline()
def _time_guard_and_finish_if_needed(latest_user_price: Optional[int]):
    if st.session_state.deal_reached or not st.session_state.started: return
    elapsed = (datetime.utcnow() - st.session_state.start_time).total_seconds()
    if elapsed < TIME_LIMIT_SECONDS: return
    best = st.session_state.best_user_offer or (latest_user_price or 0)
    if best >= RESERVATION_PRICE:
        final = _bounded(best, RESERVATION_PRICE, ORIGINAL_PRICE)
        if COND=="power": _bot_say(f"Ich setze auf Abschluss: **{final} €**. Wenn das passt, machen wir es jetzt fix.")
        _finish(final, "time_finalization")
    else:
        _polite_decline()
_time_guard_and_finish_if_needed(None)

# --------------------------- [10] SURVEY ---------------------------
def _render_survey():
    st.markdown("---"); st.subheader("Kurzer Abschluss-Fragebogen")
    st.caption("Ihre Antworten helfen uns, die Verhandlungssituation besser zu verstehen (anonym).")
    with st.form("survey", clear_on_submit=False):
        c1,c2 = st.columns(2)
        with c1:
            dominance = st.slider("Der Bot wirkte dominant", 1,7,4)
            pressure  = st.slider("Ich fühlte mich unter Druck gesetzt", 1,7,3)
            fairness  = st.slider("Die Verhandlung war fair", 1,7,4)
            satisfaction = st.slider("Ich bin mit dem Ergebnis zufrieden", 1,7,4)
        with c2:
            trust    = st.slider("Ich vertraute dem Bot", 1,7,4)
            expertise= st.slider("Der Bot wirkte kompetent", 1,7,4)
            recommend= st.slider("Ich würde so verhandeln weiterempfehlen", 1,7,3)
            manipulation_power = st.slider("Der Bot wirkte machtbetont", 1,7,4)
        comment = st.text_area("Optionaler Kommentar", placeholder="Was hat dir gefallen / gestört?")
        submitted = st.form_submit_button("Antworten absenden")
        if submitted:
            payload = {
                "timestamp_utc": datetime.utcnow().isoformat(),
                "session_id": _session_id(),
                "condition": COND,
                "final_price_eur": st.session_state.final_price or 0,
                "ended_by": "deal" if st.session_state.deal_reached else "no_deal",
                "dominance": dominance, "pressure": pressure, "fairness": fairness,
                "satisfaction": satisfaction, "trust": trust, "expertise": expertise,
                "recommend": recommend, "manipulation_power": manipulation_power,
                "comment": (comment or "").strip(),
            }
            file=_survey_path(); is_new=not file.exists()
            _save_survey_row(payload)
            st.success("Danke! Deine Antworten wurden gespeichert. ✅")

if st.session_state.show_survey: _render_survey()
