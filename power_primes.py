# ===========================
# POWER PRIMES – Moderne, realistische Dominanzbibliothek V2.0
# Reine Stil- und Formulierungsvorlagen
# ===========================

import random

# ======================================================
# 1) Hard-Opener – realistisch, modern, scharf
# ======================================================
HARD_OPENERS = [
    "Das ergibt keinen Sinn",
    "Dieses Angebot ist nicht ernst gemeint",
    "Das liegt deutlich daneben",
    "Das passt inhaltlich nicht zusammen",
    "Dieser Preis ist nicht realistisch",
    "So funktioniert keine seriöse Verhandlung",
    "Das ist kein tragfähiger Ansatz",
    "Das ist klar zu niedrig angesetzt",
    "Das entspricht nicht dem tatsächlichen Wert",
    "Das überzeugt in keiner Weise",
    "Das ist keine Basis für ein Gespräch",
    "Diese Einschätzung ist stark verfehlt",
    "Das ist schlicht unrealistisch",
    "So können wir nicht weiterarbeiten",
    "Das ist weit weg vom Marktwert",
    "Das ist nicht nachvollziehbar",
    "Das ist kein sinnvoller Startpunkt",
    "Das lässt sich fachlich nicht halten",
]

# ======================================================
# 2) Autoritätssprache – modern & glaubwürdig
# ======================================================
PRIMES_AUTORITAET = [
    "aus meiner Erfahrung heraus",
    "unter meiner Verantwortung",
    "in meinem Ermessen",
    "nach meiner fachlichen Einschätzung",
    "ich setze hier die Rahmenbedingungen",
    "ich definiere den relevanten Spielraum",
    "ich bewerte Zahlen, nicht Wünsche",
    "ich entscheide über die Angemessenheit",
    "ich bestimme die Verhandlungsbasis",
    "ich arbeite mit klaren Kriterien",
    "ich orientiere mich am tatsächlichen Marktwert",
    "ich urteile auf Grundlage von Fakten",
    "ich treffe hier die Entscheidung",
    "ich gebe die Richtung vor",
    "ich führe diese Verhandlung",
    "ich setze klare Maßstäbe",
    "ich halte die Bewertung transparent",
    "ich bleibe bei objektiven Parametern",
]

# ======================================================
# 3) Finalität – klare, moderne Schlusssätze
# ======================================================
PRIMES_FINALITAET = [
    "nicht verhandelbar",
    "abschließend geklärt",
    "das ist fix",
    "das steht nicht zur Diskussion",
    "das ist endgültig",
    "das bleibt so stehen",
    "hier gibt es keinen Spielraum",
    "das bleibt unverändert",
    "das ist meine Linie",
    "das ist gesetzt",
    "ich bleibe dabei",
    "ich ändere das nicht",
    "das ist verbindlich",
    "das steht fest",
    "das ist final",
    "daran rüttle ich nicht",
    "das ist der letzte Stand",
]

# ======================================================
# 4) Druck & klare Sachlogik – modern & scharf
# ======================================================
PRIMES_DRUCK = [
    "klar formuliert",
    "deutlich gesagt",
    "unmissverständlich",
    "streng betrachtet",
    "realistisch gesehen",
    "faktisch betrachtet",
    "ohne Schönreden",
    "ohne Spielraum",
    "aus nüchterner Sicht",
    "aus reiner Sachlogik",
    "objektiv bewertet",
    "in aller Deutlichkeit",
    "auf den Punkt gebracht",
    "ohne Umschweife",
    "rein sachlich betrachtet",
    "unter nüchterner Betrachtung",
]

# ======================================================
# 5) Rhetorische Dominanzfragen – modern, scharf, realistisch
# ======================================================
RHETORISCHE_FRAGEN = [
    "Wie soll das Ihrer Meinung nach funktionieren?",
    "Glauben Sie wirklich, dass das eine Basis ist?",
    "Sehen Sie selbst nicht, dass das zu niedrig ist?",
    "Was genau soll dieser Preis aussagen?",
    "Welchen Sinn soll dieser Vorschlag ergeben?",
    "Halten Sie das ernsthaft für realistisch?",
    "Wo sehen Sie hier den Marktbezug?",
    "Glauben Sie, so kommen wir weiter?",
    "Ist Ihnen bewusst, wie weit das vom Wert entfernt ist?",
    "Wie stellen Sie sich eine sinnvolle Verhandlung sonst vor?",
    "Worauf wollen Sie damit hinaus?",
    "Welche Logik soll dahinterstehen?",
    "Was erwarten Sie mit so einer Zahl?",
    "Meinen Sie, das sei ein tragfähiger Ansatz?",
    "Glauben Sie, dass ich das akzeptiere?",
]

