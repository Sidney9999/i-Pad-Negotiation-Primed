# ============================================
# iPad-Verhandlung – Kontrollbedingung (ohne Machtprimes)
# KI-Antworten nach Parametern, Deal/Abbruch, private Ergebnisse
# ============================================

import os, re, json, uuid, random, glob, requests
from datetime import datetime
import streamlit as st
import pandas as pd
import time
import sqlite3
import base64
import pytz

#---

def img_to_base64(path):
    with open(path, "rb") as f:
        data = f.read()
        return base64.b64encode(data).decode()


# --------------------------------
# Session State initialisieren
# --------------------------------
if "session_id" not in st.session_state:
    st.session_state["session_id"] = f"sess-{int(time.time())}"

if "history" not in st.session_state:
    st.session_state["history"] = []  # Chat-Verlauf als Liste von Dicts

if "agreed_price" not in st.session_state:
    st.session_state["agreed_price"] = None  # Preis, der per Deal-Button bestätigt werden kann

if "closed" not in st.session_state:
    st.session_state["closed"] = False  # Ob die Verhandlung abgeschlossen ist

if "action" not in st.session_state:
    st.session_state["action"] = None

# -----------------------------
# [UI: Layout & Styles + Titel mit Bild]
# -----------------------------
st.set_page_config(page_title="iPad-Verhandlung – Kontrollbedingung", page_icon="💬")

# Bild laden (z. B. ipad.png im Projektordner)
ipad_b64 = img_to_base64("ipad.png")

st.markdown(f"""
<style>

#-------Hintergrung Farbe ausgeblendet------
#   .stApp {{
#      max-width: 900px;
#        margin: 0 auto;
#        background: linear-gradient(to bottom, #f8f8f8, #e9e9e9);
#    }}

.header-flex {{
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 0.5rem;
}}
.header-img {{
    width: 48px;
    height: 48px;
    border-radius: 8px;
    object-fit: cover;
    box-shadow: 0 2px 4px rgba(0,0,0,.15);
}}
.header-title {{
    font-size: 2rem;
    font-weight: 600;
    margin: 0;
    padding: 0;
}}
</style>

<div class="header-flex">
    <img src="data:image/png;base64,{ipad_b64}" class="header-img">
    <div class="header-title">iPad-Verhandlung – ohne Machtprimes</div>
</div>
""", unsafe_allow_html=True)

st.caption("Deine Rolle: Käufer")


CHAT_CSS = """
<style>
.chat-container {
    padding-top: 10px;
}

.row {
    display: flex;
    align-items: flex-start;
    margin: 8px 0;
}

.row.left  { justify-content: flex-start; }
.row.right { justify-content: flex-end; }

.chat-bubble {
    padding: 10px 14px;
    border-radius: 16px;
    line-height: 1.45;
    max-width: 75%;
    box-shadow: 0 1px 2px rgba(0,0,0,.08);
    font-size: 15px;
}

.msg-user {
    background: #23A455;       /* User = Kleinanzeigen-Grün */
    color: white;
    border-top-right-radius: 4px;
}

.msg-bot {
    background: #F1F1F1;       /* Bot = hellgrau */
    color: #222;
    border-top-left-radius: 4px;
}

.avatar {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    object-fit: cover;
    margin: 0 8px;
    box-shadow: 0 1px 2px rgba(0,0,0,.15);
}

.meta {
    font-size: .75rem;
    color: #7A7A7A;
    margin-top: 2px;
}

</style>
"""

st.markdown(CHAT_CSS, unsafe_allow_html=True)


# ----------------------------
# Fragebogen (nur nach Abschluss)
# ----------------------------
from survey import show_survey

def run_survey_and_stop():
    survey_data = show_survey()

    if survey_data:
        SURVEY_FILE = "survey_results.xlsx"

        if os.path.exists(SURVEY_FILE):
            df_old = pd.read_excel(SURVEY_FILE)
            df = pd.concat([df_old, pd.DataFrame([survey_data])], ignore_index=True)
        else:
            df = pd.DataFrame([survey_data])

        df.to_excel(SURVEY_FILE, index=False)
        st.success("Vielen Dank! Ihre Antworten wurden gespeichert.")

    st.stop()

# Wenn die Verhandlung bereits geschlossen wurde → sofort Fragebogen
if st.session_state["closed"]:
    run_survey_and_stop()



