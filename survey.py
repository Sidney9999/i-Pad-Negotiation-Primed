# ============================================
# survey.py – Abschlussfragebogen (stabil & gut sichtbar)
# ============================================

import streamlit as st

def show_survey():
    st.markdown("## 📋 Abschlussfragebogen zur Verhandlung")
    st.info("Bitte füllen Sie den Fragebogen aus. Ihre Antworten bleiben anonym.")
    st.markdown("---")

    # ---------------------------
    # 1. Alter
    # ---------------------------
    age = st.text_input("1. Wie alt sind Sie?")
    st.markdown("---")

    # ---------------------------
    # 2. Geschlecht – alle vier Optionen direkt sichtbar (kein Dropdown)
    # ---------------------------
    st.write("2. Mit welchem Geschlecht identifizieren Sie sich?")

    gender = st.radio(
        "",
        ["männlich", "weiblich", "divers", "keine Angabe"],
        horizontal=True,           # versucht, sie nebeneinander darzustellen
        label_visibility="collapsed"
    )
    # Auf schmalen Displays bricht Streamlit die Buttons automatisch um.
    st.markdown("---")

    # ---------------------------
    # 3. Bildungsabschluss
    # ---------------------------
    education = st.selectbox(
        "3. Welcher ist Ihr höchster Bildungsabschluss?",
        [
            "Kein Abschluss",
            "Hauptschulabschluss",
            "Realschulabschluss / Mittlere Reife",
            "Fachhochschulreife",
            "Allgemeine Hochschulreife (Abitur)",
            "Berufsausbildung",
            "Bachelor",
            "Master",
            "Diplom",
            "Staatsexamen",
            "Promotion",
            "Habilitation",
            "Sonstiger Abschluss"
        ]
    )
    st.markdown("---")

    # ---------------------------
    # 4. Fachbereich (optional)
    # ---------------------------
    field = None
    field_other = None

    if education in ["Bachelor", "Master", "Diplom", "Staatsexamen", "Promotion", "Habilitation", "Sonstiger Abschluss"]:
        field = st.selectbox(
            "4. In welchem Fachbereich liegt Ihr Studium / Abschluss?",
            [
                "Architektur, Bauingenieurwesen und Geomatik",
                "Informatik und Ingenieurwissenschaften",
                "Wirtschaft und Recht",
                "Soziale Arbeit und Gesundheit",
                "Andere"
            ]
        )
        if field == "Andere":
            field_other = st.text_input("Bitte geben Sie an, welcher Fachbereich:")

    st.markdown("---")

    # -------------------------------------------------------
    # Hilfsfunktion: diskrete Skala mit 1..N (sichtbare Marken)
    # -------------------------------------------------------
    def labeled_select_scale(question, left_label, right_label, key, max_value=10, default=None):
        st.write(question)

        options = list(range(1, max_value + 1))
        if default is None:
            default = (max_value + 1) // 2

        value = st.select_slider(
            label="",
            options=options,
            value=default,
            key=key,
            label_visibility="collapsed"
        )

        col_l, col_r = st.columns(2)
        with col_l:
            st.caption(f"1 = {left_label}")
        with col_r:
            st.caption(f"{max_value} = {right_label}")

        st.markdown("")
        return value

    # ---------------------------
    # 5. Zufriedenheit Ergebnis (1–10)
    # ---------------------------
    satisfaction_outcome = labeled_select_scale(
        "5. Wie zufrieden sind Sie mit dem Ergebnis der Verhandlung?",
        left_label="sehr unzufrieden",
        right_label="sehr zufrieden",
        key="s_outcome",
        max_value=10
    )
    st.markdown("---")

    # ---------------------------
    # 6. Zufriedenheit Verlauf (1–10)
    # ---------------------------
    satisfaction_process = labeled_select_scale(
        "6. Wie zufriedenstellend fanden Sie den Verlauf der Verhandlung?",
        left_label="sehr unzufrieden",
        right_label="sehr zufrieden",
        key="s_process",
        max_value=10
    )
    st.markdown("---")

    # ---------------------------
    # 7. Preisliches Ergebnis (1–10)
    # ---------------------------
    better_result = labeled_select_scale(
        "7. Hätten Sie ein besseres preisliches Ergebnis erzielen können?",
        left_label="keine preisliche Verbesserung",
        right_label="viel bessere preisliche Verbesserung",
        key="s_better",
        max_value=10
    )
    st.markdown("---")

    # ---------------------------
    # 8. Abweichung Dominanz / Nachgiebigkeit (1–5, alle beschriftet)
    # ---------------------------
    st.write("8. Wie stark sind Sie von Ihrem normalen Verhandlungsverhalten abgewichen?")

    deviation = st.select_slider(
        label="",
        options=[1, 2, 3, 4, 5],
        value=3,
        label_visibility="collapsed",
        key="s_deviation"
    )

    labels = {
        1: "stark nachgiebig",
        2: "leicht nachgiebig",
        3: "keine Abweichung",
        4: "leicht dominant",
        5: "stark dominant"
    }

    st.caption("   ".join([f"{i} = {labels[i]}" for i in range(1, 6)]))
    st.markdown("---")

    # ---------------------------
    # 9. Verhandlungsbereitschaft im Alltag (1–10)
    # ---------------------------
    willingness = labeled_select_scale(
        "9. Wie hoch ist Ihre Bereitschaft zu verhandeln im Alltag?",
        left_label="ich verhandle nie",
        right_label="ich verhandle fast immer",
        key="s_willing",
        max_value=10
    )
    st.markdown("---")

    # ---------------------------
    # 10. Wiederverhandlung (Ja / Nein)
    # ---------------------------
    st.write("10. Würden Sie erneut mit dem Bot verhandeln wollen?")
    again = st.radio(
        "",
        ["Ja", "Nein"],
        horizontal=True,
        label_visibility="collapsed"
    )

    st.markdown("---")

    # ---------------------------
    # Absenden
    # ---------------------------
    submit = st.button("Fragebogen absenden")

    if submit:
        return {
            "age": age,
            "gender": gender,
            "education": education,
            "field": field,
            "field_other": field_other,
            "satisfaction_outcome": satisfaction_outcome,
            "satisfaction_process": satisfaction_process,
            "better_result": better_result,
            "deviation": deviation,
            "willingness": willingness,
            "again": again
        }

    return None
