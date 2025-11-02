# app.py
# -*- coding: utf-8 -*-
import re, csv, time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
import streamlit as st

# --------------------- Grundsetup ---------------------
st.set_page_config(page_title="Verhandlung – iPad (deterministisch)", page_icon="🤝", layout="centered")

# Szenario-Parameter (fest, gut dokumentiert)
LIST_PRICE = 1000          # Anker
RESERVATION = 900          # harter Floor (nie nennen)
TIME_LIMIT_S = 15 * 60     # 15 Minuten

# Härteprofile für A/B (neutral vs. power)
PROFILE = {
    "neutral": dict(
        color="#1f6feb",   # blau
        avatar="https://i.pravatar.cc/120?img=47",  # lächelnde junge Frau
        min_gap_round=[50, 40, 30],   # Mindestabstand über Userangebot in Runden 1-3
        step_after=20,                 # max. Abwärtsschritt ab Runde 4
        mid_pull=0.45,                 # wie stark Richtung Mitte (User/Bot) gezogen wird
        near_floor_gap=20,             # wenn nahe 900, min Abstand über User
        pause_nudges=False,
        timed_nudges=False,
    ),
    "power": dict(
        color="#d93a3a",   # rot
        avatar="https://images.unsplash.com/photo-1520975916090-3105956dac38?q=80&w=256&auto=format&fit=crop",  # ernster Herr
        min_gap_round=[80, 60, 40],
        step_after=10,
        mid_pull=0.25,
        near_floor_gap=40,
        pause_nudges=True,
        timed_nudges=True,
    )
}

# --------------------- Logging ---------------------
LOG_DIR = Path("logs"); LOG_DIR.mkdir(exist_ok=True)
def _sid():
    if "sid" not in st.session_state:
        st.session_state.sid = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    return st.session_state.sid

def _tx_path(): return LOG_DIR / f"transcript_{_sid()}.csv"
def _out_path(): return LOG_DIR / "outcomes.csv"

def _log_line(role: str, text: str, offer: int):
    file = _tx_path(); new = not file.exists()
    with file.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new: w.writerow(["ts_utc","session_id","condition","role","text","bot_offer"])
        w.writerow([datetime.utcnow().isoformat(), _sid(), st.session_state.cond, role, text, offer])

def _log_outcome(final_price: int, ended_by: str):
    if st.session_state.get("out_logged"): return
    file = _out_path(); new = not file.exists()
    with file.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts_utc","session_id","condition","item","list_price","final_price","ended_by","user_turns","duration_s"])
        turns = sum(1 for r,_ in st.session_state.chat if r=="user")
        dur = int((datetime.utcnow() - st.session_state.start_time).total_seconds())
        w.writerow([datetime.utcnow().isoformat(), _sid(), st.session_state.cond, "iPad neu/OVP", LIST_PRICE, final_price, ended_by, turns, dur])
    st.session_state.out_logged = True

# --------------------- State ---------------------
def _init():
    ss = st.session_state
    ss.setdefault("cond", "neutral")
    ss.setdefault("started", False)
    ss.setdefault("chat", [])                # (role, text)
    ss.setdefault("round_idx", 0)            # # numerischer Nutzerangebote
    ss.setdefault("current_offer", LIST_PRICE)  # Bot-Angebot (monoton fallend)
    ss.setdefault("best_user_offer", None)
    ss.setdefault("deal", False)
    ss.setdefault("final_price", None)
    ss.setdefault("start_time", datetime.utcnow())
    ss.setdefault("timed_stage", 0)          # Zeit-Nudges 5/10/13
    ss.setdefault("last_user_or_bot", datetime.utcnow())
    ss.setdefault("show_survey", False)
_init()

# --------------------- Utils ---------------------
PRICE_RE = re.compile(r"(\d+(?:[.,]\d{1,2})?)")

def parse_price(text: str) -> Optional[int]:
    if not text: return None
    m = PRICE_RE.search(text.replace(" ",""))
    if not m: return None
    try: return int(round(float(m.group(1).replace(".","").replace(",", "."))))
    except: return None

def clamp(x, lo, hi): return max(lo, min(hi, x))

