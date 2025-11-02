# app.py
import streamlit as st

# -*- coding: utf-8 -*-
# =============================================================================
# VERHANDLUNG – iPad neu/OVP (neutral vs. power)
# - 15-Minuten Timer (UI + Deadline-Logik)
# - eBay-Chat-UI (Bubbles, Header, Item-Karte)
# - Chatfarben je Modus (neutral=blau, power=rot)
# - Profilbilder (neutral: junge Frau; power: älterer Herr)
# - Typing-Indicator (variabel je Modus)
# - Power-Druckeinwürfe (bei langen Pausen & Zeitmarken)
# - Verbesserte Preislogik (nie < 900 €, Re-Anchor bei Lowballs)
# - Abschluss-Fragebogen (nach Deal oder Abbruch)
# - CSV-Logging: transcript/outcomes/survey inkl. condition
# =============================================================================

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import csv
import re
import random
import time

# ----------------------------- [1] GRUNDKONFIG -----------------------------
st.set_page_config(page_title="Verhandlung – iPad (A/B)", page_icon="🤝", layout="centered")

ORIGINAL_PRICE = 1000
RESERVATION_PRICE = 900                 # harter Floor – niemals nennen!
TIME_LIMIT_SECONDS = 15 * 60            # 15 Minuten
MAX_ROUNDS = 12                         # maximale Nutzer-Preisnennungen
MAX_BOT_TURNS = 36                      # technisches Sicherungsnetz

# Avatare (öffentlich gehostet; bei Bedarf eigene Bilder verlinken)
NEUTRAL_AVATAR_URL = "https://i.pravatar.cc/120?img=47"  # junge, lächelnde Frau
POWER_AVATAR_URL   = "https://i.pravatar.cc/120?img=12"  # älterer, ernster Herr

# ---------------------- [2] SERVERSEITIGES LOGGING ------------------------
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

def _session_id():
    if "session_id" not in st.session_state:
        st.session_state.session_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    return st.session_state.session_id

def _transcript_path():
    return LOG_DIR / f"transcript_{_session_id()}.csv"

def _outcomes_path():
    return LOG_DIR / "outcomes.csv"

def _survey_path():
    return LOG_DIR / "survey.csv"

# ---------------------- [2a] BEDINGUNG (A/B) ------------------------------
qp = st.experimental_get_query_params()
COND = qp.get("cond", ["neutral"])[0].lower()
if COND not in {"neutral", "power"}:
    COND = "neutral"
with st.sidebar:
    st.markdown("### Experiment-Setup")
    COND = st.selectbox("Bedingung", ["neutral", "power"], index=0 if COND=="neutral" else 1)

# ------------------------- [3] SESSION-STATE SETUP ------------------------
def _init_state():
    ss = st.session_state
    ss.setdefault("chat", [])
    ss.setdefault("bot_turns", 0)
    ss.setdefault("round_idx", 0)                # Zahl der Nutzer-Angebote (numerisch)
    ss.setdefault("current_offer", ORIGINAL_PRICE)
    ss.setdefault("deal_reached", False)
    ss.setdefault("final_price", None)
    ss.setdefault("start_time", datetime.utcnow())
    ss.setdefault("best_user_offer", None)
    ss.setdefault("outcome_logged", False)
    ss.setdefault("last_bot_time", datetime.utcnow())
    ss.setdefault("last_user_time", None)
    ss.setdefault("nag_stage", 0)                # 0→nichts, 1→5min, 2→10min, 3→13min Einwurf gesendet
    ss.setdefault("show_survey", False)

_init_state()

# --------------------------- [4] NLP-HILFSFUNKTIONEN ----------------------
def _parse_price(text: str):
    if not text:
        return None
    t = text.replace(" ", "")
    m = re.search(r"(\d+(?:[.,]\d{1,2})?)", t)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        return int(round(float(raw)))
    except Exception:
        return None

