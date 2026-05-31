# Guitar Tab Player

Interaktiver ASCII-Gitarren-Tab-Player mit echten Gitarren-Samples.  
Beliebige ASCII-Tabs (Ultimate Guitar Format) einfuegen, Tempo einstellen, abspielen — die aktuelle Position wird live hervorgehoben.

## Voraussetzungen

### 1. FluidSynth (native Bibliothek)

**Linux (Arch/Manjaro):**
```bash
sudo pacman -S fluidsynth
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt install fluidsynth
```

**macOS:**
```bash
brew install fluid-synth
```

**Windows:**  
FluidSynth-Release-DLL von https://github.com/FluidSynth/fluidsynth/releases herunterladen,  
entpacken und den Ordner zur PATH-Umgebungsvariable hinzufuegen.

### 2. SoundFont (.sf2)

Eine General-MIDI-SoundFont wird benoetigt. Empfehlung: **FluidR3_GM.sf2**

**Linux:**
```bash
sudo pacman -S soundfont-fluid   # Arch
# oder
sudo apt install fluid-soundfont-gm   # Debian/Ubuntu
# Dann liegt sie unter /usr/share/soundfonts/FluidR3_GM.sf2
```

**macOS / Windows:**  
Von https://member.keymusician.com/Member/FluidR3_GM/index.html herunterladen  
und als `FluidR3_GM.sf2` im Projektverzeichnis oder unter einem der Standard-Pfade ablegen:
- Linux: `/usr/share/soundfonts/` oder `/usr/share/sounds/sf2/`
- macOS: `~/Library/Audio/Sounds/Banks/`
- Windows: `C:\soundfonts\`

Der Player sucht automatisch in diesen Pfaden. Alternativ kann die SF2-Datei  
beliebig abgelegt und ueber das Datei-Menue geladen werden.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Starten

```bash
python -m tabplayer
```

## Tab-Format

Standard ASCII-Gitarrentab (z. B. von Ultimate Guitar):

```
e|--12-11-12-11-12-7-10-8--|
B|--------------------------|
G|--------------------------|
D|--------------------------|
A|--------------------------|
E|--------------------------|
```

- Saiten-Labels (`e B G D A E`) am Zeilenanfang sind optional.
- Mehrere Systeme (Bloecke mit 6 Zeilen) werden automatisch zu einer Sequenz zusammengefuegt.
- Bunde >= 10 (z. B. `12`) werden korrekt als zweistellige Zahlen erkannt.
- Akkorde (mehrere Saiten in derselben Spalte) werden gleichzeitig gespielt.

## Hinweis zum Rhythmus

ASCII-Tabs enthalten keine Rhythmus-Information. Der Player nimmt gleichmaessige  
Spaltenabstaende an — steuerbar ueber den BPM-Slider und die Unterteilungs-Auswahl.  
Das reicht zum Verifizieren der Tonhoehen, ist aber kein exaktes Notensatz-Playback.
