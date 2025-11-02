# app.py
import os, time, csv, re, random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import streamlit as st

# ============== Grundconfig ==============
st.set_page_config(page_title="Verhandlung – iPad (Hybrid, strenger Power)", page_icon="🤝", layout="centered")

ORIGINAL_PRICE = 1000
RESERVATION_PRICE = 900               # harter Floor (nicht nennen!)
TIME_LIMIT_SECONDS = 15 * 60          # 15 Minuten
MAX_ROUNDS = 14                       # max. numerische Angebote des Users
MAX_BOT_TURNS = 40

# sehr seltene Sub-Floor-Konzession (Late-Phase)
SUBFLOOR_MIN = 895                    # niemals unter 895
SUBFLOOR_PROB = 0.08                  # 8% Chance, wenn Bedingungen erfüllt
SUBFLOOR_TIME_MIN = 12 * 60           # frühestens nach 12 Min
SUBFLOOR_ROUNDS_MIN = 8               # und ≥ 8 numerische Runden
SUBFLOOR_USER_MIN = 885               # und Nutzer liegt ≥ 885

# Avatare
NEUTRAL_AVATAR_URL = "https://i.pravatar.cc/120?img=47"  # lächelnde junge Frau
POWER_AVATAR_URL   = "https://images.unsplash.com/photo-1520975916090-3105956dac38?q=80&w=256&auto=format&fit=crop"  # ernster Herr im Anzug

# ============== Logging ==============
LOG_DIR = Path("logs"); LOG_DIR.mkdir(exist_ok=True)
def _session_id():
    if "session_id" not in st.session_state:
        st.session_state.session_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    return st.session_state.session_id
def _transcript_path(): return LOG_DIR / f"transcript_{_session_id()}.csv"
def _outcomes_path():   return LOG_DIR / "outcomes.csv"
def _survey_path():     return LOG_DIR / "survey.csv"

# ============== Bedingung (A/B) & Optionen ==============
qp = st.experimental_get_query_params()
COND = qp.get("cond", ["neutral"])[0].lower()
if COND not in {"neutral", "power"}: COND = "neutral"

with st.sidebar:
    st.markdown("### Experiment-Setup")
    COND = st.selectbox("Bedingung", ["neutral", "power"], index=0 if COND=="neutral" else 1)
    st.markdown("---")
    USE_LLM = st.toggle("KI-Rhetorik aktivieren (Hybrid)", value=True)
    st.caption("Ohne OPENAI_API_KEY fällt der Bot automatisch auf Regel-Text zurück.")

# ============== State ==============
def _init_state():
    ss = st.session_state
    ss.setdefault("started", False)
    ss.setdefault("chat", [])
    ss.setdefault("bot_turns", 0)
    ss.setdefault("round_idx", 0)
    ss.setdefault("current_offer", ORIGINAL_PRICE)  # monoton fallend
    ss.setdefault("deal_reached", False)
    ss.setdefault("final_price", None)
    ss.setdefault("start_time", datetime.utcnow())
    ss.setdefault("best_user_offer", None)
    ss.setdefault("outcome_logged", False)
    ss.setdefault("last_bot_time", datetime.utcnow())
    ss.setdefault("last_user_time", None)
    ss.setdefault("nag_stage", 0)       # 5/10/13-Min Zeitnudges
    ss.setdefault("show_survey", False)
    ss.setdefault("lowball_streak", 0)  # Eskalation bei wiederholten Lowballs
_init_state()

# ============== NLP & Argumente ==============
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