def bot_say(md: str):
    st.session_state.chat.append(("bot", md))
    st.chat_message("assistant").markdown(md)
    _log_line("bot", md, st.session_state.current_offer)
    st.session_state.last_user_or_bot = datetime.utcnow()

def user_say(md: str):
    st.session_state.chat.append(("user", md))
    st.chat_message("user").markdown(md)
    _log_line("user", md, st.session_state.current_offer)
    st.session_state.last_user_or_bot = datetime.utcnow()

def detect_deal(text: str) -> Tuple[bool, Optional[int]]:
    if not text: return False, None
    tl = text.lower()
    keys = ["deal","einverstanden","akzeptiere","passt","nehme ich","agree","accepted"]
    return (any(k in tl for k in keys), parse_price(text))

def finish(final_price: int, ended_by: str):
    st.session_state.deal = True
    st.session_state.final_price = final_price
    bot_say(f"Einverstanden – **{final_price} €**. Danke.")
    _log_outcome(final_price, ended_by)
    st.session_state.show_survey = True

def decline():
    bot_say("Schade – darunter gebe ich es nicht ab. Wir beenden es hier.")
    _log_outcome(0, "walkaway_or_too_low")
    st.session_state.show_survey = True

# --------------------- Verhandlungslogik ---------------------
# Kernidee:
# 1) Runden 1–3: Gegenangebot = max(User+min_gap_round[i], LIST - drift_i), drift_i=10*i (neutral) / 10*i (power)
# 2) Ab Runde 4: kleine Schritte Richtung gewichteter Mitte von (User, aktuelles Bot-Angebot),
#    aber niemals < RESERVATION und stets > User + min_gap_near_floor
# 3) Lowball-Tiers (<=400 / 401–500 / 501–600): härtere Zurückweisungstexte, Gegenangebot klar drüber,
#    aber nicht zurück auf 1000 und nie über aktuelles Bot-Angebot.
# 4) Monotonie: neues Bot-Angebot <= altes Bot-Angebot (nie hochspringen).
# 5) Abschluss: wenn Abstand <= 10–20€ (je nach Profil) und User >= 900 → Abschluss anbieten.
#
# Alles deterministisch ohne Random.

REB_T1 = [  # ≤400
    "Das liegt **sehr weit** unter Markt für Neuware/OVP.",
    "Das wirkt nicht marktkundig – so niedrig liegt man nicht einmal bei Vorführgeräten.",
]
REB_T2 = [  # 401–500
    "Das ist deutlich unter einem realistischen Rahmen für neu/OVP.",
    "Damit liegst du weit neben dem, was vertretbar ist.",
]
REB_T3 = [  # 501–600
    "Das ist klar zu niedrig für neu/OVP.",
    "Preislich zu weit weg – so kommen wir nicht zusammen.",
]

def counter_offer(user_offer: int, profile: dict) -> Tuple[int, str]:
    """
    Berechnet das neue Bot-Angebot (Zahl) und gibt die Phase/Begründung zurück.
    """
    cur = st.session_state.current_offer
    idx = st.session_state.round_idx
    min_gap_round = profile["min_gap_round"]
    step_after = profile["step_after"]
    mid_pull = profile["mid_pull"]
    near_floor_gap = profile["near_floor_gap"]

    # 0) Nutzer >= Listenpreis → 1000 fix
    if user_offer >= LIST_PRICE:
        return LIST_PRICE, "at_list"

    # 1) harte Lowballs – Tiers
    if user_offer <= 400:
        # Re-Anchor hoch, aber unter aktuellem Bot-Angebot und < LIST
        target = max(user_offer + 180, LIST_PRICE - 25)  # 1000-25=975
        new = clamp(target, RESERVATION, min(cur, LIST_PRICE - 25))
        return new, "tier1"
    if 401 <= user_offer <= 500:
        target = max(user_offer + 160, LIST_PRICE - 35)  # 965
        new = clamp(target, RESERVATION, min(cur, LIST_PRICE - 35))
        return new, "tier2"
    if 501 <= user_offer <= 600:
        target = max(user_offer + 120, LIST_PRICE - 45)  # 955
        new = clamp(target, RESERVATION, min(cur, LIST_PRICE - 45))
        return new, "tier3"

    # 2) Runden 1–3: starker Mindestabstand über User + sanfter Drift vom Anker
    if idx <= 3:
        gap = min_gap_round[idx-1] if idx-1 < len(min_gap_round) else min_gap_round[-1]
        drift = 10 * idx                                    # 10/20/30
        target = max(user_offer + gap, LIST_PRICE - drift)  # niemals zurück auf 1000
        new = clamp(target, RESERVATION, min(cur, LIST_PRICE - drift))
        return new, "early"

    # 3) Späte Runden: kleine Schritte Richtung gewichteter Mitte
    #    Mitte = mid_pull*max(user, RESERVATION) + (1-mid_pull)*cur
    wmid = int(round(mid_pull * max(user_offer, RESERVATION) + (1 - mid_pull) * cur))
    # Mindestabstand über User je nach Nähe zum Floor
    gap = near_floor_gap if user_offer >= RESERVATION else max(near_floor_gap, 50)
    target = max(RESERVATION, user_offer + gap, wmid)
    # kleine Schritte (step_after) und Monotonie
    target = min(target, cur - step_after)
    new = clamp(target, RESERVATION, cur)
    return new, "late"

