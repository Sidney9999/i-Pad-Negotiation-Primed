# app.py
import streamlit as st

# -*- coding: utf-8 -*-
# ============================================================================
# VERHANDLUNG – iPad neu/OVP (neutral vs. power)
# ----------------------------------------------------------------------------
# Diese Version ist Freddys Code + A/B-Bedingung:
#   • COND = 'neutral' | 'power' (per URL ?cond=power oder Sidebar)
#   • Power-Prime-Textbank + konservativere Concessions
#   • Logging ergänzt um 'condition'
#   • Bugfix: bot_turns wird gezählt
# ============================================================================

from datetime import datetime
from pathlib import Path
import csv
import re
import random
from typing import Optional

# ----------------------------- [1] GRUNDKONFIG -----------------------------
st.set_page_config(page_title="Verhandlung – iPad (A/B)", page_icon="🤝", layout="centered")

ORIGINAL_PRICE = 1000                              # Zielpreis
INTERNAL_MIN_PRICE = int(ORIGINAL_PRICE * 0.90)    # interne Untergrenze (10 % Nachlass) – NIE nennen
TIME_LIMIT_SECONDS = 10 * 60                       # 10 Minuten – nicht offenlegen
MAX_BOT_TURNS = 24                                 # Sicherungsnetz

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

# ---------------------- [2a] BEDINGUNG (A/B) ------------------------------
qp = st.experimental_get_query_params()
COND = qp.get("cond", ["neutral"])[0].lower()
if COND not in {"neutral", "power"}:
    COND = "neutral"
with st.sidebar:
    st.markdown("### Experiment-Setup")
    COND = st.selectbox("Bedingung", ["neutral", "power"], index=0 if COND=="neutral" else 1)

# ------------------------- [3] SESSION-STATE SETUP ------------------------
if "chat" not in st.session_state:
    st.session_state.chat = []              # (role, text)
if "bot_turns" not in st.session_state:
    st.session_state.bot_turns = 0
if "current_offer" not in st.session_state:
    st.session_state.current_offer = ORIGINAL_PRICE
if "deal_reached" not in st.session_state:
    st.session_state.deal_reached = False
if "final_price" not in st.session_state:
    st.session_state.final_price = None
if "start_time" not in st.session_state:
    st.session_state.start_time = datetime.utcnow()
if "numeric_offer_count" not in st.session_state:
    st.session_state.numeric_offer_count = 0
if "best_user_offer" not in st.session_state:
    st.session_state.best_user_offer = None

# --------------------------- [4] NLP-HILFSFUNKTIONEN ----------------------
def _parse_price(text: str):
    """Erste Zahl im Text als Eurobetrag interpretieren (950, 950€, 950,00 etc.)."""
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
    """Einfache Schlagwort-Erkennung für dynamische Argumente."""
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
    "Kann ich gut nachvollziehen.",
    "Klingt nachvollziehbar.",
    "Ich sehe, worauf Sie hinauswollen.",
]
JUSTIFICATIONS = [
    "Es handelt sich um ein **neues, originalverpacktes** Gerät – ohne Nutzungsspuren.",
    "Sie haben es **sofort** verfügbar, keine Lieferzeiten oder Unsicherheiten.",
    "Der **Originalpreis liegt bei 1.000 €**; knapp darunter ist für Neuware fair.",
    "Neu/OVP hält den Wiederverkaufswert deutlich besser.",
    "Im Vergleich zu Gebrauchtware sparen Sie sich jedes Risiko.",
]
ARG_BANK = {
    "student": [
        "Gerade fürs Studium ist Verlässlichkeit wichtig – neu/OVP sorgt dafür.",
        "Ich komme Ihnen gern ein Stück entgegen, damit es für die Uni schnell klappt.",
    ],
    "budget": [
        "Ich weiß, das Budget ist im Studium oft knapp – deshalb bewege ich mich vorsichtig.",
        "Preislich möchte ich fair bleiben, ohne es unter Wert herzugeben.",
    ],
    "cheaper": [
        "Viele günstigere Angebote betreffen Aktionen, ältere Chargen oder Vorführware.",
        "Bei vermeintlich billigeren Angeboten ist es oft nicht wirklich neu/OVP.",
    ],
    "condition": [
        "Hier ist es **OVP** – das ist preislich ein Unterschied zu 'wie neu'.",
        "Neu bedeutet: null Zyklen, keine Überraschungen – das rechtfertigt knapp unter Neupreis.",
    ],
    "immediacy": [
        "Wenn es eilig ist, haben Sie es heute/zeitnah – das ist ein Vorteil.",
        "Schnelle Verfügbarkeit spart Nerven, gerade wenn die Uni losgeht.",
    ],
    "cash": [
        "Barzahlung ist möglich – das macht es unkompliziert.",
    ],
    "pickup": [
        "Abholung ist gern möglich – dann können Sie die Versiegelung direkt prüfen.",
    ],
    "shipping": [
        "Versand ist ordentlich verpackt möglich; Abholung ist natürlich noch bequemer.",
    ],
    "warranty": [
        "Bei Neugeräten greift der Herstellersupport ab Aktivierung.",
    ],
}
CLOSERS = [
    "Wie klingt das für Sie?",
    "Wäre das für Sie in Ordnung?",
    "Können wir uns darauf verständigen?",
    "Passt das für Sie?",
]