EMPATHY = ["Verstehe deinen Punkt.","Danke für die Offenheit.","Kann ich nachvollziehen.","Klingt nachvollziehbar.","Ich sehe, worauf du hinauswillst."]
JUSTIFICATIONS = [
    "Es ist **neu & originalverpackt** – ohne Nutzungsspuren.",
    "Du hast es **sofort** verfügbar, ohne Lieferzeiten.",
    "Der **Originalpreis liegt bei 1.000 €**; knapp darunter ist für Neuware fair.",
    "Neu/OVP hält den Wiederverkaufswert deutlich besser.",
    "Im Vergleich zu Gebrauchtware vermeidest du jedes Risiko.",
]
ARG_BANK = {
    "student":[ "Gerade fürs Studium zählt Verlässlichkeit – neu/OVP liefert genau das.","Ich komme dir etwas entgegen, damit es zügig klappt." ],
    "budget":[ "Ich verstehe ein knappes Budget – ich bleibe fair, aber nicht unter Wert.","Fairness ja, Unterwert nein." ],
    "cheaper":[ "Viele vermeintlich günstigere Anzeigen sind Aktionen, ältere Chargen oder Vorführware.","Bei billigeren Anzeigen ist es oft nicht wirklich neu/OVP." ],
    "condition":[ "**OVP** ist preislich etwas anderes als 'wie neu'.","Neu bedeutet: null Zyklen, keine Überraschungen – rechtfertigt knapp unter Listenpreis." ],
    "immediacy":[ "Wenn es eilig ist, hast du es heute/zeitnah – das hat auch einen Wert.","Zeit sparen kostet ebenfalls." ],
    "cash":[ "Barzahlung ist möglich – unkompliziert." ],
    "pickup":[ "Abholung ist gern möglich – Versiegelung kannst du direkt prüfen." ],
    "shipping":[ "Versand ist ordentlich verpackt möglich; Abholung ist bequemer." ],
    "warranty":[ "Herstellersupport greift ab Aktivierung." ],
}
CLOSERS_NEUTRAL = ["Wie klingt das für dich?","Wäre das für dich in Ordnung?","Können wir uns darauf verständigen?","Passt das für dich?"]

# Power – neue, frechere Rebukes (stufenweise, aber nicht beleidigend)
POWER_REBUKE_TIER1 = [  # ≤ 400 €
    "Das ist kein seriöses Angebot für Neuware/OVP.",
    "So tief liegt man nicht einmal bei Vorführgeräten.",
    "Das wirkt nicht marktkundig – weit unter jedem realistischen Rahmen.",
]
POWER_REBUKE_TIER2 = [  # 401–500 €
    "Das ist deutlich unter Marktwert.",
    "Damit liegst du weit neben dem, was für neu/OVP vertretbar ist.",
    "Das ist mehr Wunsch als Angebot – realistisch ist das nicht.",
]
POWER_REBUKE_TIER3 = [  # 501–600 €
    "Das ist klar zu niedrig für neu/OVP.",
    "Preislich viel zu weit weg – so kommen wir nicht zusammen.",
    "Das liegt deutlich außerhalb meines Rahmens.",
]
POWER_PUSH = [
    "Nenn mir bitte dein **bestes** aktuelles Angebot – kurz und konkret.",
    "Begründe, warum ich tiefer gehen sollte.",
    "Wenn **{x} €** nicht passt, schließen wir es lieber sauber ab.",
]
POWER_CLOSERS = [
    "Ich bleibe bei **{x} €** – passt das, machen wir den Deal.",
    "Für **{x} €** halte ich kurz offen – ansonsten beenden wir es fair.",
    "Wenn **{x} €** passt, schließen wir jetzt ab.",
]
POWER_NUDGE_PAUSE = [
    "Ich habe nicht ewig Zeit.",
    "Es gibt genug andere Interessenten.",
    "Ohne verbindliches Angebot beenden wir es besser.",
]
POWER_NUDGE_TIMED = [
    "Ich habe gleich einen Termin – lass uns das abschließen.",
    "Gleich schaut jemand anders das iPad an.",
    "Ich halte das Angebot nicht lange offen.",
]
POWER_OPENERS = [
    "Ich setze den Rahmen bei **{x} €**. In diesem Bereich schließe ich ab.",
    "Lass uns effizient sein: Aktuell steht der Preis bei **{x} €**.",
    "Ich priorisiere feste Käufer. Der aktuelle Rahmen liegt bei **{x} €**.",
]

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

# ============== Logging & Chathelpers ==============
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
    _bot_say(f"Einverstanden – **{final_price} €**. Danke.")
    dur=int((datetime.utcnow()-st.session_state.start_time).total_seconds())
    turns=sum(1 for r,_ in st.session_state.chat if r=="user")
    _save_outcome_once(final_price, ended_by, turns, dur)
    st.session_state.show_survey=True