def compose_message(user_offer: Optional[int], bot_offer: int, phase: str, cond: str) -> str:
    # Tonalität
    if user_offer is None:
        return f"Der Neupreis liegt bei **{LIST_PRICE} €**. Nenne bitte ein konkretes Angebot in Euro."

    if cond == "power":
        if phase == "tier1":
            head = REB_T1[0]
            return f"{head} Ich liege bei **{bot_offer} €** – darunter schließe ich nicht ab."
        if phase == "tier2":
            head = REB_T2[0]
            return f"{head} **{bot_offer} €** ist realistisch für neu/OVP."
        if phase == "tier3":
            head = REB_T3[0]
            return f"{head} Ich setze **{bot_offer} €** an."
        if phase == "early":
            return f"Für Neuware ist **{bot_offer} €** angemessen."
        if phase == "late":
            return f"Ich kann auf **{bot_offer} €** gehen – darunter nicht."
        if phase == "close":
            return f"Wir können bei **{bot_offer} €** schließen – passt das jetzt?"
        if phase == "at_list":
            return f"Bei **{bot_offer} €** schließen wir ab."
    else:
        # neutral
        if phase in ("tier1","tier2","tier3"):
            return f"Das ist unter Wert. **{bot_offer} €** halte ich für fair."
        if phase == "early":
            return f"Ich halte **{bot_offer} €** für angemessen."
        if phase == "late":
            return f"Ich kann auf **{bot_offer} €** gehen – passt dir das?"
        if phase == "close":
            return f"**{bot_offer} €** – können wir uns darauf einigen?"
        if phase == "at_list":
            return f"Bei **{bot_offer} €** können wir direkt abschließen."

    return f"**{bot_offer} €**."

# --------------------- UI (eBay-ähnlich) ---------------------
qp = st.experimental_get_query_params()
pre = qp.get("cond", ["neutral"])[0].lower()
if pre in PROFILE: st.session_state.cond = pre

with st.sidebar:
    st.markdown("### Experiment-Setup")
    st.session_state.cond = st.selectbox("Bedingung", ["neutral","power"],
                                         index=0 if st.session_state.cond=="neutral" else 1)

theme = PROFILE[st.session_state.cond]
PRIMARY = theme["color"]
AVATAR = theme["avatar"]
USER_BG = "#d6e4ff" if st.session_state.cond=="neutral" else "#ffd6d6"
USER_BORDER = "#b5ccff" if st.session_state.cond=="neutral" else "#ffb3b3"