# -----------------------------
# [SECRETS & MODELL]
# -----------------------------
API_KEY = st.secrets["OPENAI_API_KEY"]
MODEL  = st.secrets.get("OPENAI_MODEL", "gpt-4o-mini")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD")



# -----------------------------
# [EXPERIMENTSPARAMETER – defaults]
# -----------------------------
DEFAULT_PARAMS = {
    "scenario_text": "Sie verhandeln über ein iPad Pro (neu, 13 Zoll, M5 Chip, 256 GB, Space Grey) inklusive Apple Pencil (2. Gen).",
    "list_price": 1000,          # Ausgangspreis
    "min_price": 800,            # Untergrenze
    "tone": "freundlich, respektvoll, auf Augenhöhe, sachlich",
    "max_sentences": 4,          # KI-Antwortlänge in Sätzen
}

# -----------------------------
# [SESSION PARAMS]
# -----------------------------
if "sid" not in st.session_state:
    st.session_state.sid = str(uuid.uuid4())
if "params" not in st.session_state:
    st.session_state.params = DEFAULT_PARAMS.copy()

# -----------------------------
# [REGELN: KEINE MACHTPRIMES + PREISFLOOR]
# -----------------------------
BAD_PATTERNS = [
    r"\balternative(n)?\b", r"\bweitere(n)?\s+interessent(en|in)\b", r"\bknapp(e|heit)\b",
    r"\bdeadline\b", r"\bletzte chance\b", r"\bbranchen(üblich|standard)\b",
    r"\bmarktpreis\b", r"\bneupreis\b", r"\bschmerzgrenze\b", r"\bsonst geht es\b"
]
def contains_power_primes(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in BAD_PATTERNS)

PRICE_RE = re.compile(r"(?:€\s*)?(\d{2,5})")
def extract_prices(text: str):
    return [int(m.group(1)) for m in PRICE_RE.finditer(text)]

# -----------------------------
# [SYSTEM-PROMPT KONSTRUKTION – LLM EINBINDUNG]
# -----------------------------
def system_prompt(params):
    return f"""
Du bist die Verkäuferperson eines neuen iPad (256 GB, Space Grey) inkl. Apple Pencil 2.

Ausgangspreis: 1000 €
Mindestpreis, unter dem du nicht verkaufen möchtest: 800 € (dieser Wert wird NIEMALS erwähnt).

WICHTIGE REGELN FÜR DIE VERHANDLUNG:
1. Du verwendest ausschließlich echte iPad-Daten (256 GB).
2. Du erwähnst NIEMALS deine Untergrenze und sagst nie Sätze wie
   - "800 € ist das Minimum"
   - "Unter 800 € geht nicht"
   - oder konkrete interne Grenzen.
3. Alle Antworten sind frei formulierte KI-Antworten, niemals Textbausteine.
4. Du bleibst freundlich, sachlich und verhandelst realistisch.

PREISLOGIK:
- Nutzer < 600 €
  → höflich ablehnen (zu niedrig für neues Gerät), um realistischere Angebote bitten.
  → KEIN Gegenangebot.

- Nutzer 600–700 €
  → höflich ablehnen (immer noch zu wenig).
  → Gegenangebot HOCH ansetzen (940–990 €).
  → Du verhältst dich verkaufsorientiert.

- Nutzer 700–800 €
  → als Annäherung anerkennen.
  → Gegenangebot realistisch (880–950 €).
  → Du bleibst aber verkaufsorientiert.

- Nutzer ≥ 800 €
  → noch NICHT sofort akzeptieren.
  → leicht höheres Gegenangebot (z. B. +20 bis +60 €).
  → erst nach mehreren Nachrichten kann akzeptiert werden.

Zusatzregeln:
- Keine Macht-, Druck- oder Knappheitsstrategien.
- Maximal {params['max_sentences']} Sätze.
"""


# -----------------------------
# [OPENAI: REST CALL + LLM-REPLY]
# -----------------------------
def call_openai(messages, temperature=0.3, max_tokens=240):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        st.error(f"Netzwerkfehler zur OpenAI-API: {e}")
        return None

    status = r.status_code
    text = r.text

    try:
        data = r.json()
    except Exception:
        data = None

    if status != 200:
        err_msg = None
        err_type = None
        if isinstance(data, dict):
            err = data.get("error") or {}
            err_msg = err.get("message")
            err_type = err.get("type")
        st.error(
            f"OpenAI-API-Fehler {status}"
            f"{' ('+err_type+')' if err_type else ''}"
            f": {err_msg or text[:500]}"
        )
        st.caption("Tipp: Prüfe MODEL / API-Key / Quota / Nachrichtenformat.")
        return None

    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        st.error("Antwortformat unerwartet. Rohdaten:")
        st.code(text[:1000])
        return None


    # ---------------------------------------------------
    # Antwort
    # ---------------------------------------------------