# --- Power-Prime-Bausteine ------------------------------------------------
POWER_OPENERS = [
    "Ich setze den Rahmen bei **{x} €**. In diesem Bereich schließe ich üblicherweise ab.",
    "Lassen Sie uns effizient sein: Aktuell steht der Preis bei **{x} €**.",
    "Ich priorisiere feste Käufer. Der aktuelle Rahmen liegt bei **{x} €**."
]
POWER_PUSH = [
    "Geben Sie mir bitte Ihr **bestes** aktuelles Angebot – kurz und konkret.",
    "Begründen Sie mir, warum ich tiefer gehen sollte.",
    "Wenn {x} € nicht passt, schließen wir es lieber sauber ab."
]
POWER_CLOSERS = [
    "Ich bleibe bei **{x} €** – passt das, machen wir den Deal.",
    "Für **{x} €** halte ich den Slot kurz – ansonsten beenden wir es fair.",
    "Wenn **{x} €** passt, schließen wir es jetzt ab."
]

def _pick(lines, k=1):
    """Zufällig 1..k Elemente wählen."""
    if k <= 0:
        return []
    k = min(k, len(lines))
    return random.sample(lines, k)

def _compose_argument_response(flags):
    """Passende Argumente dynamisch kombinieren (max. 2 kurze Sätze)."""
    chosen = []
    for key in ["student", "budget", "cheaper", "condition", "immediacy", "pickup", "cash", "shipping", "warranty"]:
        if flags.get(key, False) and key in ARG_BANK:
            chosen.extend(_pick(ARG_BANK[key], k=1))
        if len(chosen) >= 2:
            break
    if not chosen:
        chosen = _pick(JUSTIFICATIONS, k=1)
    return " ".join(chosen)

# --------------------------- [6] VERHANDLUNGSLOGIK ------------------------
def _save_transcript_row(role: str, text: str, current_offer: int):
    """[Logging] Jede Nachricht in Session-Transkript schreiben."""
    file = _transcript_path()
    is_new = not file.exists()
    with file.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["timestamp_utc", "session_id", "condition", "role", "text", "current_offer_eur"])
        w.writerow([datetime.utcnow().isoformat(), _session_id(), COND, role, text, current_offer])

def _save_outcome_once(final_price: int, ended_by: str, turns_user: int, duration_s: int):
    """[Logging] Einmaliges Outcome in globale Datei schreiben."""
    if st.session_state.get("outcome_logged"):
        return
    file = _outcomes_path()
    is_new = not file.exists()
    with file.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow([
                "timestamp_utc", "session_id", "condition", "item", "original_price_eur",
                "final_price_eur", "ended_by", "user_turns", "duration_seconds"
            ])
        w.writerow([
            datetime.utcnow().isoformat(), _session_id(), COND, "iPad (neu, OVP)",
            ORIGINAL_PRICE, final_price, ended_by, turns_user, duration_s
        ])
    st.session_state.outcome_logged = True

def _bot_say(md: str):
    st.session_state.bot_turns += 1  # Bugfix: Bot-Züge zählen
    st.chat_message("assistant").markdown(md)
    st.session_state.chat.append(("bot", md))
    _save_transcript_row("bot", md, st.session_state.current_offer)

def _user_say(md: str):
    st.chat_message("user").markdown(md)
    st.session_state.chat.append(("user", md))
    _save_transcript_row("user", md, st.session_state.current_offer)

def _detect_deal(text: str):
    """Expliziten Abschluss erkennen; gibt (is_deal, price_if_any) zurück."""
    if not text:
        return False, None
    tl = text.lower()
    keys = ["deal", "einverstanden", "akzeptiere", "passt", "nehme ich", "agree", "accepted"]
    has = any(k in tl for k in keys)
    return has, _parse_price(text)