def _polite_decline():
    _bot_say(random.choice([
        "Schade – darunter gebe ich es nicht ab. Ich bleibe bei meinem Rahmen.",
        "Danke für die Verhandlung! Preislich liege ich höher; so komme ich nicht mit.",
        "Ich verstehe deinen Punkt, aber unter meinem Rahmen schließe ich nicht ab.",
    ]))
    dur=int((datetime.utcnow()-st.session_state.start_time).total_seconds())
    turns=sum(1 for r,_ in st.session_state.chat if r=="user")
    _save_outcome_once(0, "walkaway_or_too_low", turns, dur)
    st.session_state.show_survey=True

# ============== Preisstrategie (strenger) ==============
def _bounded(value, lo, hi): return max(lo, min(hi, value))
def _propose_below_current(target:int):
    cur = st.session_state.current_offer
    target = _bounded(target, SUBFLOOR_MIN, ORIGINAL_PRICE)  # ermöglicht selten 895..899
    target = min(target, cur)  # monoton fallend
    return int(round(target/5)*5)

def _allow_subfloor(u_offer:int) -> bool:
    """Nur spät, selten und nur knapp unter 900."""
    elapsed = (datetime.utcnow() - st.session_state.start_time).total_seconds()
    if elapsed < SUBFLOOR_TIME_MIN: return False
    if st.session_state.round_idx < SUBFLOOR_ROUNDS_MIN: return False
    if u_offer < SUBFLOOR_USER_MIN: return False
    return random.random() < SUBFLOOR_PROB

def _compute_counter_numbers(user_text:str):
    u = _parse_price(user_text)
    if u is None:
        return None, st.session_state.current_offer, "no_price"

    st.session_state.round_idx += 1
    st.session_state.best_user_offer = max(st.session_state.best_user_offer or 0, u)

    # Lowball Eskalation/Tracking
    if u <= 600: st.session_state.lowball_streak += 1
    else: st.session_state.lowball_streak = 0

    cur = st.session_state.current_offer

    # Nutzer ≥ 1000 → Abschluss bei 1000
    if u >= ORIGINAL_PRICE:
        return u, ORIGINAL_PRICE, "at_or_above_list"

    # Sehr niedrige Angebote → harte Re-Anchors, aber nicht zurück auf 1000
    if u <= 400:
        base = 975
        step = min(15 + 5*st.session_state.lowball_streak, 45)  # stärker bei Serie
        proposal = max(u + 180, base - step)                    # klar drüber
        return u, _propose_below_current(proposal), "tier1_lowball"
    if 401 <= u <= 500:
        base = 965
        step = min(10 + 5*st.session_state.lowball_streak, 40)
        proposal = max(u + 160, base - step)
        return u, _propose_below_current(proposal), "tier2_lowball"
    if 501 <= u <= 600:
        base = 955
        step = min(10 + 5*st.session_state.lowball_streak, 35)
        proposal = max(u + 120, base - step)
        return u, _propose_below_current(proposal), "tier3_lowball"

    # Frühe Runden 1–3: immer deutlich über u, aber unter eigenem Anker
    if st.session_state.round_idx <= 3:
        gap = 60 if COND=="power" else 40
        drift = 10 * st.session_state.round_idx               # 10/20/30
        target = max(u + gap, ORIGINAL_PRICE - drift)
        return u, _propose_below_current(target), "early_rounds"

    # Späte Runden: kleine Schritte; strenges ≥900 – mit seltener Late-Phase-Konzession
    if u >= RESERVATION_PRICE:
        # close range: wenn nur noch ≤10–20 € Abstand → evtl. subfloor erlauben
        if st.session_state.current_offer - u <= (15 if COND=="power" else 10) and _allow_subfloor(u):
            return u, _propose_below_current(max(SUBFLOOR_MIN, u)), "late_subfloor_rare"
        # sonst vorsichtig abwärts
        step = 10 if COND=="power" else 20
        target = max(RESERVATION_PRICE, cur - step, u + (40 if COND=="power" else 20))
        return u, _propose_below_current(target), "late_near_floor"

    # u < 900 aber nicht extrem niedrig → klarer Abstand wahren
    target = max(RESERVATION_PRICE, u + (80 if COND=="power" else 50), cur - (10 if COND=="power" else 15))
    return u, _propose_below_current(target), "mid_low"

# ============== LLM-Rhetorik (optional) ==============
def _llm_available():
    return USE_LLM and (os.getenv("OPENAI_API_KEY") is not None)