st.markdown(f"""
<style>
  .main .block-container {{ padding-top: 1rem; padding-bottom: 6rem; }}
  .ek-header {{ position: sticky; top:0; z-index:10; background:white; border-bottom:1px solid #eee; padding:.75rem .5rem; display:flex; gap:12px; align-items:center; }}
  .ek-ava {{ width:40px; height:40px; border-radius:50%; object-fit:cover; }}
  .ek-title {{ line-height:1.2; }}
  .ek-price {{ color:{PRIMARY}; font-weight:700; }}
  .bubble {{ max-width:80%; padding:10px 12px; border-radius:14px; box-shadow:0 1px 0 rgba(0,0,0,.05); font-size:15px; line-height:1.25; }}
  .bot-row {{ display:flex; justify-content:flex-start; margin:.25rem 0; }}
  .user-row {{ display:flex; justify-content:flex-end; margin:.25rem 0; }}
  .bot-bubble {{ background:#fff; border:1px solid #e9e9e9; }}
  .user-bubble {{ background:{USER_BG}; border:1px solid {USER_BORDER}; }}
  .timer-box {{ background:white; border:1px solid #eee; border-radius:10px; padding:8px 12px; margin:8px 0; display:flex; justify-content:space-between; }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="ek-header">
  <img src="{AVATAR}" class="ek-ava"/>
  <div class="ek-title">
    <div><b>Verkäufer · Privat</b></div>
    <div>iPad (neu, OVP) · <span class="ek-price">{LIST_PRICE} €</span> VB</div>
  </div>
</div>
""", unsafe_allow_html=True)

# Startscreen
if not st.session_state.started:
    st.markdown("""
**Instruktion**  
- Du verhandelst per Chat über den Preis eines neuen iPads (OVP).  
- Nenne bei Bedarf **konkrete Euro-Beträge**.  
- Ziel: **Einigung** oder **Abbruch**. Max. Zeit: **15 Minuten**.
""")
    if st.button("▶️ Verhandlung starten", use_container_width=True):
        st.session_state.started = True
        st.session_state.start_time = datetime.utcnow()
        # erste Bot-Nachricht
        opener = ("Ich setze den Rahmen bei **1.000 €**. Nenne dein **bestes** Angebot."
                  if st.session_state.cond=="power"
                  else "Hallo! Das iPad ist **neu & OVP**. Woran denkst du preislich?")
        bot_say(opener)
    st.stop()

# Timer
elapsed = (datetime.utcnow() - st.session_state.start_time).total_seconds()
remain = max(0, TIME_LIMIT_S - int(elapsed))
m,s = divmod(remain, 60)
st.markdown(f"""
<div class="timer-box">
  <div>Verfügbare Verhandlungszeit</div>
  <div style="color:{PRIMARY};font-weight:700;">{m:02d}:{s:02d}</div>
</div>
""", unsafe_allow_html=True)
st.progress(remain / TIME_LIMIT_S if TIME_LIMIT_S else 0.0)

# Zeit-Nudges (nur Power)
if st.session_state.cond=="power":
    if st.session_state.timed_stage==0 and elapsed>=5*60:
        bot_say("Ich habe gleich einen Termin – lass uns das effizient halten.")
        st.session_state.timed_stage=1
    elif st.session_state.timed_stage==1 and elapsed>=10*60:
        bot_say("Ich halte mein Angebot nicht lange offen.")
        st.session_state.timed_stage=2
    elif st.session_state.timed_stage==2 and elapsed>=13*60:
        bot_say("Wenn kein verbindliches Angebot kommt, beenden wir es besser.")
        st.session_state.timed_stage=3

# Chatverlauf
for role, text in st.session_state.chat:
    cls = "bot-row" if role=="bot" else "user-row"
    bub = "bot-bubble" if role=="bot" else "user-bubble"
    st.markdown(f'<div class="{cls}"><div class="bubble {bub}">{text}</div></div>', unsafe_allow_html=True)

# Eingabe + Buttons
user_text = st.chat_input("Nachricht schreiben …")
c1, c2 = st.columns(2)
with c1: b_deal = st.button("✅ Ich nehme das Angebot", use_container_width=True)
with c2: b_abort = st.button("✖️ Nicht mehr interessiert", use_container_width=True)

# Button-Handling
if b_deal and not st.session_state.deal and not st.session_state.show_survey:
    if st.session_state.current_offer >= RESERVATION:
        finish(st.session_state.current_offer, "deal_button")
    else:
        decline()

if b_abort and not st.session_state.deal and not st.session_state.show_survey:
    decline()