def _finish(final_price: int, ended_by: str):
    """Deal finalisieren + Outcome loggen."""
    st.session_state.deal_reached = True
    st.session_state.final_price = final_price
    _bot_say(f"Einverstanden – **{final_price} €**. Vielen Dank! 🤝")
    duration = int((datetime.utcnow() - st.session_state.start_time).total_seconds())
    user_turns = sum(1 for r, _ in st.session_state.chat if r == "user")
    _save_outcome_once(final_price, ended_by, user_turns, duration)

def _polite_decline():
    """Höflich ohne Deal beenden (Preis zu niedrig, ohne Untergrenze zu nennen)."""
    msg = random.choice([
        "Schade – so tief kann ich leider nicht gehen. Ich bleibe dann lieber bei meinem Angebot.",
        "Danke für die Verhandlung! Preislich liege ich höher; so komme ich leider nicht mit.",
        "Ich verstehe Ihre Position, aber darunter kann ich es nicht abgeben.",
    ])
    _bot_say(msg)
    duration = int((datetime.utcnow() - st.session_state.start_time).total_seconds())
    user_turns = sum(1 for r, _ in st.session_state.chat if r == "user")
    _save_outcome_once(final_price=0, ended_by="too_low", turns_user=user_turns, duration_s=duration)

def _counter_logic(user_text: str, cond: str):
    """
    Kernlogik für Gegenangebote – konditioniert auf 'neutral' vs. 'power'.
    """
    # Concession-Parameter je Bedingung
    if cond == "power":
        first_three_deltas = {1: [60,55,50,45], 2: [35,30,25,20], 3: [20,15,15,10]}
        later_step_choices = [5, 5, 10]  # kleinere Schritte
        mid_weight = 0.35                # weniger Zug zur Mitte
        closer_bank = POWER_CLOSERS
    else:
        first_three_deltas = {1: [40,50,35,30], 2: [25,30,20,15], 3: [10,15,20]}
        later_step_choices = [5,10,15]
        mid_weight = 0.5
        closer_bank = CLOSERS

    offer_user = _parse_price(user_text)
    flags = _classify_args(user_text)
    empathy = random.choice(EMPATHY)
    args = _compose_argument_response(flags)

    # Wenn kein Preis genannt wurde
    if offer_user is None:
        if cond == "power":
            reply = f"Der Neupreis liegt bei **{ORIGINAL_PRICE} €**. " + random.choice(POWER_PUSH).format(x=ORIGINAL_PRICE)
        else:
            reply = f"{empathy} Der Neupreis liegt bei **{ORIGINAL_PRICE} €**. Woran denken Sie preislich?"
        return reply, st.session_state.current_offer, False

    # Update Zähler & bestes Angebot
    st.session_state.numeric_offer_count += 1
    st.session_state.best_user_offer = max(st.session_state.best_user_offer or 0, offer_user)

    # Falls Nutzer*in ≥ Originalpreis bietet -> fair bestätigen
    if offer_user >= ORIGINAL_PRICE:
        closer = random.choice(closer_bank)
        reply = f"{empathy} {args} Da der **Originalpreis 1.000 €** ist, bleiben wir bei **1.000 €**. {closer}"
        st.session_state.current_offer = ORIGINAL_PRICE
        return reply, ORIGINAL_PRICE, False

    # 1) Erste drei numerische Angebote: immer Gegenangebot über Nutzerpreis
    if st.session_state.numeric_offer_count <= 3:
        deltas = first_three_deltas
        delta = random.choice(deltas[st.session_state.numeric_offer_count])
        upper_cap = min(ORIGINAL_PRICE, st.session_state.current_offer)
        tentative = max(offer_user + delta, offer_user + 5)
        new_offer = min(upper_cap, tentative)
        new_offer = int(round(new_offer / 5) * 5)
        new_offer = min(new_offer, st.session_state.current_offer)
        st.session_state.current_offer = new_offer

        closer = random.choice(closer_bank)
        reply = (
            f"{empathy} {args} Für ein **neues, originalverpacktes** Gerät halte ich "
            f"**{new_offer} €** für angemessen. {closer}"
        )
        return reply, new_offer, False

    # 2) Ab dem 4. Zahlenangebot: moderat annähern, nie unter Wert
    current = st.session_state.current_offer
    if current - offer_user <= 10 and offer_user >= INTERNAL_MIN_PRICE:
        final = current if current <= ORIGINAL_PRICE else ORIGINAL_PRICE
        final = max(final, offer_user)
        final = int(round(final / 5) * 5)
        closer = random.choice(closer_bank)
        reply = f"{empathy} {args} Wenn wir uns auf **{final} €** verständigen, passt es für mich. {closer}"
        st.session_state.current_offer = final
        return reply, final, False

    target = int(round((mid_weight * max(offer_user, INTERNAL_MIN_PRICE) + (1 - mid_weight) * current)))
    step_down = random.choice(later_step_choices)
    new_offer = max(INTERNAL_MIN_PRICE, min(current - step_down, target))
    new_offer = int(round(new_offer / 5) * 5)
    if new_offer > current:
        new_offer = current
    st.session_state.current_offer = new_offer

    tail = random.choice(closer_bank)
    reply = (
        f"{empathy} {args} Ich kann preislich entgegenkommen und **{new_offer} €** anbieten – "
        f"darunter würde ich es ungern abgeben. {tail}"
    )
    return reply, new_offer, False

