"""
Main application window for the Guitar Tab Player.
"""

from __future__ import annotations

from pathlib import Path

from tabplayer.i18n import _, set_language, get_available_languages

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont, QTextCharFormat, QColor, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tabplayer import parser as tab_parser
from tabplayer.examples import EXAMPLES
from tabplayer.generator import (
    OllamaGeneratorThread,
    TempoFetcherThread,
    build_prompt,
    fetch_models,
    DEFAULT_MODEL,
    OLLAMA_BASE_URL,
)
from tabplayer.player import PlayerThread, SUBDIVISIONS, find_soundfont
from tabplayer.tuning import ALL_TUNINGS, GM_GUITARS, tuning_by_name


# ---------------------------------------------------------------------------
# Playhead display widget
# ---------------------------------------------------------------------------

class TabDisplayWidget(QPlainTextEdit):
    """
    Read-only monospace text widget that highlights the current playhead
    column using ExtraSelections.

    The widget stores the character-offset of each parsed Column so it
    can highlight the right position when column_changed fires.
    """

    HIGHLIGHT_COLOR = QColor("#f59e0b")   # amber
    HIGHLIGHT_FG    = QColor("#1e1e2e")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        font = QFont("Monospace", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # One entry per column; each entry is a list of (char_pos, width) for
        # every note in that column (one per active string) so chords are fully lit up.
        self._col_char_positions: list[list[tuple[int, int]]] = []
        self._col_system_tops: list[int] = []

    def load_result(self, result: tab_parser.ParseResult, raw_text: str) -> None:
        """Display the raw tab text and compute per-column character positions."""
        self.setPlainText(raw_text)
        self._col_char_positions = []
        self._col_system_tops = []
        self._clear_highlight()

        if not result.raw_systems:
            return

        doc_text = self.toPlainText()
        lines = doc_text.splitlines(keepends=True)

        line_offsets: list[int] = []
        offset = 0
        for line in lines:
            line_offsets.append(offset)
            offset += len(line)

        system_line_ranges = self._find_system_line_numbers(lines, result.raw_systems)

        col_positions: list[list[tuple[int, int]]] = []
        col_system_tops: list[int] = []
        for sys_idx, system_lines_indices in enumerate(system_line_ranges):
            if sys_idx >= len(result.raw_systems):
                break
            raw_sys = result.raw_systems[sys_idx]
            before = len(col_positions)
            self._collect_col_positions(
                raw_sys, system_lines_indices, line_offsets, lines, col_positions
            )
            # char offset of the very first line of this system (= top string)
            system_top = (line_offsets[system_lines_indices[0]]
                          if system_lines_indices else 0)
            col_system_tops.extend([system_top] * (len(col_positions) - before))

        self._col_char_positions = col_positions
        self._col_system_tops = col_system_tops

    def _find_system_line_numbers(
        self, lines: list[str], raw_systems: list[list[str]]
    ) -> list[list[int]]:
        result = []
        search_from = 0
        for system in raw_systems:
            indices: list[int] = []
            i = search_from
            for sys_line in system:
                while i < len(lines):
                    if lines[i].rstrip("\n\r") == sys_line.rstrip("\n\r"):
                        indices.append(i)
                        i += 1
                        break
                    i += 1
            if len(indices) == 6:
                result.append(indices)
                search_from = i
        return result

    def _collect_col_positions(
        self,
        raw_system: list[str],
        line_indices: list[int],
        line_offsets: list[int],
        doc_lines: list[str],
        col_positions: list[list[tuple[int, int]]],
    ) -> None:
        """Walk column by column; collect ALL string positions per chord column."""
        from tabplayer.parser import _strip_label, _scan_expression

        stripped = [_strip_label(ln) for ln in raw_system]
        max_len = max(len(s) for s in stripped) if stripped else 0
        stripped_padded = [s.ljust(max_len, "-") for s in stripped]

        # Character offset within each raw line where the stripped content begins
        raw_label_offsets: list[int] = []
        for raw_line in raw_system:
            stripped_content = _strip_label(raw_line)
            offset_in_raw = 0
            for k in range(len(raw_line)):
                if raw_line[k:].startswith(stripped_content[:max(1, len(stripped_content))]):
                    offset_in_raw = k
                    break
            raw_label_offsets.append(offset_in_raw)

        pos = 0
        while pos < max_len:
            advance = 1
            note_cells: list[tuple[int, int]] = []  # (char_pos, display_width) per string

            for si, sline in enumerate(stripped_padded):
                expr = _scan_expression(sline, pos)
                if expr is None:
                    continue
                _fret, _tech, _target, width = expr
                advance = max(advance, width)
                if si < len(line_indices):
                    doc_line_idx = line_indices[si]
                    if doc_line_idx < len(line_offsets):
                        char_pos = (line_offsets[doc_line_idx]
                                    + raw_label_offsets[si] + pos)
                        note_cells.append((char_pos, width))

            if note_cells:
                col_positions.append(note_cells)

            pos += advance

    def highlight_column(self, col_index: int) -> None:
        self._clear_highlight()
        if not self._col_char_positions or col_index >= len(self._col_char_positions):
            return

        fmt = QTextCharFormat()
        fmt.setBackground(self.HIGHLIGHT_COLOR)
        fmt.setForeground(self.HIGHLIGHT_FG)
        fmt.setFontWeight(700)

        selections: list[QTextEdit.ExtraSelection] = []
        first_cursor = None

        for char_pos, width in self._col_char_positions[col_index]:
            cursor = self.textCursor()
            cursor.setPosition(char_pos)
            cursor.movePosition(QTextCursor.MoveOperation.Right,
                                QTextCursor.MoveMode.KeepAnchor, width)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            selections.append(sel)
            if first_cursor is None:
                first_cursor = cursor

        self.setExtraSelections(selections)

        # Scroll to the TOP LINE of the current system so all 6 strings are visible.
        # Using the system-top char offset (not just the note position) prevents the
        # view from showing only a partial system.
        if (self._col_system_tops and col_index < len(self._col_system_tops)):
            top_cursor = self.textCursor()
            top_cursor.setPosition(self._col_system_tops[col_index])
            self.setTextCursor(top_cursor)
            self.ensureCursorVisible()
        elif first_cursor:
            self.setTextCursor(first_cursor)
            self.ensureCursorVisible()

    def _clear_highlight(self) -> None:
        self.setExtraSelections([])


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(_("Guitar Tab Player"))
        self.resize(1000, 700)

        self._player = PlayerThread(self)
        self._player.column_changed.connect(self._on_column_changed)
        self._player.playback_finished.connect(self._on_playback_finished)
        self._player.error_occurred.connect(self._on_error)

        self._generator = OllamaGeneratorThread(self)
        self._generator.token.connect(self._on_gen_token)
        self._generator.finished.connect(self._on_gen_finished)
        self._generator.error.connect(self._on_gen_error)

        self._tempo_fetcher = TempoFetcherThread(self)
        self._tempo_fetcher.tempo_found.connect(self._on_tempo_found)
        self._tempo_fetcher.error.connect(self._on_tempo_error)

        self._parse_result: tab_parser.ParseResult | None = None
        self._is_playing = False
        self._current_col = 0

        self._build_ui()
        self._load_example(list(EXAMPLES.keys())[0])
        self._check_audio()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        # --- Menu bar: Language picker --------------------------------
        self._build_menu()

        # --- Tab widget: Player | Generator ---------------------------
        self._tabs = QTabWidget()
        root_layout.addWidget(self._tabs, stretch=1)

        self._tabs.addTab(self._build_player_tab(), _("🎸 Player"))
        self._tabs.addTab(self._build_generator_tab(), _("✨ Tab Generator"))

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(_("Ready."))

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        lang_menu = menu_bar.addMenu(_("Language"))
        for code, name in get_available_languages():
            action = lang_menu.addAction(name)
            action.triggered.connect(lambda checked=False, c=code: self._change_language(c))

    def _change_language(self, lang_code: str) -> None:
        set_language(lang_code)
        # Rebuild UI labels by re-running build steps on existing widgets
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        """Update all translatable widget texts after a language switch."""
        self.setWindowTitle(_("Guitar Tab Player"))
        self._tabs.setTabText(0, _("🎸 Player"))
        self._tabs.setTabText(1, _("✨ Tab Generator"))
        # Rebuild menu
        self.menuBar().clear()
        self._build_menu()
        self._status.showMessage(_("Ready."))

    # ------------------------------------------------------------------
    # Player tab
    # ------------------------------------------------------------------

    def _build_player_tab(self) -> QWidget:
        w = QWidget()
        root_layout = QVBoxLayout(w)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(6)

        # --- Top: example loader + sf2 --------------------------------
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel(_("Example:")))
        self._example_combo = QComboBox()
        self._example_combo.addItems(list(EXAMPLES.keys()))
        self._example_combo.currentTextChanged.connect(self._load_example)
        top_bar.addWidget(self._example_combo)
        top_bar.addStretch()

        sf2_btn = QPushButton(_("Load SoundFont…"))
        sf2_btn.setToolTip(_("Manually select a .sf2 SoundFont file"))
        sf2_btn.clicked.connect(self._browse_sf2)
        top_bar.addWidget(sf2_btn)
        root_layout.addLayout(top_bar)

        # --- Splitter: input | display --------------------------------
        splitter = QSplitter(Qt.Orientation.Vertical)
        root_layout.addWidget(splitter, stretch=1)

        # Input editor
        input_group = QGroupBox(_("Tab Input  (paste any ASCII tab here)"))
        input_layout = QVBoxLayout(input_group)
        self._input_edit = QPlainTextEdit()
        font = QFont("Monospace", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._input_edit.setFont(font)
        self._input_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._input_edit.setPlaceholderText(
            _("Paste ASCII guitar tab here…") + "\n\n"
            "e|--0-2-3--|\nB|--0-3-3--|\nG|--0-2-0--|\n"
            "D|---------|\nA|---------|\nE|---------|"
        )
        parse_btn = QPushButton(_("Parse Tab ▶"))
        parse_btn.clicked.connect(self._parse_input)
        input_layout.addWidget(self._input_edit)
        input_layout.addWidget(parse_btn)
        splitter.addWidget(input_group)

        # Tab display
        display_group = QGroupBox(_("Parsed Tab  (playhead highlighted)"))
        display_layout = QVBoxLayout(display_group)
        self._tab_display = TabDisplayWidget()
        display_layout.addWidget(self._tab_display)
        splitter.addWidget(display_group)
        splitter.setSizes([220, 380])

        # --- Transport bar --------------------------------------------
        transport_group = QGroupBox(_("Transport"))
        transport_layout = QHBoxLayout(transport_group)

        self._play_btn = QPushButton("▶ " + _("Play"))
        self._play_btn.setCheckable(True)
        self._play_btn.clicked.connect(self._toggle_play)
        self._play_btn.setMinimumWidth(90)

        self._stop_btn = QPushButton("■ " + _("Stop"))
        self._stop_btn.clicked.connect(self._stop)
        self._stop_btn.setMinimumWidth(80)

        transport_layout.addWidget(self._play_btn)
        transport_layout.addWidget(self._stop_btn)
        transport_layout.addSpacing(16)

        transport_layout.addWidget(QLabel(_("BPM:")))
        self._bpm_slider = QSlider(Qt.Orientation.Horizontal)
        self._bpm_slider.setRange(20, 280)
        self._bpm_slider.setValue(80)
        self._bpm_slider.setFixedWidth(150)
        self._bpm_slider.valueChanged.connect(self._on_bpm_changed)
        self._bpm_label = QLabel("80")
        self._bpm_label.setMinimumWidth(30)
        transport_layout.addWidget(self._bpm_slider)
        transport_layout.addWidget(self._bpm_label)

        self._auto_tempo_btn = QPushButton("🎵 " + _("Auto"))
        self._auto_tempo_btn.setToolTip(
            _("Auto-detect BPM (asks Ollama for the song tempo)")
        )
        self._auto_tempo_btn.setFixedWidth(70)
        self._auto_tempo_btn.clicked.connect(self._fetch_auto_tempo)
        transport_layout.addWidget(self._auto_tempo_btn)
        transport_layout.addSpacing(16)

        transport_layout.addWidget(QLabel(_("Subdivision:")))
        self._subdiv_combo = QComboBox()
        self._subdiv_combo.addItems(list(SUBDIVISIONS.keys()))
        self._subdiv_combo.setCurrentText("Eighth")
        self._subdiv_combo.currentTextChanged.connect(self._on_subdiv_changed)
        transport_layout.addWidget(self._subdiv_combo)
        transport_layout.addSpacing(16)

        transport_layout.addWidget(QLabel(_("Tuning:")))
        self._tuning_combo = QComboBox()
        for t in ALL_TUNINGS:
            self._tuning_combo.addItem(t.name)
        self._tuning_combo.currentTextChanged.connect(self._on_tuning_changed)
        transport_layout.addWidget(self._tuning_combo)
        transport_layout.addSpacing(16)

        transport_layout.addWidget(QLabel(_("Instrument:")))
        self._instrument_combo = QComboBox()
        for lbl, _prog in GM_GUITARS:
            self._instrument_combo.addItem(lbl)
        self._instrument_combo.setCurrentIndex(1)
        self._instrument_combo.currentIndexChanged.connect(self._on_instrument_changed)
        transport_layout.addWidget(self._instrument_combo)
        transport_layout.addSpacing(16)

        self._loop_cb = QCheckBox(_("Loop"))
        self._loop_cb.stateChanged.connect(self._on_loop_changed)
        transport_layout.addWidget(self._loop_cb)
        transport_layout.addStretch()

        root_layout.addWidget(transport_group)

        note_label = QLabel(
            "<i>" + _("Note: ASCII tabs contain no rhythm information. "
                       "BPM and subdivision control the playback speed.") + "</i>"
        )
        note_label.setWordWrap(True)
        root_layout.addWidget(note_label)

        return w

    # ------------------------------------------------------------------
    # Generator tab
    # ------------------------------------------------------------------

    def _build_generator_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # --- Input form -----------------------------------------------
        form_group = QGroupBox(_("Song Request"))
        form = QFormLayout(form_group)
        form.setHorizontalSpacing(12)

        self._gen_song   = QLineEdit()
        self._gen_song.setPlaceholderText(_("e.g. Für Elise"))
        self._gen_artist = QLineEdit()
        self._gen_artist.setPlaceholderText(_("e.g. Beethoven  (optional)"))
        self._gen_section = QLineEdit()
        self._gen_section.setPlaceholderText(_("e.g. Intro, main riff, verse  (optional)"))

        self._gen_model  = QLineEdit(DEFAULT_MODEL)
        self._gen_model.setPlaceholderText(_("Model name, e.g. qwen3:latest"))

        form.addRow(_("Song:"), self._gen_song)
        form.addRow(_("Artist:"), self._gen_artist)
        form.addRow(_("Section:"), self._gen_section)
        form.addRow(_("Ollama Model:"), self._gen_model)
        layout.addWidget(form_group)

        # --- Buttons --------------------------------------------------
        btn_row = QHBoxLayout()

        self._gen_btn = QPushButton("✨ " + _("Generate Tab"))
        self._gen_btn.setMinimumHeight(32)
        self._gen_btn.clicked.connect(self._start_generation)
        btn_row.addWidget(self._gen_btn)

        self._gen_stop_btn = QPushButton("⏹ " + _("Cancel"))
        self._gen_stop_btn.setEnabled(False)
        self._gen_stop_btn.clicked.connect(self._stop_generation)
        btn_row.addWidget(self._gen_stop_btn)

        self._gen_prompt_btn = QPushButton("📋 " + _("Show Prompt"))
        self._gen_prompt_btn.setToolTip(_("Show the prompt that will be sent to Ollama"))
        self._gen_prompt_btn.clicked.connect(self._show_prompt)
        btn_row.addWidget(self._gen_prompt_btn)

        btn_row.addStretch()

        self._load_into_player_btn = QPushButton("▶ " + _("Load into Player"))
        self._load_into_player_btn.setEnabled(False)
        self._load_into_player_btn.setToolTip(_("Copy the generated tab into the Player"))
        self._load_into_player_btn.clicked.connect(self._load_generated_into_player)
        btn_row.addWidget(self._load_into_player_btn)

        layout.addLayout(btn_row)

        # --- Output area ----------------------------------------------
        out_group = QGroupBox(_("Generated Tab  (streaming live)"))
        out_layout = QVBoxLayout(out_group)

        self._gen_output = QPlainTextEdit()
        mono = QFont("Monospace", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._gen_output.setFont(mono)
        self._gen_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._gen_output.setReadOnly(False)
        self._gen_output.setPlaceholderText(
            _("Generated tab will appear here…") + "\n\n" +
            _("You can edit it before loading into the Player.")
        )
        out_layout.addWidget(self._gen_output)
        layout.addWidget(out_group, stretch=1)

        hint = QLabel(
            "<i>" + _("Ollama must be running locally: <b>ollama serve</b>  |  "
                       "Pull model: <b>ollama pull qwen3:latest</b>") + "</i>"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        return w

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _load_example(self, name: str) -> None:
        text = EXAMPLES.get(name, "")
        self._input_edit.setPlainText(text)
        self._parse_input()

    def _parse_input(self) -> None:
        text = self._input_edit.toPlainText()
        result = tab_parser.parse(text)
        self._parse_result = result

        self._tab_display.load_result(result, text)
        self._current_col = 0
        self._player.set_columns(result.columns)

        if result.errors:
            msgs = "; ".join(e.message for e in result.errors)
            if not result.columns:
                self._status.showMessage(_("Parse error: ") + msgs)
            else:
                self._status.showMessage(
                    f"{len(result.columns)} " + _("columns parsed. Warnings: ") + msgs
                )
        else:
            self._status.showMessage(
                _("Tab parsed:") + f" {len(result.columns)} " +
                _("columns /") + f" {len(result.raw_systems)} " + _("system(s).")
            )

    def _toggle_play(self, checked: bool) -> None:
        if checked:
            self._start_playback()
        else:
            self._pause_playback()

    def _start_playback(self) -> None:
        if self._parse_result is None or not self._parse_result.columns:
            self._status.showMessage(_("No valid tab loaded."))
            self._play_btn.setChecked(False)
            return

        if self._player.isRunning() and not self._player._paused:
            return

        if self._player.isRunning() and self._player._paused:
            self._player.resume()
            self._play_btn.setText("⏸ " + _("Pause"))
            self._is_playing = True
            return

        self._player.set_start_column(self._current_col)
        self._player.set_bpm(self._bpm_slider.value())
        self._player.set_subdivision(SUBDIVISIONS[self._subdiv_combo.currentText()])
        self._player.set_loop(self._loop_cb.isChecked())
        self._player.set_tuning(tuning_by_name(self._tuning_combo.currentText()))
        _lbl, prog = GM_GUITARS[self._instrument_combo.currentIndex()]
        self._player.set_program(prog)

        self._player.start()
        self._play_btn.setText("⏸ " + _("Pause"))
        self._is_playing = True

    def _pause_playback(self) -> None:
        if self._player.isRunning():
            self._player.pause()
        self._play_btn.setText("▶ " + _("Play"))
        self._is_playing = False

    def _stop(self) -> None:
        self._player.stop()
        self._player.wait(1000)
        self._play_btn.setChecked(False)
        self._play_btn.setText("▶ " + _("Play"))
        self._is_playing = False
        self._current_col = 0
        self._tab_display._clear_highlight()
        self._status.showMessage(_("Stopped."))

    def _browse_sf2(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, _("Select SoundFont"), str(Path.home()), "SoundFont Files (*.sf2)"
        )
        if path:
            sf2 = Path(path)
            self._player.set_sf2_path(sf2)
            if self._player._backend:
                self._player._backend.close()
                self._player._backend = None
            self._status.showMessage(_("SoundFont loaded: ") + sf2.name)

    # ------------------------------------------------------------------
    # Slots (from player thread)
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_column_changed(self, col_index: int) -> None:
        self._current_col = col_index
        self._tab_display.highlight_column(col_index)
        if self._parse_result and col_index < len(self._parse_result.columns):
            col = self._parse_result.columns[col_index]
            n = len(col.notes)
            label = _("note") if n == 1 else _("chord ({n} notes)").format(n=n)
            total = len(self._parse_result.columns)
            self._status.showMessage(
                _("Column {cur} / {total}  —  {label}").format(
                    cur=col_index + 1, total=total, label=label)
            )

    @Slot()
    def _on_playback_finished(self) -> None:
        self._play_btn.setChecked(False)
        self._play_btn.setText("▶ " + _("Play"))
        self._is_playing = False
        self._current_col = 0
        self._status.showMessage(_("Done."))

    @Slot(str)
    def _on_error(self, msg: str) -> None:
        self._status.showMessage(_("Audio warning: ") + msg)

    # ------------------------------------------------------------------
    # Control change handlers
    # ------------------------------------------------------------------

    def _on_bpm_changed(self, value: int) -> None:
        self._bpm_label.setText(str(value))
        self._player.set_bpm(value)

    def _on_subdiv_changed(self, text: str) -> None:
        self._player.set_subdivision(SUBDIVISIONS.get(text, 8))

    def _on_tuning_changed(self, name: str) -> None:
        self._player.set_tuning(tuning_by_name(name))

    def _on_instrument_changed(self, index: int) -> None:
        _lbl, prog = GM_GUITARS[index]
        self._player.set_program(prog)

    def _on_loop_changed(self, state: int) -> None:
        self._player.set_loop(bool(state))

    # ------------------------------------------------------------------
    # Auto-Tempo
    # ------------------------------------------------------------------

    def _fetch_auto_tempo(self) -> None:
        if self._tempo_fetcher.isRunning():
            return

        song = self._gen_song.text().strip()
        artist = self._gen_artist.text().strip()
        if not song:
            first_line = self._input_edit.toPlainText().splitlines()[0].strip() if self._input_edit.toPlainText().strip() else ""
            song = first_line or "this song"

        self._tempo_fetcher.set_query(song, artist)
        self._tempo_fetcher.set_model(self._gen_model.text().strip() or DEFAULT_MODEL)
        self._auto_tempo_btn.setEnabled(False)
        self._status.showMessage(
            _("Asking Ollama for BPM of \"{song}\"…").format(song=song)
        )
        self._tempo_fetcher.start()

    @Slot(int)
    def _on_tempo_found(self, bpm: int) -> None:
        self._bpm_slider.setValue(bpm)
        self._auto_tempo_btn.setEnabled(True)
        self._status.showMessage(_("Auto-Tempo: {bpm} BPM set.").format(bpm=bpm))

    @Slot(str)
    def _on_tempo_error(self, msg: str) -> None:
        self._auto_tempo_btn.setEnabled(True)
        self._status.showMessage(_("Auto-Tempo failed: ") + msg)

    # ------------------------------------------------------------------
    # Startup check
    # ------------------------------------------------------------------

    def _check_audio(self) -> None:
        sf2 = find_soundfont()
        if sf2:
            self._status.showMessage(_("SoundFont found: ") + str(sf2))
        else:
            self._status.showMessage(
                _("No SoundFont (.sf2) found — load one manually or install FluidR3_GM.sf2. "
                  "Playhead will still work.")
            )

    # ------------------------------------------------------------------
    # Generator actions & slots
    # ------------------------------------------------------------------

    def _build_prompt_from_form(self) -> str:
        tuning_name = self._tuning_combo.currentText()
        return build_prompt(
            song    = self._gen_song.text().strip(),
            artist  = self._gen_artist.text().strip(),
            section = self._gen_section.text().strip(),
            tuning  = tuning_name,
        )

    def _start_generation(self) -> None:
        song = self._gen_song.text().strip()
        if not song:
            self._status.showMessage(_("Please enter a song title."))
            return

        if self._generator.isRunning():
            return

        prompt = self._build_prompt_from_form()
        self._generator.set_model(self._gen_model.text().strip() or DEFAULT_MODEL)
        self._generator.set_prompt(prompt)

        self._gen_output.clear()
        self._gen_btn.setEnabled(False)
        self._gen_stop_btn.setEnabled(True)
        self._load_into_player_btn.setEnabled(False)
        self._status.showMessage(_("Generating tab for \"{song}\"…").format(song=song))

        self._generator.start()

    def _stop_generation(self) -> None:
        self._generator.stop()
        self._gen_btn.setEnabled(True)
        self._gen_stop_btn.setEnabled(False)
        self._status.showMessage(_("Generation cancelled."))

    def _show_prompt(self) -> None:
        prompt = self._build_prompt_from_form()
        self._gen_output.setPlainText(
            "── " + _("Prompt sent to Ollama") + " ──\n\n"
            + prompt
            + "\n\n── " + _("End of prompt") + " ──"
        )
        self._status.showMessage(_("Prompt displayed."))

    def _load_generated_into_player(self) -> None:
        text = self._gen_output.toPlainText().strip()
        if not text:
            return
        self._input_edit.setPlainText(text)
        self._parse_input()
        self._tabs.setCurrentIndex(0)
        self._status.showMessage(_("Tab loaded into Player and parsed."))

    @Slot(str)
    def _on_gen_token(self, token: str) -> None:
        cursor = self._gen_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(token)
        self._gen_output.setTextCursor(cursor)
        self._gen_output.ensureCursorVisible()

    @Slot(str)
    def _on_gen_finished(self, full_text: str) -> None:
        self._gen_btn.setEnabled(True)
        self._gen_stop_btn.setEnabled(False)
        self._load_into_player_btn.setEnabled(bool(full_text.strip()))
        self._status.showMessage(
            _("Tab generated. Click '▶ Load into Player' to play it.")
        )

    @Slot(str)
    def _on_gen_error(self, msg: str) -> None:
        self._gen_btn.setEnabled(True)
        self._gen_stop_btn.setEnabled(False)
        self._gen_output.setPlainText(_("Error:") + "\n" + msg)
        self._status.showMessage(_("Generation failed."))

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._generator.stop()
        self._player.cleanup()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------

def run() -> None:
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