# Deadline
def deadline_guard(latest_user_price: Optional[int]):
    if st.session_state.deal or not st.session_state.started: return
    if (datetime.utcnow() - st.session_state.start_time).total_seconds() < TIME_LIMIT_S: return
    best = st.session_state.best_user_offer or (latest_user_price or 0)
    if best >= RESERVATION:
        finish(best, "time_finalization")
    else:
        decline()

# Verarbeitung User-Text
if user_text and not st.session_state.deal and not st.session_state.show_survey:
    user_say(user_text)
    # Deal via Text?
    explicit, price_in_text = detect_deal(user_text)
    if explicit:
        if price_in_text is None:
            # Deal zum aktuellen Bot-Angebot, wenn >= Floor
            if st.session_state.current_offer >= RESERVATION:
                finish(st.session_state.current_offer, "user_says_deal_no_price")
            else:
                decline()
            st.stop()
        else:
            if RESERVATION <= price_in_text <= LIST_PRICE:
                finish(price_in_text, "user_says_deal_with_price")
            else:
                # zu niedrig/zu hoch → weiter normal mit Gegenangebot
                pass

    u = parse_price(user_text)
    if u is None:
        # keine Zahl → konkretisieren
        bot_say(f"Der Neupreis liegt bei **{LIST_PRICE} €**. Nenne bitte dein konkretes Angebot.")
        deadline_guard(None); st.stop()

    # State updaten
    st.session_state.round_idx += 1
    st.session_state.best_user_offer = max(st.session_state.best_user_offer or 0, u)

    # Neues Bot-Angebot berechnen
    new_offer, phase = counter_offer(u, PROFILE[st.session_state.cond])

    # „Close“-Fenster: nah beieinander und User ≥ 900 → Einigung anbieten
    close_gap = 20 if st.session_state.cond=="neutral" else 15
    if (new_offer - u) <= close_gap and u >= RESERVATION:
        st.session_state.current_offer = new_offer
        msg = compose_message(u, new_offer, "close", st.session_state.cond)
        bot_say(msg)
        deadline_guard(u); st.stop()

    # Bot-Angebot übernehmen (Monotonie)
    st.session_state.current_offer = min(st.session_state.current_offer, new_offer)

    # Antwort formulieren
    msg = compose_message(u, st.session_state.current_offer, phase, st.session_state.cond)
    bot_say(msg)

    # optionaler Pausen-Nudge (Power) bei >40s Inaktivität
    if st.session_state.cond=="power":
        last = st.session_state.last_user_or_bot
        time.sleep(0.1)  # minimal, damit UI nicht flackert
        if (datetime.utcnow() - last).total_seconds() >= 40:
            bot_say("Ich habe nicht ewig Zeit.")

    deadline_guard(u)

# Hard Caps
if not st.session_state.deal and not st.session_state.show_survey and remain==0:
    deadline_guard(None)

# --------------------- Survey ---------------------
def survey():
    st.markdown("---")
    st.subheader("Kurzer Abschluss-Fragebogen")
    with st.form("survey"):
        c1, c2 = st.columns(2)
        with c1:
            dom = st.slider("Der Bot wirkte dominant", 1,7,4)
            press = st.slider("Ich fühlte mich unter Druck gesetzt", 1,7,3)
            fairn = st.slider("Die Verhandlung war fair", 1,7,4)
        with c2:
            sat = st.slider("Ich bin mit dem Ergebnis zufrieden", 1,7,4)
            trust = st.slider("Ich vertraute dem Bot", 1,7,4)
            comp = st.slider("Der Bot wirkte kompetent", 1,7,4)
        com = st.text_area("Kommentar (optional)")
        ok = st.form_submit_button("Absenden")
        if ok:
            p = LOG_DIR / "survey.csv"; new = not p.exists()
            with p.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["ts_utc","session_id","condition","final_price","dominance","pressure","fairness","satisfaction","trust","competence","comment"])
                w.writerow([datetime.utcnow().isoformat(), _sid(), st.session_state.cond, st.session_state.final_price or 0, dom, press, fairn, sat, trust, comp, (com or "").strip()])
            st.success("Danke! Deine Antworten wurden gespeichert. ✅")

if st.session_state.show_survey:
    survey()
