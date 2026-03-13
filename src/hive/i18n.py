"""Translation strings and lookup for Hive's supported languages."""

from __future__ import annotations

LANG_OPTIONS: list[tuple[str, str]] = [("en", "English"), ("de", "Deutsch")]

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # name prompt (always shown in EN — before language is chosen)
        "name.heading": "Welcome to Hive!",
        "name.prompt": "Type your name below and press Enter.",
        "name.rename_heading": "What's your new name?",
        "name.rename_prompt": "Type your new name below and press Enter.",
        # trust panel
        "trust.heading": "Hive wants to create a local workspace in:",
        "trust.body1": "This will create a .hive folder for session",
        "trust.body2": "history, logs, and output.",
        "trust.hint": "← → to choose · Enter to confirm",
        # language picker
        "lang.heading": "Choose a language:",
        "lang.hint": "↑ ↓ to navigate · Enter to confirm",
        "lang.change_later": "You can change this later with /language",
        # welcome
        "welcome.greeting": "Hello, {name}!",
        "welcome.hint": "Enter · Shift+Enter newline · Shift+drag to select · Ctrl+C ×2 exit",
        # resume picker
        "resume.heading": "Choose a session to resume:",
        "resume.hint": "↑ ↓ navigate · Enter resume · L cycle limit · Esc cancel",
        "resume.limit": "Context limit: {limit}",
        "resume.limit_unlimited": "Unlimited",
        "resume.limit_custom_hint": "Type token limit and press Enter · Esc cancel",
        # context restore notices (appended to output after resume)
        "context.loading": "Restoring context\u2026",
        "context.restored": "Context restored \u2014 {n} messages",
        "context.summarized": "Context summarized from previous session",
        "context.partial": "Context partially restored \u2014 last {n} messages",
        # sessions
        "sessions.title": "Sessions",
        "sessions.col.id": "ID",
        "sessions.col.started": "Started",
        "sessions.col.commands": "Commands",
        "sessions.none": "No sessions found.",
        "sessions.none_resume": "No sessions to resume.",
        # /model command
        "model.current": "Model: {model}",
        "model.set": "Model set to {model}",
        "model.usage": "Usage: /model <name>   e.g. /model llama3.2",
        # AI
        "ai.busy": "Still thinking\u2026 please wait.",
        "ai.error": "Error: {error}",
        # exit hint
        "exit.resume": "To resume:  hive --resume {id}",
    },
    "de": {
        # trust panel
        "trust.heading": "Hive möchte einen lokalen Arbeitsbereich erstellen in:",
        "trust.body1": "Ein .hive-Ordner wird erstellt für Verlauf,",
        "trust.body2": "Protokolle und Ausgaben der Sitzung.",
        "trust.hint": "← → auswählen · Enter bestätigen",
        # language picker
        "lang.heading": "Sprache auswählen:",
        "lang.hint": "↑ ↓ navigieren · Enter bestätigen",
        "lang.change_later": "Später änderbar mit /language",
        # welcome
        "welcome.greeting": "Hallo, {name}!",
        "welcome.hint": "Enter · Shift+Enter neue Zeile · Shift+Ziehen · Ctrl+C ×2 beenden",
        # resume picker
        "resume.heading": "Sitzung zum Fortsetzen auswählen:",
        "resume.hint": "↑ ↓ navigieren · Enter fortsetzen · L Limit · Esc abbrechen",
        "resume.limit": "Kontextlimit: {limit}",
        "resume.limit_unlimited": "Unbegrenzt",
        "resume.limit_custom_hint": "Tokenlimit eingeben und Enter drücken · Esc abbrechen",
        # context restore notices
        "context.loading": "Kontext wird wiederhergestellt\u2026",
        "context.restored": "Kontext wiederhergestellt \u2014 {n} Nachrichten",
        "context.summarized": "Kontext aus vorheriger Sitzung zusammengefasst",
        "context.partial": "Kontext teilweise wiederhergestellt \u2014 letzte {n} Nachrichten",
        # sessions
        "sessions.title": "Sitzungen",
        "sessions.col.id": "ID",
        "sessions.col.started": "Gestartet",
        "sessions.col.commands": "Befehle",
        "sessions.none": "Keine Sitzungen gefunden.",
        "sessions.none_resume": "Keine Sitzungen zum Fortsetzen.",
        # /model command
        "model.current": "Modell: {model}",
        "model.set": "Modell gesetzt auf {model}",
        "model.usage": "Verwendung: /model <name>   z.B. /model llama3.2",
        # AI
        "ai.busy": "Noch am Denken\u2026 bitte warten.",
        "ai.error": "Fehler: {error}",
        # exit hint
        "exit.resume": "Fortsetzen mit:  hive --resume {id}",
    },
}


def t(key: str, lang: str = "en") -> str:
    """Return the translated string for key in lang, falling back to English."""
    return _STRINGS.get(lang, {}).get(key) or _STRINGS["en"].get(key) or key