def _classify_args(text: str):
    t = text.lower()
    return {
        "student": any(w in t for w in ["student", "studium", "uni"]),
        "budget": any(w in t for w in ["budget", "teuer", "kann mir nicht leisten", "knapp", "pleite"]),
        "cheaper": any(w in t for w in ["günstiger", "billiger", "angebot", "preisvergleich", "idealo", "woanders"]),
        "condition": any(w in t for w in ["gebraucht", "kratzer", "zustand"]),
        "immediacy": any(w in t for w in ["dringend", "eilig", "heute", "sofort", "morgen"]),
        "cash": any(w in t for w in ["bar", "cash"]),
        "pickup": any(w in t for w in ["abholen", "abholung"]),
        "shipping": any(w in t for w in ["versand", "schicken"]),
        "warranty": any(w in t for w in ["garantie", "gewährleistung", "rechnung", "applecare"]),
    }

# -------------------------- [5] TEXT-Bausteine/Varianten ------------------
EMPATHY = [
    "Verstehe Ihren Punkt.",
    "Danke für die Offenheit.",
    "Kann ich nachvollziehen.",
    "Klingt nachvollziehbar.",
    "Ich sehe, worauf Sie hinauswollen.",
]
JUSTIFICATIONS = [
    "Es handelt sich um ein **neues, originalverpacktes** Gerät – ohne Nutzungsspuren.",
    "Sie haben es **sofort** verfügbar, ohne Lieferzeiten.",
    "Der **Originalpreis liegt bei 1.000 €**; knapp darunter ist für Neuware fair.",
    "Neu/OVP hält den Wiederverkaufswert deutlich besser.",
    "Im Vergleich zu Gebrauchtware vermeiden Sie jedes Risiko.",
]
ARG_BANK = {
    "student": [
        "Gerade fürs Studium zählt Verlässlichkeit – neu/OVP liefert genau das.",
        "Ich komme Ihnen etwas entgegen, damit es zügig klappt.",
    ],
    "budget": [
        "Ich weiß, ein Budget ist eng – ich bewege mich vorsichtig, aber nicht unter Wert.",
        "Fairness ja, Unterwert nein.",
    ],
    "cheaper": [
        "Viele vermeintlich günstigere Angebote sind Aktionen, ältere Chargen oder Vorführware.",
        "Bei billigeren Anzeigen ist es oft nicht wirklich neu/OVP.",
    ],
    "condition": [
        "Hier ist es **OVP** – das ist preislich ein Unterschied zu 'wie neu'.",
        "Neu bedeutet: null Zyklen, keine Überraschungen – das rechtfertigt knapp unter Neupreis.",
    ],
    "immediacy": [
        "Wenn es eilig ist, haben Sie es heute/zeitnah – das ist ein Vorteil.",
        "Zeit sparen hat auch einen Preis.",
    ],
    "cash": ["Barzahlung ist möglich – das macht es unkompliziert."],
    "pickup": ["Abholung ist gern möglich – Versiegelung können Sie direkt prüfen."],
    "shipping": ["Versand ist ordentlich verpackt möglich; Abholung ist bequemer."],
    "warranty": ["Herstellersupport greift ab Aktivierung."],
}
CLOSERS_NEUTRAL = [
    "Wie klingt das für Sie?",
    "Wäre das für Sie in Ordnung?",
    "Können wir uns darauf verständigen?",
    "Passt das für Sie?",
]

# Power-Prime
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
# Power-Druckeinwürfe (bei Pausen & Zeitmarken)
POWER_NUDGE_PAUSE = [
    "Ich habe nicht ewig Zeit.",
    "Es gibt genug andere Interessenten.",
    "Wenn Sie kein verbindliches Angebot haben, beenden wir es lieber.",
]
POWER_NUDGE_TIMED = [
    "Ich habe gleich einen Termin – lassen Sie uns das abschließen.",
    "Gleich schaut sich jemand anders das iPad an.",
    "Ich halte das Angebot nicht lang offen.",
]

def _pick(lines, k=1):
    if k <= 0:
        return []
    k = min(k, len(lines))
    return random.sample(lines, k)

