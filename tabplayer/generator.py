"""
Ollama Tab Generator

Sends a structured prompt to a local Ollama instance and streams the response.
Uses the standard Ollama /api/chat endpoint (http://localhost:11434).

Runs in a QThread; emits:
  - token(str)          one streamed token at a time
  - finished(str)       full generated text when done
  - error(str)          on connection / API errors
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from urllib.parse import urljoin

from PySide6.QtCore import QThread, Signal


OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL   = "qwen3:latest"

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a guitar tab expert. When asked for a guitar tab, you output ONLY valid \
ASCII guitar tab notation — no explanations, no markdown fences, no extra text. \
Use standard 6-string format with labels e|B|G|D|A|E| on the left. \
Use dashes for empty positions. Multi-digit fret numbers (10, 11, 12 …) are fine. \
Split long sections into multiple systems of 6 lines each, separated by a blank line.\
"""


def build_prompt(song: str, artist: str, section: str, tuning: str) -> str:
    parts = [f'Generate a guitar tab for "{song}"']
    if artist.strip():
        parts[0] += f" by {artist}"
    parts[0] += "."

    if section.strip():
        parts.append(f"Section: {section}.")

    parts.append(
        f"Tuning: {tuning}. "
        "Output only the tab in standard ASCII format. "
        "6 lines per system, labeled e|B|G|D|A|E. "
        "No explanations or markdown."
    )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Streaming Ollama client
# ---------------------------------------------------------------------------

class OllamaGeneratorThread(QThread):
    """
    Calls POST /api/chat on the local Ollama instance with streaming.

    Signals:
        token(str):     each streamed token as it arrives
        finished(str):  complete generated text
        error(str):     error message
    """

    token    = Signal(str)
    finished = Signal(str)
    error    = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model   = DEFAULT_MODEL
        self._prompt  = ""
        self._base_url = OLLAMA_BASE_URL
        self._stop_requested = False

    def set_model(self, model: str) -> None:
        self._model = model.strip() or DEFAULT_MODEL

    def set_base_url(self, url: str) -> None:
        self._base_url = url.rstrip("/")

    def set_prompt(self, prompt: str) -> None:
        self._prompt = prompt

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        self._stop_requested = False
        url = f"{self._base_url}/api/chat"

        payload = {
            "model":  self._model,
            "stream": True,
            "messages": [
                {"role": "system",  "content": SYSTEM_PROMPT},
                {"role": "user",    "content": self._prompt},
            ],
            # Ask the model to suppress chain-of-thought for cleaner output
            "options": {
                "temperature": 0.3,
            },
        }

        body = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        full_text = ""
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw_line in resp:
                    if self._stop_requested:
                        break
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # /api/chat streaming format
                    content = (
                        chunk.get("message", {}).get("content", "")
                        or chunk.get("response", "")  # /api/generate compat
                    )
                    if content:
                        # Qwen3 thinking mode wraps reasoning in <think>…</think>
                        # Strip those tags so only the tab reaches the display
                        if not hasattr(self, "_in_think"):
                            self._in_think = False
                        if "<think>" in content:
                            self._in_think = True
                        if self._in_think:
                            if "</think>" in content:
                                self._in_think = False
                                # emit only the part after </think>
                                after = content.split("</think>", 1)[1]
                                if after:
                                    self.token.emit(after)
                                    full_text += after
                            # skip thinking tokens entirely
                            continue
                        self.token.emit(content)
                        full_text += content

                    if chunk.get("done"):
                        break

        except urllib.error.URLError as exc:
            reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
            if "Connection refused" in reason or "Connect call failed" in reason:
                self.error.emit(
                    "Ollama ist nicht erreichbar (localhost:11434).\n"
                    "Starte Ollama mit: ollama serve"
                )
            else:
                self.error.emit(f"Netzwerk-Fehler: {reason}")
            return
        except Exception as exc:
            self.error.emit(f"Fehler: {exc}")
            return

        self.finished.emit(full_text)


# ---------------------------------------------------------------------------
# Model list fetcher (non-streaming, best-effort)
# ---------------------------------------------------------------------------

def fetch_models(base_url: str = OLLAMA_BASE_URL) -> list[str]:
    """Return list of available model names from the local Ollama instance."""
    try:
        url = f"{base_url}/api/tags"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Auto-Tempo fetcher
# ---------------------------------------------------------------------------

class TempoFetcherThread(QThread):
    """
    Asks Ollama for the BPM of a given song.

    Signals:
        tempo_found(int):  BPM value extracted from the model response
        error(str):        error or unparseable response message
    """

    tempo_found = Signal(int)
    error       = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._song     = ""
        self._artist   = ""
        self._model    = DEFAULT_MODEL
        self._base_url = OLLAMA_BASE_URL

    def set_query(self, song: str, artist: str = "") -> None:
        self._song   = song.strip()
        self._artist = artist.strip()

    def set_model(self, model: str) -> None:
        self._model = model.strip() or DEFAULT_MODEL

    def set_base_url(self, url: str) -> None:
        self._base_url = url.rstrip("/")

    def run(self) -> None:
        query = f'"{self._song}"'
        if self._artist:
            query += f' by {self._artist}'

        payload = {
            "model":  self._model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a music expert. "
                        "When asked for the BPM of a song, reply with ONLY a single integer. "
                        "No range, no text, no explanation — just the number."
                    ),
                },
                {
                    "role": "user",
                    "content": f"What is the BPM of {query}?",
                },
            ],
            "options": {"temperature": 0.1},
        }

        body = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data    = json.loads(resp.read())
                content = data.get("message", {}).get("content", "").strip()

                # Strip <think>…</think> blocks (qwen3 thinking mode)
                import re
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

                # Extract first integer from the response
                m = re.search(r"\b(\d{2,3})\b", content)
                if m:
                    bpm = int(m.group(1))
                    bpm = max(20, min(300, bpm))
                    self.tempo_found.emit(bpm)
                else:
                    self.error.emit(f"Kein BPM-Wert gefunden in: {content!r}")

        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            if "Connection refused" in reason or "Connect call failed" in reason:
                self.error.emit("Ollama nicht erreichbar (localhost:11434). Starte: ollama serve")
            else:
                self.error.emit(f"Netzwerk-Fehler: {reason}")
        except Exception as exc:
            self.error.emit(f"Fehler: {exc}")
