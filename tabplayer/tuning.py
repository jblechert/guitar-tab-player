"""
Guitar Tuning and Pitch Mapping

Converts (string_index, fret) pairs to MIDI note numbers.

String indices: 0 = high e, 1 = B, 2 = G, 3 = D, 4 = A, 5 = low E
MIDI note 60 = middle C (C4).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tuning:
    name: str
    # Open-string MIDI notes, index 0 = high e, index 5 = low E
    open_strings: tuple[int, ...]

    def midi_note(self, string_index: int, fret: int) -> int:
        """Return MIDI note number for a given string and fret."""
        if not (0 <= string_index < len(self.open_strings)):
            raise ValueError(f"Invalid string index: {string_index}")
        return self.open_strings[string_index] + fret


# Standard tuning: E2 A2 D3 G3 B3 e4  (low to high)
# MIDI: E2=40, A2=45, D3=50, G3=55, B3=59, e4=64
STANDARD = Tuning(
    name="Standard (EADGBe)",
    open_strings=(64, 59, 55, 50, 45, 40),  # index 0=high e, 5=low E
)

# Drop D: low E string tuned down to D2 (MIDI 38)
DROP_D = Tuning(
    name="Drop D (DADGBe)",
    open_strings=(64, 59, 55, 50, 45, 38),
)

# Open G: D G D G B D
OPEN_G = Tuning(
    name="Open G (DGDGBd)",
    open_strings=(62, 59, 55, 50, 47, 38),
)

# Half step down: Eb Ab Db Gb Bb eb
HALF_DOWN = Tuning(
    name="Halbton tiefer (Eb Ab Db Gb Bb eb)",
    open_strings=(63, 58, 54, 49, 44, 39),
)

ALL_TUNINGS: list[Tuning] = [STANDARD, DROP_D, OPEN_G, HALF_DOWN]


def tuning_by_name(name: str) -> Tuning:
    for t in ALL_TUNINGS:
        if t.name == name:
            return t
    return STANDARD


# General MIDI guitar program numbers (0-indexed, channel 0)
GM_GUITARS: list[tuple[str, int]] = [
    ("Nylon Acoustic (24)",   24),
    ("Steel Acoustic (25)",   25),
    ("Jazz Electric (26)",    26),
    ("Clean Electric (27)",   27),
    ("Muted Electric (28)",   28),
    ("Overdrive Guitar (29)", 29),
    ("Distortion Guitar (30)", 30),
]