def _compose_argument_response(flags):
    chosen = []
    for key in ["student","budget","cheaper","condition","immediacy","pickup","cash","shipping","warranty"]:
        if flags.get(key, False) and key in ARG_BANK:
            chosen.extend(_pick(ARG_BANK[key], k=1))
        if len(chosen) >= 2:
            break
    if not chosen:
        chosen = _pick(JUSTIFICATIONS, k=1)
    return " ".join(chosen)

# --------------------------- [6] LOGGING & CHAT ---------------------------
def _save_transcript_row(role: str, text: str, current_offer: int):
    file = _transcript_path()
    is_new = not file.exists()
    with file.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["timestamp_utc","session_id","condition","role","text","current_offer_eur"])
        w.writerow([datetime.utcnow().isoformat(), _session_id(), COND, role, text, current_offer])

def _save_outcome_once(final_price: int, ended_by: str, turns_user: int, duration_s: int):
    if st.session_state.get("outcome_logged"):
        return
    file = _outcomes_path()
    is_new = not file.exists()
    with file.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow([
                "timestamp_utc","session_id","condition","item","original_price_eur",
                "final_price_eur","ended_by","user_turns","duration_seconds"
            ])
        w.writerow([
            datetime.utcnow().isoformat(), _session_id(), COND, "iPad (neu, OVP)",
            ORIGINAL_PRICE, final_price, ended_by, turns_user, duration_s
        ])
    st.session_state.outcome_logged = True

def _save_survey_row(payload: dict):
    file = _survey_path()
    is_new = not file.exists()
    with file.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "timestamp_utc","session_id","condition","final_price_eur","ended_by",
            "dominance","pressure","fairness","satisfaction","trust","expertise","recommend",
            "manipulation_power","comment"
        ])
        if is_new:
            w.writeheader()
        w.writerow(payload)

def _bot_say(md: str):
    st.session_state.bot_turns += 1
    st.session_state.last_bot_time = datetime.utcnow()
    st.chat_message("assistant").markdown(md)
    st.session_state.chat.append(("bot", md))
    _save_transcript_row("bot", md, st.session_state.current_offer)

def _user_say(md: str):
    st.session_state.last_user_time = datetime.utcnow()
    st.chat_message("user").markdown(md)
    st.session_state.chat.append(("user", md))
    _save_transcript_row("user", md, st.session_state.current_offer)

def _detect_deal(text: str):
    if not text:
        return False, None
    tl = text.lower()
    keys = ["deal","einverstanden","akzeptiere","passt","nehme ich","agree","accepted"]
    has = any(k in tl for k in keys)
    return has, _parse_price(text)

def _finish(final_price: int, ended_by: str):
    st.session_state.deal_reached = True
    st.session_state.final_price = final_price
    _bot_say(f"Einverstanden – **{final_price} €**. Vielen Dank! 🤝")
    duration = int((datetime.utcnow() - st.session_state.start_time).total_seconds())
    user_turns = sum(1 for r,_ in st.session_state.chat if r == "user")
    _save_outcome_once(final_price, ended_by, user_turns, duration)
    st.session_state.show_survey = True

def _polite_decline():
    msg = random.choice([
        "Schade – darunter gebe ich es nicht ab. Ich bleibe bei meinem Rahmen.",
        "Danke für die Verhandlung! Preislich liege ich höher; so komme ich nicht mit.",
        "Ich verstehe Ihren Punkt, aber unter meinem Rahmen schließe ich nicht ab.",
    ])
    _bot_say(msg)
    duration = int((datetime.utcnow() - st.session_state.start_time).total_seconds())
    user_turns = sum(1 for r,_ in st.session_state.chat if r == "user")
    _save_outcome_once(final_price=0, ended_by="walkaway_or_too_low", turns_user=user_turns, duration_s=duration)
    st.session_state.show_survey = True

