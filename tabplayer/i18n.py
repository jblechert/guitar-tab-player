"""
Internationalisation (i18n) support for Guitar Tab Player.

Usage in any module:

    from tabplayer.i18n import _
    label = _("Play")

Translators work with standard .po / .pot files in tabplayer/locale/.
Compile a .po file to a binary .mo file with:

    msgfmt -o tabplayer/locale/de/LC_MESSAGES/tabplayer.mo \\
              tabplayer/locale/de/LC_MESSAGES/tabplayer.po

Generate / update the .pot template from source:

    xgettext -d tabplayer -o tabplayer/locale/tabplayer.pot \\
             --from-code=UTF-8 --language=Python \\
             tabplayer/app.py tabplayer/generator.py tabplayer/player.py

To add a new language (e.g. Swedish):

    mkdir -p tabplayer/locale/sv/LC_MESSAGES
    msginit -i tabplayer/locale/tabplayer.pot \\
            -o tabplayer/locale/sv/LC_MESSAGES/tabplayer.po \\
            --locale=sv
    # translate strings in the .po file, then compile:
    msgfmt -o tabplayer/locale/sv/LC_MESSAGES/tabplayer.mo \\
              tabplayer/locale/sv/LC_MESSAGES/tabplayer.po
"""

from __future__ import annotations

import gettext
from pathlib import Path

LOCALE_DIR = Path(__file__).parent / "locale"

# Active translation — NullTranslations is the identity (returns msgid unchanged).
# When language = "en", strings in code ARE the translation, so NullTranslations is correct.
_translation: gettext.NullTranslations = gettext.NullTranslations()


def set_language(lang: str) -> None:
    """
    Switch the active language at runtime.

    lang: ISO 639-1 code, e.g. "en", "de", "sv".
    Falls back to NullTranslations (= English) if no .mo file is found.
    """
    global _translation
    try:
        _translation = gettext.translation(
            domain="tabplayer",
            localedir=str(LOCALE_DIR),
            languages=[lang],
        )
    except FileNotFoundError:
        _translation = gettext.NullTranslations()


def _(msgid: str) -> str:
    """Translate msgid using the currently active language."""
    return _translation.gettext(msgid)


def get_available_languages() -> list[tuple[str, str]]:
    """
    Return a list of (language_code, display_name) pairs for all languages
    that have a compiled .mo file present.
    English is always included (it is the source language).
    """
    DISPLAY_NAMES: dict[str, str] = {
        "en": "English",
        "de": "Deutsch",
        "sv": "Svenska",
        "fr": "Français",
        "es": "Español",
        "nl": "Nederlands",
        "pl": "Polski",
        "pt": "Português",
        "ja": "日本語",
        "zh": "中文",
    }
    result = [("en", "English")]
    if LOCALE_DIR.is_dir():
        for path in sorted(LOCALE_DIR.iterdir()):
            if (path / "LC_MESSAGES" / "tabplayer.mo").exists():
                code = path.name
                result.append((code, DISPLAY_NAMES.get(code, code)))
    return result
