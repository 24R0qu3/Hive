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
        "welcome.hint": "Enter · Ctrl+J newline · Shift+drag to select · Ctrl+C ×2 exit",
        # resume picker
        "resume.heading": "Choose a session to resume:",
        "resume.hint": "↑ ↓ navigate · Enter resume · Esc cancel",
        # sessions
        "sessions.title": "Sessions",
        "sessions.col.id": "ID",
        "sessions.col.started": "Started",
        "sessions.col.ended": "Ended",
        "sessions.col.last_message": "Last message",
        "sessions.col.commands": "Commands",
        "sessions.none": "No sessions found.",
        "sessions.none_resume": "No sessions to resume.",
        # /model command
        "model.current": "Model: {model}",
        "model.set": "Model set to {model}",
        "model.usage": "Usage: /model <name>   e.g. /model llama3.2",
        "model.picker_heading": "Choose a model:",
        "model.picker_hint": "↑ ↓ to navigate · Enter to select · Esc/Ctrl+C to cancel",
        "model.picker_none": "No models found. Is Ollama running?",
        # AI
        "ai.busy": "Still thinking\u2026 please wait.",
        "ai.error": "Error: {error}",
        # MCP
        "mcp.title": "MCP Servers",
        "mcp.col.server": "Server",
        "mcp.col.tools": "Tools",
        "mcp.none": "No MCP servers connected.",
        "mcp.error": "MCP: failed to connect to '{name}': {error}",
        "mcp.tools_unsupported": "Model does not support tool calling — MCP tools unavailable",
        "mcp.manage.heading": "MCP Servers",
        "mcp.manage.hint": "↑ ↓ navigate · Enter toggle · R reconnect · D delete · A add · Esc close",
        "mcp.manage.status.connected": "connected ✓",
        "mcp.manage.status.disconnected": "disconnected ✗",
        "mcp.manage.status.reconnecting": "reconnecting…",
        "mcp.manage.confirm_delete": "Delete '{name}'? Press D again to confirm, Esc to cancel.",
        "mcp.manage.add.prompt_name": "New server name:",
        "mcp.manage.add.prompt_command": "Command (e.g. uvx mcp-server-filesystem):",
        "mcp.manage.add.prompt_args": "Args (space-separated, or blank):",
        "mcp.manage.add.prompt_env": "Env vars (KEY=VALUE space-separated, or blank):",
        "mcp.manage.deleted": "Deleted MCP server '{name}'.",
        "mcp.manage.enabled": "Enabled MCP server '{name}'.",
        "mcp.manage.disabled": "Disabled MCP server '{name}'.",
        "mcp.manage.reconnecting": "Reconnecting to '{name}'…",
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
        "welcome.hint": "Enter · Ctrl+J neue Zeile · Shift+Ziehen · Ctrl+C ×2 beenden",
        # resume picker
        "resume.heading": "Sitzung zum Fortsetzen auswählen:",
        "resume.hint": "↑ ↓ navigieren · Enter fortsetzen · Esc/Ctrl+C abbrechen",
        # sessions
        "sessions.title": "Sitzungen",
        "sessions.col.id": "ID",
        "sessions.col.started": "Gestartet",
        "sessions.col.ended": "Beendet",
        "sessions.col.last_message": "Letzte Nachricht",
        "sessions.col.commands": "Befehle",
        "sessions.none": "Keine Sitzungen gefunden.",
        "sessions.none_resume": "Keine Sitzungen zum Fortsetzen.",
        # /model command
        "model.current": "Modell: {model}",
        "model.set": "Modell gesetzt auf {model}",
        "model.usage": "Verwendung: /model <name>   z.B. /model llama3.2",
        "model.picker_heading": "Modell auswählen:",
        "model.picker_hint": "↑ ↓ navigieren · Enter auswählen · Esc/Ctrl+C abbrechen",
        "model.picker_none": "Keine Modelle gefunden. Läuft Ollama?",
        # AI
        "ai.busy": "Noch am Denken\u2026 bitte warten.",
        "ai.error": "Fehler: {error}",
        # MCP
        "mcp.title": "MCP-Server",
        "mcp.col.server": "Server",
        "mcp.col.tools": "Tools",
        "mcp.none": "Keine MCP-Server verbunden.",
        "mcp.error": "MCP: Verbindung zu '{name}' fehlgeschlagen: {error}",
        "mcp.tools_unsupported": "Modell unterstützt keine Werkzeugaufrufe — MCP-Tools nicht verfügbar",
        "mcp.manage.heading": "MCP-Server",
        "mcp.manage.hint": "↑ ↓ navigieren · Enter umschalten · R verbinden · D löschen · A hinzufügen · Esc schließen",
        "mcp.manage.status.connected": "verbunden ✓",
        "mcp.manage.status.disconnected": "getrennt ✗",
        "mcp.manage.status.reconnecting": "verbindet…",
        "mcp.manage.confirm_delete": "'{name}' löschen? D erneut drücken zum Bestätigen, Esc zum Abbrechen.",
        "mcp.manage.add.prompt_name": "Name des neuen Servers:",
        "mcp.manage.add.prompt_command": "Befehl (z.B. uvx mcp-server-filesystem):",
        "mcp.manage.add.prompt_args": "Argumente (leerzeichen-getrennt oder leer):",
        "mcp.manage.add.prompt_env": "Umgebungsvariablen (KEY=VALUE leerzeichen-getrennt oder leer):",
        "mcp.manage.deleted": "MCP-Server '{name}' gelöscht.",
        "mcp.manage.enabled": "MCP-Server '{name}' aktiviert.",
        "mcp.manage.disabled": "MCP-Server '{name}' deaktiviert.",
        "mcp.manage.reconnecting": "Verbinde mit '{name}'…",
        # exit hint
        "exit.resume": "Fortsetzen mit:  hive --resume {id}",
    },
}


def t(key: str, lang: str = "en") -> str:
    """Return the translated string for key in lang, falling back to English."""
    return _STRINGS.get(lang, {}).get(key) or _STRINGS["en"].get(key) or key