def _time_guard_and_finish_if_needed(latest_user_price: Optional[int]):
    """Spätestens nach 10 Minuten zum Abschluss führen (oder höflich absagen)."""
    if st.session_state.deal_reached:
        return
    elapsed = (datetime.utcnow() - st.session_state.start_time).total_seconds()
    if elapsed < TIME_LIMIT_SECONDS:
        return
    best_offer = st.session_state.best_user_offer or (latest_user_price or 0)
    if best_offer >= INTERNAL_MIN_PRICE:
        final = max(INTERNAL_MIN_PRICE, min(st.session_state.current_offer, ORIGINAL_PRICE, best_offer))
        final = int(round(final / 5) * 5)
        if COND == "power":
            _bot_say(f"Ich setze auf Abschluss: **{final} €**. Wenn das passt, machen wir es jetzt fix.")
        _finish(final_price=final, ended_by="time_finalization")
    else:
        _polite_decline()

# --------------------------- [7] UI & CHATFLOW ----------------------------
st.title("🤝 Verhandlung: iPad (neu & originalverpackt)")
st.caption(f"**Bedingung:** {'🔹 neutral' if COND=='neutral' else '🔸 power'}")

with st.container():
    st.markdown(
        f"""
**Szenario:**  
Du bist Student*in und brauchst für die Uni dringend ein neues iPad, da dein altes kaputt gegangen ist.  
Du möchtest genau das Modell, das hier auf eBay angeboten wird.  
Der/die Verkäufer*in bietet ein **neues, originalverpacktes iPad** an und möchte es zum **Originalpreis von {ORIGINAL_PRICE} €** loswerden,  
ist aber bereit, in der Verhandlung **knapp darunter** zu gehen – jedoch nicht unter Wert.  
**Auf wie viel Euro einigt ihr euch?**
        """
    )

# Erste Bot-Nachricht
if len(st.session_state.chat) == 0:
    if COND == "power":
        opening = (
            random.choice(POWER_OPENERS).format(x=ORIGINAL_PRICE) + " " +
            "Das Gerät ist **neu & OVP**. " +
            random.choice(POWER_PUSH).format(x=ORIGINAL_PRICE)
        )
    else:
        opening = (
            "Hallo! Danke für Ihr Interesse 😊 Das iPad ist **neu & originalverpackt**. "
            f"Der Neupreis liegt bei **{ORIGINAL_PRICE} €**. "
            "Woran denken Sie preislich?"
        )
    _bot_say(opening)

# Bisherige Nachrichten anzeigen
for role, text in st.session_state.chat:
    st.chat_message("assistant" if role == "bot" else "user").markdown(text)

# Eingabe & Buttons
col_in, col_deal, col_cancel = st.columns([4,1,1])
with col_in:
    user_input = st.chat_input("Ihre Nachricht / Ihr Angebot …")
with col_deal:
    deal_click = st.button("✅ Deal")
with col_cancel:
    cancel_click = st.button("✖️ Abbrechen")

# Deal-Button
if deal_click and not st.session_state.deal_reached:
    _finish(st.session_state.current_offer, ended_by="deal_button")

# Abbrechen
if cancel_click and not st.session_state.deal_reached:
    _polite_decline()

# Nutzer-Eingabe
if user_input and not st.session_state.deal_reached:
    _user_say(user_input)

    is_deal, price_in_text = _detect_deal(user_input)
    if is_deal:
        if price_in_text is not None and INTERNAL_MIN_PRICE <= price_in_text <= ORIGINAL_PRICE:
            _finish(final_price=price_in_text, ended_by="user_says_deal_with_price")
        elif price_in_text is None:
            _finish(final_price=st.session_state.current_offer, ended_by="user_says_deal_no_price")
        else:
            reply, new_offer, _ = _counter_logic(user_input, COND)
            _bot_say(reply)
    else:
        reply, new_offer, _ = _counter_logic(user_input, COND)
        _bot_say(reply)

    _time_guard_and_finish_if_needed(latest_user_price=_parse_price(user_input))

# Absicherung gegen sehr lange Verläufe
if (not st.session_state.deal_reached) and st.session_state.bot_turns >= MAX_BOT_TURNS:
    _polite_decline()