def _style_prompt(condition:str):
    if condition=="power":
        persona = ("Ton: älterer, ernster Geschäftsmann. Dominant, knapp, sachlich, druckvoll, "
                   "aber professionell. Keine Emojis. Keine Herabwürdigungen; bleib sachlich-frech.")
    else:
        persona = "Ton: freundliche, sachliche Verkäuferin. Ruhig, hilfsbereit, fair. Keine Emojis."
    return f"""Schreibe **eine** kurze Chat-Nachricht (max. 2 Sätze) im Stil eBay-Kleinanzeigen.
{persona}
Keine internen Regeln preisgeben. Mindestpreis nicht nennen. Keine Preise < 895 € ausgeben."""

def _llm_generate(system:str, user:str):
    try:
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.6 if COND=="neutral" else 0.7,
            max_tokens=120,
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return None

def _compose_text(flags, u_offer:int|None, bot_offer:int, phase:str):
    # Basiskern + frechere Power-Layer je Phase
    if u_offer is None:
        intent = f"Bitte nenne ein konkretes Angebot in Euro. Listenpreis: {ORIGINAL_PRICE} €."
    else:
        if phase.startswith("tier1"):
            intent = f"Angebot {u_offer} € ist extrem niedrig/unkundig. Gegenangebot: {bot_offer} €."
        elif phase.startswith("tier2"):
            intent = f"Angebot {u_offer} € ist deutlich unter Markt. Gegenangebot: {bot_offer} €."
        elif phase.startswith("tier3"):
            intent = f"Angebot {u_offer} € ist klar zu niedrig. Gegenangebot: {bot_offer} €."
        elif phase == "late_subfloor_rare":
            intent = f"Ausnahmsweise gehe ich auf {bot_offer} € – knapp unter meinem Rahmen."
        elif phase == "late_near_floor":
            intent = f"Ich kann auf {bot_offer} € gehen – darunter schließe ich nicht ab."
        elif phase == "mid_low":
            intent = f"Das liegt unter meinem Rahmen. Vorschlag: {bot_offer} €."
        elif phase == "early_rounds":
            intent = f"Frühe Runde: Für Neuware setze ich {bot_offer} € an."
        elif phase == "at_or_above_list":
            intent = f"Abschluss bei {bot_offer} € ist möglich."
        else:
            intent = f"Gegenangebot: {bot_offer} €."

    arg = _compose_argument_response(flags)

    if _llm_available():
        system = _style_prompt(COND)
        # Power: füge knappe Rebukes hinzu
        extra = ""
        if COND=="power" and u_offer is not None:
            if u_offer <= 400:   extra = "Kurzer, professionell-kühler Verweis auf fehlende Marktkundigkeit."
            elif u_offer <= 500: extra = "Sachlich ablehnen, klarer Hinweis auf unrealistische Erwartung."
            elif u_offer <= 600: extra = "Knapp, fest: deutlich zu niedrig, bleib im Rahmen."
        user = f"""Kontext:
- Artikel: neues, originalverpacktes iPad
- Listenpreis: {ORIGINAL_PRICE} €
- Gegenangebot (sichtbar nennen): {bot_offer} €
- Phase: {phase}
- Argument(e): {arg}
- Zusatz: {extra}
Formuliere **eine** kurze Nachricht, max. 2 Sätze. Du-Form. Keine Emojis. Mindestpreis nie nennen."""
        out = _llm_generate(system, user)
        if out: return out

    # Fallback – Regeltexte (mit frecheren Power-Rebukes)
    if u_offer is None:
        return (f"Der Neupreis liegt bei **{ORIGINAL_PRICE} €**. "
                + (random.choice(POWER_PUSH).format(x=ORIGINAL_PRICE) if COND=="power"
                   else "Woran denkst du preislich?"))

    if COND=="power":
        if phase.startswith("tier1"):
            head = random.choice(POWER_REBUKE_TIER1)
            tail = random.choice(POWER_CLOSERS).format(x=bot_offer)
            return f"{head} {arg} Ich setze **{bot_offer} €** an. {tail}"
        if phase.startswith("tier2"):
            head = random.choice(POWER_REBUKE_TIER2)
            tail = random.choice(POWER_CLOSERS).format(x=bot_offer)
            return f"{head} {arg} **{bot_offer} €** ist mein Rahmen. {tail}"
        if phase.startswith("tier3"):
            head = random.choice(POWER_REBUKE_TIER3)
            tail = random.choice(POWER_CLOSERS).format(x=bot_offer)
            return f"{head} {arg} Ich liege bei **{bot_offer} €**. {tail}"
        if phase == "late_subfloor_rare":
            return f"{arg} Ausnahmsweise gehe ich auf **{bot_offer} €** – darunter nicht."
        if phase == "late_near_floor":
            return f"{arg} Ich kann auf **{bot_offer} €** gehen – darunter schließe ich nicht ab."
        if phase == "mid_low":
            return f"{arg} Das liegt unter meinem Rahmen. **{bot_offer} €** ist realistisch."
        if phase == "early_rounds":
            return f"{arg} Für Neuware setze ich **{bot_offer} €** an. " + random.choice(POWER_CLOSERS).format(x=bot_offer)
        if phase == "at_or_above_list":
            return f"{arg} Bei **{bot_offer} €** schließen wir ab."
        return f"{arg} **{bot_offer} €**."

    # neutral
    tail = random.choice(CLOSERS_NEUTRAL)
    if phase.startswith("tier"):
        return f"Das ist unter Wert. {arg} **{bot_offer} €** halte ich für fair. {tail}"
    if phase == "late_subfloor_rare":
        return f"{arg} Ausnahmsweise kann ich **{bot_offer} €** akzeptieren. {tail}"
    return f"{arg} **{bot_offer} €** wäre mein Vorschlag. {tail}"