def generate_reply(history, params: dict) -> str:
    WRONG_CAPACITY_PATTERN = r"\b(32|64|128|512|800|1000|1tb|2tb)\s?gb\b"

        # Utility: Rundet auf 5er Schritte
    def round_to_5(value: int) -> int:
        return int(round(value / 5) * 5)

    # Utility: am Ende der Verhandlung (Differenz ≤ 15 €) krumme Zahlen erlauben
    def smart_price(value: int, user_price: int, threshold: int = 15) -> int:
        if abs(value - user_price) <= threshold:
            return value   # krumme Zahl erlaubt
        return round_to_5(value)


    # 1) Grundantwort vom LLM (wird später überschrieben, falls Preislogik greift)
    sys_msg = {"role": "system", "content": system_prompt(params)}

    # LLM-Antwort einholen
    raw_llm_reply = call_openai([sys_msg] + history)
    if not isinstance(raw_llm_reply, str):
        raw_llm_reply = "Es gab einen kleinen technischen Fehler. Bitte frage nochmal. 😊"

    # ---------------------------------------------------
    # REGELPRÜFUNG
    # ---------------------------------------------------
    def violates_rules(text: str) -> str | None:
        if contains_power_primes(text):
            return "Keine Macht-/Knappheits-/Autoritäts-Frames verwenden."
        if re.search(WRONG_CAPACITY_PATTERN, text.lower()):
            return "Falsche Speichergröße. Verwende ausschließlich 256 GB."
        return None

    reason = violates_rules(raw_llm_reply)
    attempts = 0

    while reason and attempts < 2:
        attempts += 1
        retry_prompt = {
            "role": "system",
            "content": (
                f"REGEL-VERSTOSS: {reason}. "
                f"Formuliere die Antwort komplett neu, freundlich und verhandelnd, "
                f"maximal {params['max_sentences']} Sätze."
            )
        }
        raw_llm_reply = call_openai([retry_prompt] + history)
        reason = violates_rules(raw_llm_reply)

    # Speichergröße auto-korrigieren
    raw_llm_reply = re.sub(WRONG_CAPACITY_PATTERN, "256 GB", raw_llm_reply, flags=re.IGNORECASE)



       # ---------------------------------------------------
    # 2) PREISLOGIK – realistische Händlerlogik mit 5er-Rundung, krummen Endpreisen
    # ---------------------------------------------------

    # USERPREIS EXTRAHIEREN
    last_user_msg = ""
    for m in reversed(history):
        if m["role"] == "user":
            last_user_msg = m["content"]
            break

    nums = re.findall(r"\d{2,5}", last_user_msg)
    user_price = int(nums[0]) if nums else None

    if user_price is None:
        return raw_llm_reply

    # BOT-LETZTES GEGENANGEBOT FINDEN
    last_bot_offer = None
    for m in reversed(history):
        if m["role"] == "assistant":
            matches = re.findall(r"\d{2,5}", m["content"])
            if matches:
                last_bot_offer = int(matches[-1])
            break

    # Nachrichtenzahl (steuert Annäherungstempo)
    msg_count = sum(1 for m in history if m["role"] == "assistant")


    # ----------------------------------------
    # WEICHE MINDESTPREISREGEL
    # ----------------------------------------
    if user_price is not None and user_price < params["min_price"]:
        instruct = (
            f"Der Nutzer bietet {user_price} €. "
            f"Du darfst KEINEN Deal unter {params['min_price']} € akzeptieren. "
            f"Reagiere freundlich, erkläre kurz warum dieser Preis zu niedrig ist "
            f"und mache optional ein realistisch höheres Gegenangebot."
        )
        history = [{"role": "system", "content": instruct}] + history


    # ----------------- Utility-Funktionen -----------------

    def round_to_5(v):
        return int(round(v / 5) * 5)

    # kleine Variation für Endgame-Krumme Preise
    def close_range_price(v, user_price):
        diff = abs(v - user_price)
        if diff <= 15:
            return v + random.choice([-3, -2, -1, 0, 1, 2, 3])
        return v

    # realistische Preisspanne
    def human_price(raw, user):
        diff = abs(raw - user)

        if diff > 80:
            return round_to_5(raw)

        if diff > 30:
            return round_to_5(raw + random.choice([-7, -3, 0, 3, 7]))

        return close_range_price(raw, user)

    # NIE HÖHER ALS VORHER
    def ensure_not_higher(new_price):
        if last_bot_offer is None:
            return new_price
        if new_price >= last_bot_offer:
            # reduziere etwas unter das alte Angebot
            return last_bot_offer - random.randint(5, 20)
        return new_price


    # ---------------- PREISZONEN ----------------

    # A) unter 600 – KEIN Gegenangebot
    if user_price < 600:
        instruct = (
            f"Der Nutzer bietet {user_price} €. "
            f"Lehne höflich ab, mache KEIN Gegenangebot, "
            f"nenn KEINEN eigenen Preis, "
            f"bitte nur um ein realistischeres Angebot. "
            f"Verrate niemals interne Grenzen."
        )
        return call_openai([{"role": "system", "content": instruct}] + history)


    # B) 600–700 – HOHES Gegenangebot
    if 600 <= user_price < 700:
        raw_price = random.randint(920, 990)
        counter = human_price(raw_price, user_price)
        counter = ensure_not_higher(counter)

        instruct = (
            f"Der Nutzer bietet {user_price} €. "
            f"Gib EIN Gegenangebot: {counter} €. "
            f"Nenne KEINEN anderen Preis. "
            f"Formuliere frei, freundlich und verhandelnd."
        )
        return call_openai([{"role": "system", "content": instruct}] + history)


    # C) 700–800 – realistisches Herantasten
    if 700 <= user_price < 800:

        # Frühphase: hohe Preise, Endphase: realistisch
        if msg_count < 3:
            raw_price = random.randint(910, 960)
        else:
            raw_price = random.randint(850, 930)

        counter = human_price(raw_price, user_price)
        counter = ensure_not_higher(counter)

        instruct = (
            f"Der Nutzer bietet {user_price} €. "
            f"Mach ein realistisches Gegenangebot: {counter} €. "
            f"Formuliere die Antwort frei, freundlich und menschlich."
        )
        return call_openai([{"role": "system", "content": instruct}] + history)


    # D) 800+ – leicht höheres Gegenangebot, noch kein sofortiger Deal
    if user_price >= 800:
        # je nach Gesprächsphase konservativ starten
        if msg_count < 3:
            raw_price = user_price + random.randint(30, 80)
        else:
            raw_price = user_price + random.randint(15, 40)

        counter = human_price(raw_price, user_price)
        counter = ensure_not_higher(counter)

        instruct = (
            f"Der Nutzer bietet {user_price} €. "
            f"Mach ein leicht höheres Gegenangebot: {counter} €. "
            f"Formuliere freundlich, verhandelnd, maximal {params['max_sentences']} Sätze."
        )
        return call_openai([{"role": "system", "content": instruct}] + history)