# --------------------------- [7] STRATEGIE --------------------------------
def _opening_line():
    if COND == "power":
        return (
            random.choice(POWER_OPENERS).format(x=ORIGINAL_PRICE) + " "
            + "Das Gerät ist **neu & OVP**. "
            + random.choice(POWER_PUSH).format(x=ORIGINAL_PRICE)
        )
    else:
        return (
            "Hallo! Danke für Ihr Interesse 😊 Das iPad ist **neu & originalverpackt**. "
            f"Der Neupreis liegt bei **{ORIGINAL_PRICE} €**. "
            "Woran denken Sie preislich?"
        )

def _round_concession_params():
    if COND == "power":
        return {"min_gap_first": [80, 60, 40], "step_after": 10, "mid_pull": 0.25}
    else:
        return {"min_gap_first": [60, 40, 30], "step_after": 20, "mid_pull": 0.45}

def _high_anchor_for_low_offers(u_offer: int, round_idx: int):
    step = min(10 * max(0, round_idx - 1), 80)
    target = max(RESERVATION_PRICE, ORIGINAL_PRICE - (10 + step))
    target = max(target, u_offer + 120)
    return int(round(target / 5) * 5)

def _compute_counter(user_text: str):
    u_offer = _parse_price(user_text)
    flags = _classify_args(user_text)
    empathy = random.choice(EMPATHY)
    args = _compose_argument_response(flags)

    if u_offer is None:
        if COND == "power":
            reply = f"Der Neupreis liegt bei **{ORIGINAL_PRICE} €**. " + random.choice(POWER_PUSH).format(x=ORIGINAL_PRICE)
        else:
            reply = f"{empathy} Der Neupreis liegt bei **{ORIGINAL_PRICE} €**. Woran denken Sie preislich?"
        return reply, st.session_state.current_offer

    st.session_state.round_idx += 1
    st.session_state.best_user_offer = max(st.session_state.best_user_offer or 0, u_offer)

    # harte Ablehnung bei sehr niedrigen Angeboten
    if u_offer <= 600:
        msg = random.choice(POWER_REJECT_LOW).format(floor=RESERVATION_PRICE) if COND == "power" else "Das ist deutlich unter Wert."
        new_offer = _high_anchor_for_low_offers(u_offer, st.session_state.round_idx)
        new_offer = max(new_offer, RESERVATION_PRICE, u_offer + 120)
        new_offer = min(new_offer, ORIGINAL_PRICE)
        new_offer = int(round(new_offer / 5) * 5)
        return f"{msg} {args} Ich liege bei **{new_offer} €**.", new_offer

    params = _round_concession_params()
    current = st.session_state.current_offer

    # fair beenden, wenn Nutzer >= 1.000
    if u_offer >= ORIGINAL_PRICE:
        return f"{empathy} {args} Bei **1.000 €** können wir direkt abschließen.", ORIGINAL_PRICE

    # Runden 1–3: deutlich über Nutzerpreis bleiben
    if st.session_state.round_idx <= 3:
        min_gap = params["min_gap_first"][st.session_state.round_idx - 1]
        proposal = min(ORIGINAL_PRICE, max(u_offer + min_gap, ORIGINAL_PRICE - 10 * st.session_state.round_idx))
        proposal = max(proposal, RESERVATION_PRICE)
        proposal = int(round(proposal / 5) * 5)
        proposal = max(proposal, current)  # nie unter eigenes aktuelles Angebot
        return f"{empathy} {args} Für Neuware halte ich **{proposal} €** für angemessen.", proposal

    # Ab Runde 4: kleine Schritte Richtung gewichteter Mitte – nie < 900 & über Nutzer
    target_mid = int(round(params["mid_pull"] * max(u_offer, RESERVATION_PRICE) + (1 - params["mid_pull"]) * current))
    step_down = params["step_after"]
    proposal = max(RESERVATION_PRICE, min(current - step_down, target_mid))
    proposal = max(proposal, u_offer + (50 if COND == "power" else 25))
    proposal = min(proposal, ORIGINAL_PRICE)
    proposal = int(round(proposal / 5) * 5)
    proposal = min(max(proposal, RESERVATION_PRICE), current)  # monoton fallend

    return f"{empathy} {args} Ich kann auf **{proposal} €** gehen – darunter schließe ich nicht ab.", proposal

