"""
Playback Engine

Plays a list of Column objects using FluidSynth with a .sf2 SoundFont.
Runs in a QThread; emits a Qt signal with the current column index so the
UI can update the playhead highlight in a thread-safe way.

Fallback: if FluidSynth is not available, a dummy engine is used that
emits column signals without producing sound, so the UI still works.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from tabplayer.parser import Column
from tabplayer.tuning import Tuning, STANDARD


# ---------------------------------------------------------------------------
# SoundFont search paths
# ---------------------------------------------------------------------------

SF2_SEARCH_PATHS: list[Path] = [
    Path("/usr/share/soundfonts/FluidR3_GM.sf2"),
    Path("/usr/share/sounds/sf2/FluidR3_GM.sf2"),
    Path("/usr/share/soundfonts/default.sf2"),
    Path("/usr/share/sounds/sf2/default.sf2"),
    Path(os.path.expanduser("~/Library/Audio/Sounds/Banks/FluidR3_GM.sf2")),
    Path("C:/soundfonts/FluidR3_GM.sf2"),
    Path("FluidR3_GM.sf2"),  # current directory
]

SF2_FILENAMES = [
    "FluidR3_GM.sf2", "GeneralUser GS.sf2", "TimGM6mb.sf2", "default.sf2"
]


def find_soundfont() -> Path | None:
    """Search common locations for a .sf2 SoundFont file."""
    for p in SF2_SEARCH_PATHS:
        if p.exists():
            return p
    # Also search common sound directories for any .sf2 file
    for directory in [
        Path("/usr/share/soundfonts"),
        Path("/usr/share/sounds/sf2"),
        Path(os.path.expanduser("~/.local/share/sounds")),
    ]:
        if directory.is_dir():
            for sf2 in directory.glob("*.sf2"):
                return sf2
    return None


# ---------------------------------------------------------------------------
# FluidSynth wrapper
# ---------------------------------------------------------------------------

class FluidSynthBackend:
    """Thin wrapper around fluidsynth.Synth with a per-channel instrument."""

    def __init__(self, sf2_path: Path, program: int = 25) -> None:
        import fluidsynth  # type: ignore
        self._fs = fluidsynth.Synth()
        self._sfid: int = -1

        # Try audio drivers in order of preference
        for driver in ("pipewire", "pulseaudio", "alsa", "oss"):
            try:
                self._fs.start(driver=driver)
                break
            except Exception:
                continue

        self._sfid = self._fs.sfload(str(sf2_path))
        if self._sfid == -1:
            raise RuntimeError(f"SoundFont konnte nicht geladen werden: {sf2_path}")

        self.channel = 0
        self.set_program(program)

    def set_program(self, program: int) -> None:
        self._program = program
        # program_select is more reliable than program_change when using a specific sfid
        self._fs.program_select(self.channel, self._sfid, 0, program)

    def note_on(self, midi: int, velocity: int = 90) -> None:
        self._fs.noteon(self.channel, midi, velocity)

    def note_off(self, midi: int) -> None:
        self._fs.noteoff(self.channel, midi)

    def all_notes_off(self) -> None:
        for midi in range(128):
            self._fs.noteoff(self.channel, midi)
        self.mod_wheel(0)

    def mod_wheel(self, value: int) -> None:
        """CC#1 modulation wheel 0-127. Most GM soundfonts map this to vibrato LFO."""
        try:
            self._fs.cc(self.channel, 1, max(0, min(127, value)))
        except Exception:
            pass

    def pitch_bend(self, semitones: float) -> None:
        """Pitch bend in semitones (-2..+2). MIDI range: -8192..+8191 = ±2 st."""
        val = int(semitones * 4096)
        val = max(-8192, min(8191, val))
        try:
            self._fs.pitch_bend(self.channel, val)
        except Exception:
            pass

    def close(self) -> None:
        self._fs.delete()