# ======================================================
# 6) Professionelle Kälte – sachlich, kurz, unfreundlich
# ======================================================
PROFESSIONELLE_KAELTE = [
    "Ich orientiere mich ausschließlich an Fakten.",
    "Ich bewerte das nüchtern.",
    "Ich bleibe sachlich, aber klar.",
    "Ich arbeite mit realistischen Parametern.",
    "Ich halte mich an belastbare Werte.",
    "Ich betrachte das rein technisch.",
    "Ich verlasse mich auf nachvollziehbare Daten.",
    "Ich sehe keinen Anlass für Abweichungen.",
    "Ich bleibe konsequent.",
    "Ich halte das sehr einfach: realistisch oder nicht.",
    "Ich bewerte das ohne persönliche Aspekte.",
]

# ======================================================
# 7) Grenzen setzen – klar & modern
# ======================================================
GRENZZIEHUNG = [
    "An dieser Grenze ändere ich nichts.",
    "Darunter gehe ich nicht.",
    "Diese Linie bleibt bestehen.",
    "Das unterschreite ich nicht.",
    "Das ist mein Minimum.",
    "Das ist die klare Grenze.",
    "Hier endet der Spielraum.",
    "Weiter runter führt das zu nichts.",
    "Diese Untergrenze bleibt fix.",
    "Darüber diskutiere ich nicht weiter.",
]

# ======================================================
# 8) Abwertende Bewertung eines Angebots – modern, aber nicht beleidigend
# ======================================================
ABWERTUNG = [
    "Das ist deutlich zu niedrig angesetzt.",
    "Das bewegt sich klar unter dem Minimum.",
    "Damit kommen wir nicht weiter.",
    "Das ist keine tragfähige Grundlage.",
    "Das ergibt keinen wirtschaftlichen Sinn.",
    "Das passt nicht zu Zustand und Ausstattung.",
    "Das ist kein ernstzunehmender Vorschlag.",
    "Das ist eine verzerrte Einschätzung.",
    "Das liegt erheblich unter dem Wert.",
    "Das erfüllt kein realistisches Niveau.",
]

# ======================================================
# 9) Selbstbewusste Dominanz – modern & kompetent
# ======================================================
SELBSTBEWUSSTE_DOMINANZ = [
    "Ich weiß sehr genau, wo der Wert liegt.",
    "Ich habe das vollständig im Blick.",
    "Ich kenne den Markt besser als die meisten.",
    "Ich entscheide das auf Basis fundierter Erfahrung.",
    "Ich bleibe konsequent bei meiner Linie.",
    "Ich kenne die realen Preise sehr genau.",
    "Ich steuere diesen Prozess zielgerichtet.",
    "Ich mache hier keine Ausnahmen.",
    "Ich bewerte das mit klarem Kopf.",
    "Ich lasse mich nicht auf Fantasiepreise ein.",
]

# ======================================================
# 10) Unterstellende Formulierungen – subtiler psychologischer Druck
# ======================================================
UNTERSTELLUNGEN = [
    "Sie wissen selbst, dass dieser Preis nicht passt.",
    "Sie sehen doch, dass das nicht realistisch ist.",
    "Sie kennen den Marktwert genauso wie ich.",
    "Sie verstehen sicher, warum ich das nicht akzeptiere.",
    "Ihnen ist klar, dass dieser Ansatz zu niedrig ist.",
    "Sie wissen genau, was dieses Gerät wert ist.",
    "Sie wissen selbst, dass das so nicht funktioniert.",
    "Sie erkennen das Problem sicher selbst.",
    "Sie wissen, dass dieser Betrag keinen Sinn ergibt.",
]

# ======================================================
# Kategorisierte Sammlung
# ======================================================
POWER_PRIMES = {
    "autorität": PRIMES_AUTORITAET,
    "finalität": PRIMES_FINALITAET,
    "druck": PRIMES_DRUCK,
    "rhetorik": RHETORISCHE_FRAGEN,
    "kälte": PROFESSIONELLE_KAELTE,
    "grenzen": GRENZZIEHUNG,
    "abwertung": ABWERTUNG,
    "dominanz": SELBSTBEWUSSTE_DOMINANZ,
    "unterstellung": UNTERSTELLUNGEN,
}

def get_example_primes():
    """Gibt alle Formulierungsbeispiele als Inspirationsliste zurück."""
    all_primes = (
        HARD_OPENERS
        + PRIMES_AUTORITAET
        + PRIMES_FINALITAET
        + PRIMES_DRUCK
        + RHETORISCHE_FRAGEN
        + PROFESSIONELLE_KAELTE
        + GRENZZIEHUNG
        + ABWERTUNG
        + SELBSTBEWUSSTE_DOMINANZ
        + UNTERSTELLUNGEN
    )
    return all_primes

def get_examples_by_category(category):
    """Gibt Beispielphrasen zu einer Kategorie zurück."""
    return POWER_PRIMES.get(category, [])