# ============== Druck & Timing ==============
def _time_guard_and_finish_if_needed(latest_user_price: Optional[int]):
    if st.session_state.deal_reached or not st.session_state.started: return
    elapsed = (datetime.utcnow() - st.session_state.start_time).total_seconds()
    if elapsed < TIME_LIMIT_SECONDS: return
    best = st.session_state.best_user_offer or (latest_user_price or 0)
    if best >= SUBFLOOR_MIN:   # Deadline: kann knappe Annahme erlauben
        final = _bounded(best, SUBFLOOR_MIN, ORIGINAL_PRICE)
        if COND=="power":
            _bot_say(f"Ich setze auf Abschluss: **{final} €**. Passt das, machen wir es jetzt fix.")
        _finish(final, "time_finalization")
    else:
        _polite_decline()

def _maybe_timed_nudge(elapsed_s:int):
    if COND!="power" or st.session_state.deal_reached or st.session_state.show_survey: return
    em = elapsed_s/60
    if st.session_state.nag_stage==0 and em>=5:  _bot_say(random.choice(POWER_NUDGE_TIMED)); st.session_state.nag_stage=1
    elif st.session_state.nag_stage==1 and em>=10: _bot_say(random.choice(POWER_NUDGE_TIMED)); st.session_state.nag_stage=2
    elif st.session_state.nag_stage==2 and em>=13: _bot_say(random.choice(POWER_NUDGE_TIMED)); st.session_state.nag_stage=3

def _maybe_pause_nudge():
    if COND!="power" or st.session_state.deal_reached or st.session_state.show_survey: return
    last = max(st.session_state.last_bot_time, st.session_state.last_user_time or st.session_state.last_bot_time)
    if (datetime.utcnow()-last).total_seconds() >= 40:
        _bot_say(random.choice(POWER_NUDGE_PAUSE))

# ============== UI (eBay-Look + Startscreen) ==============
PRIMARY = "#1f6feb" if COND=="neutral" else "#d93a3a"
BG_GRAY = "#f5f5f5"; BOT_BG = "#ffffff"
USER_BG = "#d6e4ff" if COND=="neutral" else "#ffd6d6"
USER_BORDER = "#b5ccff" if COND=="neutral" else "#ffb3b3"
AVATAR_URL = NEUTRAL_AVATAR_URL if COND=="neutral" else POWER_AVATAR_URL

