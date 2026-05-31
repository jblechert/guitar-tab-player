"""
ASCII Guitar Tab Parser

Parses standard ASCII guitar tab notation into a sequence of Column objects.
Each Column represents one time-step: a list of (string_index, fret) pairs
that should be played simultaneously.

String indices follow standard guitar notation (high to low):
  0 = e (high E), 1 = B, 2 = G, 3 = D, 4 = A, 5 = E (low E)

Supports:
- 6-string tabs with or without string labels (e B G D A E)
- Multi-digit fret numbers (e.g. 12, 15)
- Multiple systems stacked vertically (auto-concatenated in reading order)
- Chords (multiple strings in same column)
- Technique markers (h p / \\ b ~ x) are parsed but played as plain notes or skipped

Does NOT support:
- Rhythm notation
- String bends with pitch targets (e.g. b9)
- Partial capo / non-standard tunings (handled in tuning.py)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


STRING_LABELS = ("e", "B", "G", "D", "A", "E")
# Regex matching an optional label prefix like "e|" or "B|--" at line start
_LABEL_RE = re.compile(r"^\s*[eEBGDAd]?\s*\|?")


TECHNIQUE_CHARS = frozenset("/\\hpbrs~")

TECHNIQUE_NAMES: dict[str, str] = {
    "/":  "slide_up",
    "\\": "slide_down",
    "s":  "slide",      # 3s5 = slide from 3 to 5 (direction inferred from frets)
    "h":  "hammer_on",
    "p":  "pull_off",
    "b":  "bend",
    "r":  "release",
    "~":  "vibrato",
}


@dataclass
class Note:
    string_index: int        # 0 = high e, 5 = low E
    fret: int                # start fret (or only fret for plain notes)
    technique: str | None = None   # e.g. 'slide_up', 'hammer_on', None
    target_fret: int | None = None # destination fret for slides / bends


@dataclass
class Column:
    index: int          # sequential position in the full tab
    notes: list[Note] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return len(self.notes) == 0


@dataclass
class ParseError:
    message: str
    line: int = -1


@dataclass
class ParseResult:
    columns: list[Column]
    errors: list[ParseError]
    raw_systems: list[list[str]]  # for debug / display


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_label(line: str) -> str:
    """
    Remove leading string label from a tab line.

    Handles single-letter labels (e B G D A E) and two-letter labels used
    for alternate tunings (eb Bb Gb Db Ab Eb) as well as plain leading |.
    """
    # Two-letter label: note letter + optional flat/sharp, then optional space, then |
    m = re.match(r"^\s*[A-Ga-g][b#]?\s*\|", line)
    if m:
        return line[m.end():]
    # Bare leading |
    m2 = re.match(r"^\s*\|", line)
    if m2:
        return line[m2.end():]
    return line


def _is_tab_line(line: str) -> bool:
    """
    Heuristic: a line is a tab line if it contains mostly dashes, digits,
    pipes, and technique characters, and is reasonably long.
    """
    stripped = line.strip()
    if len(stripped) < 3:
        return False
    # Must contain at least one dash (the backbone of tab notation)
    if "-" not in stripped:
        return False
    # Tab characters: digits, dashes, pipes, technique markers, muted (x), ghost notes
    tab_chars = set("0123456789-|hpbr/\\~x() ")
    tab_char_count = sum(1 for c in stripped if c in tab_chars)
    ratio = tab_char_count / len(stripped)
    return ratio > 0.75


def _find_systems(lines: list[str]) -> list[list[str]]:
    """
    Group lines into systems (blocks of exactly 6 consecutive tab lines).
    Returns a list of systems; each system is a list of 6 raw strings
    in order high-e to low-E.
    """
    systems: list[list[str]] = []
    i = 0
    while i < len(lines):
        # Try to collect 6 consecutive tab lines starting at i
        block: list[str] = []
        j = i
        while j < len(lines) and len(block) < 6:
            if _is_tab_line(lines[j]):
                block.append(lines[j])
                j += 1
            elif not lines[j].strip():
                # Empty line inside a potential block: tolerate up to 1
                if block:
                    # skip one blank and try to continue
                    j += 1
                    # if next line is not a tab line, stop this block
                    if j < len(lines) and not _is_tab_line(lines[j]):
                        break
                else:
                    j += 1
            else:
                # Non-tab, non-blank line breaks the block
                if block:
                    break
                j += 1
        if len(block) == 6:
            systems.append(block)
            i = j
        else:
            i += 1
    return systems


def _scan_expression(line: str, pos: int) -> tuple[int, str | None, int | None, int] | None:
    """
    Scan a complete guitar technique expression starting at `pos`.

    Returns (fret_start, technique_name, fret_end, width) or None if no note at pos.

    Examples
    --------
    "9---"    pos=0 → (9,  None,         None, 1)
    "12--"    pos=0 → (12, None,         None, 2)
    "9/12"    pos=0 → (9,  'slide_up',   12,   4)
    "12\\\\9" pos=0 → (12, 'slide_down', 9,    4)
    "9h12"    pos=0 → (9,  'hammer_on',  12,   4)
    "12p9"    pos=0 → (12, 'pull_off',   9,    3)
    "9b11"    pos=0 → (9,  'bend',       11,   4)
    "x---"    pos=0 → (0,  'muted',      None, 1)
    "(0)--"   pos=0 → (0,  'ghost',      None, 3)
    "(12)-"   pos=0 → (12, 'ghost',      None, 4)
    """
    if pos >= len(line):
        return None

    ch = line[pos]

    # --- Muted / dead string: x -------------------------------------------
    if ch == "x":
        return (0, "muted", None, 1)

    # --- Leading approach slide: /12 (from below) or \7 (from above) -------
    # No source fret given — the slide starts from an unspecified position.
    if ch in "/\\":
        direction = "slide_in_up" if ch == "/" else "slide_in_down"
        p = pos + 1
        while p < len(line) and line[p] == "-":
            p += 1
        if p < len(line) and line[p].isdigit():
            end_str = line[p]; p += 1
            if p < len(line) and line[p].isdigit():
                end_str += line[p]; p += 1
            # absorb trailing vibrato marker if present
            if p < len(line) and line[p] == "~":
                p += 1
                return (int(end_str), "slide_in_up_vib" if ch == "/" else "slide_in_down_vib", None, p - pos)
            return (int(end_str), direction, None, p - pos)
        return None

    # --- Ghost / held note: (n) or (nn) ------------------------------------
    if ch == "(":
        p = pos + 1
        fret_str = ""
        while p < len(line) and line[p].isdigit():
            fret_str += line[p]
            p += 1
        if fret_str and p < len(line) and line[p] == ")":
            return (int(fret_str), "ghost", None, p - pos + 1)
        return None  # malformed parenthesis, skip

    if not ch.isdigit():
        return None

    # Read start fret (1 or 2 digits)
    p = pos
    fret_str = line[p]
    p += 1
    if p < len(line) and line[p].isdigit():
        fret_str += line[p]
        p += 1
    fret_start = int(fret_str)

    # Check for technique marker(s) immediately after the fret number.
    # A compound like "10b12r10" is consumed fully as a chained expression:
    # the bend is the primary technique; the trailing "r<fret>" is the release target.
    if p < len(line) and line[p] in TECHNIQUE_CHARS:
        tech_char = line[p]
        technique = TECHNIQUE_NAMES.get(tech_char)
        p += 1

        # Vibrato (~) has no target fret
        if tech_char == "~":
            return (fret_start, technique, None, p - pos)

        # Skip any dashes between technique marker and target fret (e.g. "10/-12")
        while p < len(line) and line[p] == "-":
            p += 1

        # Read target fret if present
        if p < len(line) and line[p].isdigit():
            end_str = line[p]
            p += 1
            if p < len(line) and line[p].isdigit():
                end_str += line[p]
                p += 1
            target_fret = int(end_str)

            # Consume optional chained release/bend after the target fret
            # e.g. "10b12r10": after reading target 12, skip "r10"
            while p < len(line) and line[p] in TECHNIQUE_CHARS:
                p += 1                              # skip technique char
                while p < len(line) and line[p] == "-":
                    p += 1                          # skip dashes
                if p < len(line) and line[p].isdigit():
                    p += 1                          # skip release fret digits
                    if p < len(line) and line[p].isdigit():
                        p += 1

            return (fret_start, technique, target_fret, p - pos)

        # Technique marker but no target fret (e.g. trailing "b")
        return (fret_start, technique, None, p - pos)

    return (fret_start, None, None, p - pos)


def _parse_system(system_lines: list[str], col_offset: int) -> tuple[list[Column], list[ParseError]]:
    """
    Parse one system (6 tab lines) into a sequence of Columns.

    Walks character positions across all strings simultaneously. At each
    position, calls _scan_expression for each string to collect the full
    technique expression (e.g. "9/12" = slide, "9h12" = hammer-on).
    Multiple strings active at the same position form a chord Column.
    """
    errors: list[ParseError] = []

    stripped = [_strip_label(ln) for ln in system_lines]
    max_len = max(len(s) for s in stripped) if stripped else 0
    stripped = [s.ljust(max_len, "-") for s in stripped]

    columns: list[Column] = []
    col_idx = col_offset
    pos = 0

    while pos < max_len:
        notes: list[Note] = []
        advance = 1

        for string_i, line in enumerate(stripped):
            expr = _scan_expression(line, pos)
            if expr is None:
                continue
            fret_start, technique, target_fret, width = expr
            advance = max(advance, width)
            notes.append(Note(
                string_index=string_i,
                fret=fret_start,
                technique=technique,
                target_fret=target_fret,
            ))

        if notes:
            columns.append(Column(index=col_idx, notes=notes))
            col_idx += 1

        pos += advance

    return columns, errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(tab_text: str) -> ParseResult:
    """
    Parse an ASCII guitar tab string into a ParseResult containing
    a flat list of Columns (one per time-step) and any parse errors.
    """
    lines = tab_text.splitlines()
    systems = _find_systems(lines)

    all_columns: list[Column] = []
    all_errors: list[ParseError] = []

    if not systems:
        all_errors.append(ParseError("Kein gueltiges Tab-System gefunden. "
                                     "Erwartet werden 6 aufeinanderfolgende Tab-Zeilen."))
        return ParseResult(columns=[], errors=all_errors, raw_systems=[])

    col_offset = 0
    for system in systems:
        cols, errs = _parse_system(system, col_offset)
        all_columns.extend(cols)
        all_errors.extend(errs)
        col_offset += len(cols)

    return ParseResult(columns=all_columns, errors=all_errors, raw_systems=systems)