# -----------------------------
# [ERGEBNIS-LOGGING (SQLite)]
# -----------------------------
DB_PATH = "verhandlungsergebnisse.sqlite3"

def _init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            session_id TEXT,
            deal INTEGER,
            price INTEGER,
            msg_count INTEGER
        )
    """)
    conn.commit()
    conn.close()

def log_result(session_id: str, deal: bool, price: int | None, msg_count: int):
    _init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO results (ts, session_id, deal, price, msg_count) VALUES (?, ?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), session_id, 1 if deal else 0, price, msg_count),
    )
    conn.commit()
    conn.close()

def load_results_df() -> pd.DataFrame:
    _init_db()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT ts, session_id, deal, price, msg_count FROM results ORDER BY id ASC",
        conn,
    )
    conn.close()
    if df.empty:
        return df
    df["deal"] = df["deal"].map({1: "Deal", 0: "Abgebrochen"})
    return df

def extract_price_from_bot(msg: str) -> int | None:
    text = msg.lower()

    # 0) Wenn eine Zahl direkt vor "gb" steht → nie ein Preis
    gb_numbers = re.findall(r"(\d{2,5})\s*gb", text)
    gb_numbers = {int(x) for x in gb_numbers}

    # 1) Explizite Euro-Angaben ("920 €" oder "920€")
    euro_matches = re.findall(r"(\d{2,5})\s*€", text)
    for m in euro_matches[::-1]:
        val = int(m)
        if val not in gb_numbers and 600 <= val <= 2000:
            return val

    # 2) Preisangaben mit Worten (für 900 / Preis wäre 880 / Gegenangebot 910)
    word_matches = re.findall(
        r"(?:preis|für|gegenangebot|angebot)\s*:?[^0-9]*(\d{2,5})",
        text
    )
    for m in word_matches[::-1]:
        val = int(m)
        if val not in gb_numbers and 600 <= val <= 2000:
            return val

    # 3) Alle sonstigen Zahlen prüfen (Backup), aber GB ausschließen!
    all_nums = [int(x) for x in re.findall(r"\d{2,5}", text)]

    for n in all_nums:
        if n in gb_numbers:
            continue
        if n in (32, 64, 128, 256, 512, 1024, 2048):
            continue
        if 600 <= n <= 2000:
            return n

    return None





# -----------------------------
# [Szenario-Kopf]
# -----------------------------
with st.container():
    st.subheader("Szenario")
    st.write(st.session_state.params["scenario_text"])
    st.write(f"**Ausgangspreis:** {st.session_state.params['list_price']} €")

st.caption(f"Session-ID: `{st.session_state.sid}`")



# -----------------------------
# [CHAT-UI – vollständig LLM-basiert]
# -----------------------------
st.subheader("💬 iPad Verhandlungs-Bot")

# Zeitzone definieren
tz = pytz.timezone("Europe/Berlin")

# 1) Initiale Bot-Nachricht einmalig
if len(st.session_state["history"]) == 0:
    first_msg = (
        "Hi! Ich biete ein neues iPad (256 GB, Space Grey) inklusive Apple Pencil (2. Gen) "
        f"mit M5-Chip an. Der Ausgangspreis liegt bei {DEFAULT_PARAMS['list_price']} €. "
        "Was schwebt dir preislich vor?"
    )
    st.session_state["history"].append({
        "role": "assistant",
        "text": first_msg,
        "ts": datetime.now(tz).strftime("%d.%m.%Y %H:%M"),
    })

# 2) Eingabefeld
user_input = st.chat_input(
    "Deine Nachricht",
    disabled=st.session_state["closed"],
)

# 3) Wenn User etwas sendet → LLM-Antwort holen
if user_input and not st.session_state["closed"]:

    # Zeitstempel erzeugen
    now = datetime.now(tz).strftime("%d.%m.%Y %H:%M")

    # Nutzer-Nachricht speichern
    st.session_state["history"].append({
        "role": "user",
        "text": user_input.strip(),
        "ts": now,
    })

    # LLM-Verlauf vorbereiten (role/content)
    llm_history = [
        {"role": m["role"], "content": m["text"]}
        for m in st.session_state["history"]
    ]

    # KI-Antwort generieren
    bot_text = generate_reply(llm_history, st.session_state.params)

    # Bot-Nachricht speichern
    st.session_state["history"].append({
        "role": "assistant",
        "text": bot_text,
        "ts": datetime.now(tz).strftime("%d.%m.%Y %H:%M"),
    })

    # Bot-Gegenangebot extrahieren
    bot_offer = extract_price_from_bot(bot_text)
    st.session_state["bot_offer"] = bot_offer



# 4) Chat-Verlauf anzeigen (inkl. frischer Bot-Antwort) 
# Profilbilder laden
BOT_AVATAR  = img_to_base64("bot.png")
USER_AVATAR = img_to_base64("user.png")

for item in st.session_state["history"]:
    role = item["role"]
    text = item["text"]
    ts = item["ts"]

    is_user = (role == "user")

    avatar_b64 = USER_AVATAR if is_user else BOT_AVATAR

    side = "right" if is_user else "left"
    klass = "msg-user" if is_user else "msg-bot"

    st.markdown(f"""
    <div class="row {side}">
        <img src="data:image/png;base64,{avatar_b64}" class="avatar">
        <div class="chat-bubble {klass}">
            {text}
        </div>
    </div>
    <div class="row {side}">
        <div class="meta">{ts}</div>
    </div>
    """, unsafe_allow_html=True)


# 5) Deal bestätigen / Verhandlung beenden
if not st.session_state["closed"]:

    deal_col1, deal_col2 = st.columns([1, 1])

    bot_offer = st.session_state.get("bot_offer", None)
    show_deal = (bot_offer is not None)

    # DEAL-BUTTON
    with deal_col1:
        if st.button(
            f"💚 Deal bestätigen: {bot_offer} €" if show_deal else "Deal bestätigen",
            disabled=not show_deal,
            use_container_width=True
        ):
            bot_price = st.session_state.get("bot_offer")
            msg_count = len([
                m for m in st.session_state["history"]
                if m["role"] in ("user", "assistant")
            ])
            log_result(st.session_state["session_id"], True, bot_price, msg_count)

            st.session_state["closed"] = True
            run_survey_and_stop()

    # ABBRUCH-BUTTON
    with deal_col2:
        if st.button("❌ Verhandlung beenden", use_container_width=True):

            msg_count = len([
                m for m in st.session_state["history"]
                if m["role"] in ("user", "assistant")
            ])

            log_result(st.session_state["session_id"], False, None, msg_count)

            st.session_state["closed"] = True
            run_survey_and_stop()

# -----------------------------
# [ADMIN-BEREICH: Ergebnisse (privat)]
# -----------------------------
if not st.session_state["closed"]:
    st.sidebar.header("📊 Ergebnisse")
    pwd_ok = False
    dashboard_password = st.secrets.get("DASHBOARD_PASSWORD", os.environ.get("DASHBOARD_PASSWORD"))
    pwd_input = st.sidebar.text_input("Passwort für Dashboard", type="password")
    if dashboard_password:
        if pwd_input and pwd_input == dashboard_password:
            pwd_ok = True
        elif pwd_input and pwd_input != dashboard_password:
            st.sidebar.warning("Falsches Passwort.")
    else:
        st.sidebar.info("Kein Passwort gesetzt (DASHBOARD_PASSWORD). Dashboard ist deaktiviert.")

    if pwd_ok:
        st.sidebar.success("Zugang gewährt.")

        with st.sidebar.expander("Alle Verhandlungsergebnisse", expanded=True):
            if os.path.exists("survey_results.xlsx"):
                df_s = pd.read_excel("survey_results.xlsx")
                st.dataframe(df_s, use_container_width=True)

                from io import BytesIO
                buf = BytesIO()
                df_s.to_excel(buf, index=False)
                buf.seek(0)

                st.download_button(
                    "Umfrage als Excel herunterladen",
                    buf,
                    file_name="survey_results_download.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.info("Noch keine Umfrage-Daten vorhanden.")


            df = load_results_df()

            if len(df) == 0:
                st.write("Noch keine Ergebnisse gespeichert.")

            else:
                # neue Nummerierung hinzufügen (1, 2, 3, ...)
                df = df.reset_index(drop=True)
                df["nr"] = df.index + 1

                # schönere Reihenfolge
                df = df[["nr", "ts", "session_id", "deal", "price", "msg_count"]]

                st.dataframe(df, use_container_width=True, hide_index=True)

                from io import BytesIO
                buffer = BytesIO()
                df.to_excel(buffer, index=False)
                buffer.seek(0)

                st.download_button(
                    "Excel herunterladen",
                    buffer,
                    file_name="verhandlungsergebnisse.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    # ----------------------------
    # Admin Reset mit Bestätigung
    # ----------------------------
        st.sidebar.markdown("---")
        st.sidebar.subheader("Admin-Tools")

        # Zustand für Sicherheitsabfrage speichern
        if "confirm_delete" not in st.session_state:
            st.session_state["confirm_delete"] = False

        # Erste Stufe: Benutzer klickt → Sicherheitswarnung erscheint
        if not st.session_state["confirm_delete"]:
            if st.sidebar.button("🗑️ Alle Ergebnisse löschen"):
                st.session_state["confirm_delete"] = True
                st.sidebar.warning("⚠️ Bist du sicher, dass du **ALLE Ergebnisse** löschen möchtest?")
                st.sidebar.info("Dieser Vorgang kann nicht rückgängig gemacht werden.")
        else:
            # Zweite Stufe: Zwei Buttons erscheinen
            col1, col2 = st.sidebar.columns(2)

            with col1:
                if st.button("❌ Abbrechen"):
                    st.session_state["confirm_delete"] = False

            with col2:
                if st.button("✅ Ja, löschen"):
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute("DELETE FROM results")
                    conn.commit()
                    conn.close()

                    st.session_state["confirm_delete"] = False
                    st.sidebar.success("Alle Ergebnisse wurden gelöscht.")

        