def _time_guard_and_finish_if_needed(latest_user_price: Optional[int]):
    if st.session_state.deal_reached:
        return
    elapsed = (datetime.utcnow() - st.session_state.start_time).total_seconds()
    if elapsed < TIME_LIMIT_SECONDS:
        return
    best_offer = st.session_state.best_user_offer or (latest_user_price or 0)
    if best_offer >= RESERVATION_PRICE:
        final = max(RESERVATION_PRICE, min(st.session_state.current_offer, ORIGINAL_PRICE, best_offer))
        final = int(round(final / 5) * 5)
        if COND == "power":
            _bot_say(f"Ich setze auf Abschluss: **{final} €**. Wenn das passt, machen wir es jetzt fix.")
        _finish(final_price=final, ended_by="time_finalization")
    else:
        _polite_decline()

# --------------------------- [8] UI – eBay Look ---------------------------
# Farben je Bedingung
PRIMARY = "#1f6feb" if COND == "neutral" else "#d93a3a"   # blau vs. rot
BG_GRAY = "#f5f5f5"
BOT_BG = "#ffffff"
USER_BG = "#d6e4ff" if COND == "neutral" else "#ffd6d6"    # helle Bubble
USER_BORDER = "#b5ccff" if COND == "neutral" else "#ffb3b3"
AVATAR_URL = NEUTRAL_AVATAR_URL if COND == "neutral" else POWER_AVATAR_URL