class DummyBackend:
    """No-op backend used when FluidSynth is not available."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def set_program(self, program: int) -> None:
        pass

    def note_on(self, midi: int, velocity: int = 90) -> None:
        pass

    def note_off(self, midi: int) -> None:
        pass

    def all_notes_off(self) -> None:
        pass

    def close(self) -> None:
        pass


def create_backend(sf2_path: Path | None, program: int) -> FluidSynthBackend | DummyBackend:
    if sf2_path is None:
        return DummyBackend("Keine SoundFont-Datei gefunden.")
    try:
        return FluidSynthBackend(sf2_path, program)
    except Exception as exc:
        return DummyBackend(f"FluidSynth konnte nicht geladen werden: {exc}")


# ---------------------------------------------------------------------------
# Playback Thread
# ---------------------------------------------------------------------------

# Subdivision options: label -> columns per beat
SUBDIVISIONS: dict[str, int] = {
    "Whole":      1,
    "Half":       2,
    "Quarter":    4,
    "Eighth":     8,
    "Sixteenth": 16,
}


class PlayerThread(QThread):
    """
    Plays back a list of Columns at a fixed tempo.

    Signals:
        column_changed(int): emitted when playback advances to a new column index.
        playback_finished(): emitted when the end of the tab is reached (and loop=False).
        error_occurred(str): emitted on fatal errors.
    """

    column_changed = Signal(int)
    playback_finished = Signal()
    error_occurred = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._columns: list[Column] = []
        self._tuning: Tuning = STANDARD
        self._bpm: int = 120
        self._subdivision: int = 8   # columns per beat (Achtel)
        self._loop: bool = False
        self._program: int = 25      # GM Steel Acoustic

        self._sf2_path: Path | None = find_soundfont()
        self._backend: FluidSynthBackend | DummyBackend | None = None

        self._running = False
        self._paused = False
        self._stop_requested = False
        self._start_col: int = 0     # allow resuming from a position

    # --- Configuration (call before start / while stopped) -----------------

    def set_columns(self, columns: list[Column]) -> None:
        self._columns = columns

    def set_tuning(self, tuning: Tuning) -> None:
        self._tuning = tuning

    def set_bpm(self, bpm: int) -> None:
        self._bpm = max(20, min(300, bpm))

    def set_subdivision(self, columns_per_beat: int) -> None:
        self._subdivision = columns_per_beat

    def set_loop(self, loop: bool) -> None:
        self._loop = loop

    def set_program(self, program: int) -> None:
        self._program = program
        if self._backend:
            self._backend.set_program(program)

    def set_sf2_path(self, path: Path) -> None:
        self._sf2_path = path

    def set_start_column(self, col: int) -> None:
        self._start_col = col

    # --- Playback control ---------------------------------------------------

    def pause(self) -> None:
        self._paused = True
        if self._backend:
            self._backend.all_notes_off()

    def resume(self) -> None:
        self._paused = False

    def stop(self) -> None:
        self._stop_requested = True
        self._paused = False
        if self._backend:
            self._backend.all_notes_off()

    @property
    def is_using_dummy_backend(self) -> bool:
        return isinstance(self._backend, DummyBackend)

    @property
    def dummy_reason(self) -> str:
        if isinstance(self._backend, DummyBackend):
            return self._backend.reason
        return ""

    # --- QThread.run --------------------------------------------------------

    def run(self) -> None:
        if not self._columns:
            return

        # Initialise backend lazily (first run)
        if self._backend is None:
            self._backend = create_backend(self._sf2_path, self._program)
            if isinstance(self._backend, DummyBackend):
                self.error_occurred.emit(
                    f"Audio nicht verfuegbar: {self._backend.reason}\n"
                    "Playhead laeuft trotzdem mit."
                )

        self._stop_requested = False
        note_duration = 0.15  # seconds each note rings before noteoff

        col_idx = self._start_col
        while not self._stop_requested:
            if col_idx >= len(self._columns):
                if self._loop:
                    col_idx = 0
                else:
                    break

            col = self._columns[col_idx]
            self.column_changed.emit(col.index)

            # Compute step duration in seconds
            seconds_per_beat = 60.0 / self._bpm
            step_duration = seconds_per_beat / self._subdivision * 4
            # (4 subdivisions per beat at "quarter" base; adjusted for chosen subdivision)
            # Simplified: each column = one subdivision slot
            step_duration = (60.0 / self._bpm) / (self._subdivision / 4.0)

            # Categorise notes by playback behaviour
            plain_notes:     list[int] = []
            ghost_notes:     list[int] = []
            vibrato_notes:   list[int] = []           # ~  vibrato via CC#1
            muted_notes:     list[int] = []           # x  dead string
            technique_notes: list[tuple[int, int]] = []  # slide/bend (start, end)
            slide_in_notes:  list[tuple[int, int]] = []  # /12 \7 (approach, target)

            for note in col.notes:
                if note.technique == "muted":
                    try:
                        muted_notes.append(
                            self._tuning.midi_note(note.string_index, 0))
                    except ValueError:
                        pass
                    continue

                try:
                    start_midi = self._tuning.midi_note(note.string_index, note.fret)
                except ValueError:
                    continue

                if note.technique == "ghost":
                    ghost_notes.append(start_midi)

                elif note.technique in ("vibrato",):
                    vibrato_notes.append(start_midi)

                elif note.technique in ("slide_in_up", "slide_in_up_vib"):
                    # approach from 2 semitones below
                    approach = max(0, start_midi - 2)
                    slide_in_notes.append((approach, start_midi))
                    if "vib" in (note.technique or ""):
                        vibrato_notes.append(start_midi)

                elif note.technique in ("slide_in_down", "slide_in_down_vib"):
                    # approach from 2 semitones above
                    approach = min(127, start_midi + 2)
                    slide_in_notes.append((approach, start_midi))
                    if "vib" in (note.technique or ""):
                        vibrato_notes.append(start_midi)

                elif note.technique in ("slide_up", "slide_down", "slide",
                                        "hammer_on", "pull_off",
                                        "bend", "release") and note.target_fret is not None:
                    try:
                        end_midi = self._tuning.midi_note(note.string_index, note.target_fret)
                        technique_notes.append((start_midi, end_midi))
                    except ValueError:
                        plain_notes.append(start_midi)

                else:
                    plain_notes.append(start_midi)

            tick = 0.01
            half = step_duration / 2.0

            # --- Approach-slide: play brief note from ±2 semitones -----------
            for approach_midi, _ in slide_in_notes:
                self._backend.note_on(approach_midi, velocity=70)
            approach_dur = min(0.06, half * 0.3)
            time.sleep(approach_dur)
            for approach_midi, target_midi in slide_in_notes:
                self._backend.note_off(approach_midi)
                self._backend.note_on(target_midi, velocity=85)

            # --- Muted notes: very quiet, cut quickly ------------------------
            for midi in muted_notes:
                self._backend.note_on(midi, velocity=35)

            # --- Plain, ghost, vibrato start ---------------------------------
            for midi in plain_notes:
                self._backend.note_on(midi, velocity=90)
            for midi in ghost_notes:
                self._backend.note_on(midi, velocity=55)
            for midi in vibrato_notes:
                if midi not in [t for _, t in slide_in_notes]:
                    self._backend.note_on(midi, velocity=85)

            # Technique start notes
            for start_midi, _ in technique_notes:
                self._backend.note_on(start_midi, velocity=90)

            # Cut muted quickly
            muted_cut = min(0.04, step_duration * 0.12)
            time.sleep(muted_cut)
            for midi in muted_notes:
                self._backend.note_off(midi)

            # Enable vibrato via CC#1 modulation
            has_vibrato = bool(vibrato_notes)
            if has_vibrato:
                self._backend.mod_wheel(80)

            # Sleep first half (minus already-elapsed time)
            elapsed = approach_dur + muted_cut
            while elapsed < half and not self._stop_requested:
                if self._paused:
                    time.sleep(tick)
                    continue
                time.sleep(tick)
                elapsed += tick

            # Slide / hammer / pull-off: transition to target
            for start_midi, end_midi in technique_notes:
                self._backend.note_off(start_midi)
                self._backend.note_on(end_midi, velocity=75)

            # Sleep second half
            elapsed = 0.0
            while elapsed < half and not self._stop_requested:
                if self._paused:
                    time.sleep(tick)
                    continue
                time.sleep(tick)
                elapsed += tick

            # Reset vibrato and note-off everything
            if has_vibrato:
                self._backend.mod_wheel(0)

            midi_notes = (plain_notes + ghost_notes + vibrato_notes
                          + [t for _, t in slide_in_notes]
                          + [e for _, e in technique_notes])
            for midi in set(midi_notes):
                self._backend.note_off(midi)

            if not self._paused:
                col_idx += 1

        if self._backend:
            self._backend.all_notes_off()

        if not self._stop_requested:
            self.playback_finished.emit()

    def cleanup(self) -> None:
        """Call when the application exits to release FluidSynth resources."""
        self.stop()
        self.wait(2000)
        if self._backend:
            self._backend.close()
            self._backend = None