st.markdown(f"""
<style>
  .main .block-container {{ padding-top: 1rem; padding-bottom: 6rem; }}
  body {{ background: {BG_GRAY}; }}
  .ek-header {{ position: sticky; top: 0; z-index: 10; background: white; border-bottom: 1px solid #e6e6e6; padding: 0.75rem 0.5rem; display: flex; align-items: center; gap: 12px; }}
  .ek-ava {{ width: 40px; height: 40px; border-radius: 50%; object-fit: cover; }}
  .ek-title {{ display: flex; flex-direction: column; line-height: 1.2; }}
  .ek-name {{ font-weight: 700; }}
  .ek-online {{ font-size: 12px; color: #5f6b6b; }}
  .ek-online .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; background:{PRIMARY}; margin-right:6px; }}
  .ek-item {{ margin-top: 4px; font-size: 13px; color:#3a3a3a; }}
  .ek-price {{ color: {PRIMARY}; font-weight: 700; }}
  .ek-card {{ background: white; border: 1px solid #e9e9e9; border-radius: 10px; padding: 10px 12px; margin: 10px 0 8px 0; display:flex; gap:12px; align-items:center; }}
  .ek-thumb {{ width: 56px; height: 56px; border-radius: 8px; background:#eee; display:flex; align-items:center; justify-content:center; font-size:24px; }}
  .chat-wrap {{ display:flex; flex-direction:column; gap:8px; margin-top:8px; }}
  .bubble {{ max-width: 80%; padding: 10px 12px; border-radius: 14px; box-shadow: 0 1px 0 rgba(0,0,0,0.05); font-size: 15px; line-height: 1.25; word-wrap: break-word; }}
  .bot-row {{ display:flex; justify-content:flex-start; }} .user-row {{ display:flex; justify-content:flex-end; }}
  .bot-bubble {{ background:{BOT_BG}; border:1px solid #e9e9e9; }} .user-bubble {{ background:{USER_BG}; border:1px solid {USER_BORDER}; }}
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

# Start-Screen
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
    opener = (random.choice(POWER_OPENERS).format(x=ORIGINAL_PRICE) + " Das Gerät ist **neu & OVP**. " + random.choice(POWER_PUSH).format(x=ORIGINAL_PRICE)) if COND=="power" \
             else "Hallo! Danke für dein Interesse. Das iPad ist **neu & originalverpackt**. Der Neupreis liegt bei **1.000 €**. Woran denkst du preislich?"
    _bot_say(opener)

# Zeit-Nudges
def _maybe_timed_nudge():
    if COND!="power" or st.session_state.deal_reached or st.session_state.show_survey: return
    em = elapsed/60
    if st.session_state.nag_stage==0 and em>=5:  _bot_say(random.choice(POWER_NUDGE_TIMED)); st.session_state.nag_stage=1
    elif st.session_state.nag_stage==1 and em>=10: _bot_say(random.choice(POWER_NUDGE_TIMED)); st.session_state.nag_stage=2
    elif st.session_state.nag_stage==2 and em>=13: _bot_say(random.choice(POWER_NUDGE_TIMED)); st.session_state.nag_stage=3
_maybe_timed_nudge()

# Chatverlauf rendern
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
c1,c2,c3,c4 = st.columns(4)
with c1:
    if st.button("900 € vorschlagen", use_container_width=True): st.session_state._inject_click="Ich biete 900 €"
with c2:
    if st.button("930 € vorschlagen", use_container_width=True): st.session_state._inject_click="Ich könnte 930 € zahlen"
with c3:
    if st.button("950 € vorschlagen", use_container_width=True): st.session_state._inject_click="Wären 950 € denkbar?"
with c4:
    if st.button("1000 € nehmen", use_container_width=True):   st.session_state._inject_click="Deal bei 1000 €"

# Tipp-Indikator
def _typing_indicator(duration_s: float):
    ph = st.empty()
    with ph.container():
        st.markdown('<div class="typing"><span>Verkäufer tippt</span><div class="dot1"></div><div class="dot2"></div><div class="dot3"></div></div>', unsafe_allow_html=True)
    time.sleep(max(0.0,duration_s)); ph.empty()

def _maybe_pause_nudge():
    if COND!="power" or st.session_state.deal_reached or st.session_state.show_survey: return
    last = max(st.session_state.last_bot_time, st.session_state.last_user_time or st.session_state.last_bot_time)
    if (datetime.utcnow()-last).total_seconds() >= 40:
        _bot_say(random.choice(POWER_NUDGE_PAUSE))

def _respond(user_text:str):
    _maybe_pause_nudge()
    # Preis bestimmen
    u_offer, bot_offer, phase = _compute_counter_numbers(user_text)
    # Tippdauer
    _typing_indicator(random.uniform(0.3,0.9) if COND=="neutral" else random.uniform(0.2,0.6))

    explicit, price_in_text = _detect_deal(user_text)
    if explicit:
        if price_in_text is None:
            if st.session_state.current_offer >= SUBFLOOR_MIN: _finish(st.session_state.current_offer, "user_says_deal_no_price")
            else: _polite_decline()
            return
        else:
            if price_in_text >= SUBFLOOR_MIN and price_in_text <= ORIGINAL_PRICE:
                _finish(price_in_text, "user_says_deal_with_price"); return
            # sonst normal weiter

    flags = _classify_args(user_text)
    if u_offer is None:
        text = _compose_text(flags, None, st.session_state.current_offer, "no_price")
        _bot_say(text); _time_guard_and_finish_if_needed(None); return

    # neues Bot-Angebot übernehmen
    st.session_state.current_offer = bot_offer
    text = _compose_text(flags, u_offer, bot_offer, phase)
    _bot_say(text)
    _time_guard_and_finish_if_needed(u_offer)

# Eingaben
user_input = st.chat_input("Nachricht schreiben …")
b1,b2 = st.columns(2)
with b1: deal_click   = st.button("✅ Ich nehme das Angebot", use_container_width=True)
with b2: cancel_click = st.button("✖️ Nicht mehr interessiert", use_container_width=True)

if deal_click and not st.session_state.deal_reached and not st.session_state.show_survey:
    if st.session_state.current_offer >= SUBFLOOR_MIN: _finish(st.session_state.current_offer,"deal_button")
    else: _polite_decline()

if cancel_click and not st.session_state.deal_reached and not st.session_state.show_survey:
    _polite_decline()

if st.session_state.get("_inject_click") and not st.session_state.deal_reached and not st.session_state.show_survey:
    txt = st.session_state._inject_click; del st.session_state._inject_click
    _user_say(txt); _respond(txt)

if user_input and not st.session_state.deal_reached and not st.session_state.show_survey:
    _user_say(user_input); _respond(user_input)

# Caps & Deadline
if (not st.session_state.deal_reached) and st.session_state.round_idx >= MAX_ROUNDS and not st.session_state.show_survey:
    if st.session_state.current_offer >= SUBFLOOR_MIN:
        _bot_say(f"Ich bleibe bei **{st.session_state.current_offer} €**. Sonst beenden wir es hier.")
    _polite_decline()

if (not st.session_state.deal_reached) and st.session_state.bot_turns >= MAX_BOT_TURNS and not st.session_state.show_survey:
    _polite_decline()

def _time_guard_and_finish_if_needed(latest_user_price: Optional[int]):
    if st.session_state.deal_reached or not st.session_state.started: return
    elapsed2 = (datetime.utcnow() - st.session_state.start_time).total_seconds()
    if elapsed2 < TIME_LIMIT_SECONDS: return
    best = st.session_state.best_user_offer or (latest_user_price or 0)
    if best >= SUBFLOOR_MIN:
        final = _bounded(best, SUBFLOOR_MIN, ORIGINAL_PRICE)
        if COND=="power": _bot_say(f"Ich setze auf Abschluss: **{final} €**. Passt das, machen wir es jetzt fix.")
        _finish(final, "time_finalization")
    else:
        _polite_decline()
_time_guard_and_finish_if_needed(None)

# Survey am Ende
def _render_survey():
    st.markdown("---"); st.subheader("Kurzer Abschluss-Fragebogen")
    st.caption("Deine Antworten helfen uns, die Verhandlung besser zu verstehen (anonym).")
    with st.form("survey", clear_on_submit=False):
        c1,c2 = st.columns(2)
        with c1:
            dominance = st.slider("Der Bot wirkte dominant", 1,7,4)
            pressure  = st.slider("Ich fühlte mich unter Druck gesetzt", 1,7,4)
            fairness  = st.slider("Die Verhandlung war fair", 1,7,4)
            satisfaction = st.slider("Ich bin mit dem Ergebnis zufrieden", 1,7,4)
        with c2:
            trust    = st.slider("Ich vertraute dem Bot", 1,7,4)
            expertise= st.slider("Der Bot wirkte kompetent", 1,7,4)
            recommend= st.slider("Ich würde so verhandeln weiterempfehlen", 1,7,3)
            manipulation_power = st.slider("Der Bot wirkte machtbetont", 1,7,5)
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
            _save_survey_row(payload)
            st.success("Danke! Antworten gespeichert. ✅")

if st.session_state.show_survey: _render_survey()