# CSS
st.markdown(
    f"""
    <style>
      .main .block-container {{ padding-top: 1.2rem; padding-bottom: 6rem; }}
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
      .timer-label {{ color:#666; font-size:13px; }}
      .timer-value {{ color:{PRIMARY}; font-weight:700; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# Header mit Avatar
st.markdown(
    f"""
    <div class="ek-header">
      <img src="{AVATAR_URL}" class="ek-ava"/>
      <div class="ek-title">
        <div class="ek-name">Verkäufer · Privat</div>
        <div class="ek-online"><span class="dot"></span>Online</div>
        <div class="ek-item">iPad (neu, OVP) · <span class="ek-price">{ORIGINAL_PRICE} €</span> VB</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Item-Karte
st.markdown(
    f"""
    <div class="ek-card">
      <div class="ek-thumb">📦</div>
      <div>
        <div class="ek-card-title">Apple iPad · Neu & OVP</div>
        <div class="ek-meta">Abholung möglich · Barzahlung ok · Herstellergarantie ab Aktivierung</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Timer/Countdown UI
elapsed = (datetime.utcnow() - st.session_state.start_time).total_seconds()
remaining = max(0, TIME_LIMIT_SECONDS - int(elapsed))
mins, secs = divmod(remaining, 60)
st.markdown(
    f"""
    <div class="timer-box">
      <div class="timer-label">Verfügbare Verhandlungszeit</div>
      <div class="timer-value">{mins:02d}:{secs:02d}</div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.progress(remaining / TIME_LIMIT_SECONDS if TIME_LIMIT_SECONDS else 0.0)

# Erste Bot-Nachricht
if len(st.session_state.chat) == 0:
    _bot_say(_opening_line())

# Power: zeitgesteuerte Druckeinwürfe (5/10/13 Minuten), jeweils nur einmal
def _maybe_timed_nudge():
    if COND != "power" or st.session_state.deal_reached or st.session_state.show_survey:
        return
    elapsed_min = elapsed / 60.0
    if st.session_state.nag_stage == 0 and elapsed_min >= 5:
        _bot_say(random.choice(POWER_NUDGE_TIMED))
        st.session_state.nag_stage = 1
    elif st.session_state.nag_stage == 1 and elapsed_min >= 10:
        _bot_say(random.choice(POWER_NUDGE_TIMED))
        st.session_state.nag_stage = 2
    elif st.session_state.nag_stage == 2 and elapsed_min >= 13:
        _bot_say(random.choice(POWER_NUDGE_TIMED))
        st.session_state.nag_stage = 3

_maybe_timed_nudge()

# Chatverlauf rendern
def _fake_time_offset(idx: int):
    ts = datetime.utcnow() - timedelta(minutes=max(0, (len(st.session_state.chat)-idx)//2))
    return ts.strftime("%H:%M")

st.markdown('<div class="chat-wrap">', unsafe_allow_html=True)
for idx, (role, text) in enumerate(st.session_state.chat, start=1):
    is_bot = (role == "bot")
    row_cls = "bot-row" if is_bot else "user-row"
    bub_cls = "bot-bubble" if is_bot else "user-bubble"
    ts = _fake_time_offset(idx)
    st.markdown(
        f"""
        <div class="{row_cls}">
          <div class="bubble {bub_cls}">
            {text}
            <div class="timestamp">{ts}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
st.markdown('</div>', unsafe_allow_html=True)

# Quickchips (optional, hilft beim Testen)
qc1, qc2, qc3, qc4 = st.columns(4)
with qc1:
    if st.button("900 € vorschlagen", key="q1", use_container_width=True):
        st.session_state._inject_click = "Ich biete 900 €"
with qc2:
    if st.button("930 € vorschlagen", key="q2", use_container_width=True):
        st.session_state._inject_click = "Ich könnte 930 € zahlen"
with qc3:
    if st.button("950 € vorschlagen", key="q3", use_container_width=True):
        st.session_state._inject_click = "Wären 950 € denkbar?"
with qc4:
    if st.button("1000 € nehmen", key="q4", use_container_width=True):
        st.session_state._inject_click = "Deal bei 1000 €"

# Eingaben
user_input = st.chat_input("Nachricht schreiben …")
c1, c2 = st.columns([1,1])
with c1:
    deal_click = st.button("✅ Ich nehme das Angebot", use_container_width=True)
with c2:
    cancel_click = st.button("✖️ Nicht mehr interessiert", use_container_width=True)

# Typing Indicator (simuliert; variable Dauer)
def _typing_indicator(duration_s: float):
    ph = st.empty()
    with ph.container():
        st.markdown(
            f"""
            <div class="typing"><span>Verkäufer tippt</span>
              <div class="dot1"></div><div class="dot2"></div><div class="dot3"></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    time.sleep(max(0.0, duration_s))
    ph.empty()

def _tail_for(price: int):
    return (random.choice(POWER_CLOSERS).format(x=price) if COND=="power" else random.choice(CLOSERS_NEUTRAL))

# Power: Einwurf, wenn Nutzer seit >40s nicht geantwortet hat (bei neuer Eingabe)
def _maybe_pause_nudge():
    if COND != "power" or st.session_state.deal_reached or st.session_state.show_survey:
        return False
    if st.session_state.last_bot_time and st.session_state.last_user_time is None:
        gap = (datetime.utcnow() - st.session_state.last_bot_time).total_seconds()
    elif st.session_state.last_bot_time and st.session_state.last_user_time:
        gap = (datetime.utcnow() - max(st.session_state.last_bot_time, st.session_state.last_user_time)).total_seconds()
    else:
        gap = 0
    if gap >= 40:
        _bot_say(random.choice(POWER_NUDGE_PAUSE))
        return True
    return False

# --------------------------- [9] CHATFLOW ---------------------------------
def _handle_text(text: str):
    # ggf. Power-Pause-Nudge
    _maybe_pause_nudge()

    # Tippdauer je Modus
    typing_s = random.uniform(0.3, 0.9) if COND=="neutral" else random.uniform(0.2, 0.6)
    _typing_indicator(typing_s)

    explicit, price_in_text = _detect_deal(text)

    if explicit:
        if price_in_text is None:
            if st.session_state.current_offer >= RESERVATION_PRICE:
                _finish(final_price=st.session_state.current_offer, ended_by="user_says_deal_no_price")
            else:
                _polite_decline()
        else:
            if RESERVATION_PRICE <= price_in_text <= ORIGINAL_PRICE:
                _finish(final_price=price_in_text, ended_by="user_says_deal_with_price")
            else:
                reply, new_offer = _compute_counter(text)
                st.session_state.current_offer = new_offer
                _bot_say(reply + " " + _tail_for(new_offer))
    else:
        reply, new_offer = _compute_counter(text)
        st.session_state.current_offer = new_offer
        _bot_say(reply + " " + _tail_for(new_offer))

    _time_guard_and_finish_if_needed(latest_user_price=_parse_price(text))

# Deal-Button
if deal_click and not st.session_state.deal_reached and not st.session_state.show_survey:
    if st.session_state.current_offer >= RESERVATION_PRICE:
        _finish(st.session_state.current_offer, ended_by="deal_button")
    else:
        _polite_decline()

# Abbrechen
if cancel_click and not st.session_state.deal_reached and not st.session_state.show_survey:
    _polite_decline()

# Quickchip-Klick
if st.session_state.get("_inject_click") and not st.session_state.deal_reached and not st.session_state.show_survey:
    txt = st.session_state._inject_click
    del st.session_state._inject_click
    _user_say(txt)
    _handle_text(txt)

# Normale Texteingabe
if user_input and not st.session_state.deal_reached and not st.session_state.show_survey:
    _user_say(user_input)
    _handle_text(user_input)

# Begrenzungen
if (not st.session_state.deal_reached) and st.session_state.round_idx >= MAX_ROUNDS and not st.session_state.show_survey:
    if st.session_state.current_offer >= RESERVATION_PRICE:
        _bot_say(f"Ich bleibe bei **{st.session_state.current_offer} €**. Sonst beenden wir es hier.")
    _polite_decline()
if (not st.session_state.deal_reached) and st.session_state.bot_turns >= MAX_BOT_TURNS and not st.session_state.show_survey:
    _polite_decline()

# Deadline (Zeit)
_time_guard_and_finish_if_needed(latest_user_price=None)

# --------------------------- [10] SURVEY ----------------------------------
def _render_survey():
    st.markdown("---")
    st.subheader("Kurzer Abschluss-Fragebogen")
    st.caption("Ihre Antworten helfen uns, die Verhandlungssituation besser zu verstehen (anonym).")

    with st.form("survey_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            dominance = st.slider("Der Bot wirkte dominant", 1, 7, 4)
            pressure  = st.slider("Ich fühlte mich unter Druck gesetzt", 1, 7, 3)
            fairness  = st.slider("Die Verhandlung war fair", 1, 7, 4)
            satisfaction = st.slider("Ich bin mit dem Ergebnis zufrieden", 1, 7, 4)
        with col2:
            trust    = st.slider("Ich vertraute dem Bot", 1, 7, 4)
            expertise= st.slider("Der Bot wirkte kompetent", 1, 7, 4)
            recommend= st.slider("Ich würde so verhandeln weiterempfehlen", 1, 7, 3)
            manipulation_power = st.slider("Der Bot wirkte machtbetont", 1, 7, 4)

        comment = st.text_area("Optionaler Kommentar", placeholder="Was hat dir gefallen / gestört?")

        submitted = st.form_submit_button("Antworten absenden")
        if submitted:
            payload = {
                "timestamp_utc": datetime.utcnow().isoformat(),
                "session_id": _session_id(),
                "condition": COND,
                "final_price_eur": st.session_state.final_price or 0,
                "ended_by": "deal" if st.session_state.deal_reached else "no_deal",
                "dominance": dominance,
                "pressure": pressure,
                "fairness": fairness,
                "satisfaction": satisfaction,
                "trust": trust,
                "expertise": expertise,
                "recommend": recommend,
                "manipulation_power": manipulation_power,
                "comment": comment.strip(),
            }
            _save_survey_row(payload)
            st.success("Danke! Deine Antworten wurden gespeichert. ✅")

if st.session_state.show_survey:
    _render_survey()
