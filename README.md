# Writing Parrot (طوطی‌نویس)

Turn long spoken-word recordings (book-club sessions, lectures, interviews) into
plain-text transcripts — **locally and offline**, on your own GPU. Nothing is ever
uploaded to a cloud service.

Built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with OpenAI's
**`large-v3`** model. Tuned for **Persian (فارسی)** by default, but works for any
language Whisper supports via `--language`.

- 🔒 **Private** — audio never leaves your machine
- ⚡ **Fast** — a ~90-minute recording transcribes in ~20–25 min on a laptop RTX 4050
- 🎯 **Accurate names** — seed the model with a session's proper nouns to fix the
  usual garbling of book titles, authors, and characters
- 🧱 **Self-contained** — the Python environment and the model live inside the
  project folder, so it doesn't depend on (and isn't wiped by) `~/.cache`

---

## Desktop app (preview, Linux)

A point-and-click version for people who'd rather not use a terminal, in English or
Persian (switch with the **فا / EN** button).

```bash
./setup.sh        # one time
./run-gui.sh      # open the app
```

- **First launch** checks your computer, downloads what it needs (graphics-card
  support and the speech model) with live progress, and runs a quick test. Downloads
  continue where they stopped if the internet drops. If you already used the
  command line, it offers to reuse the model in `./models/`.
- **Drop a recording** on the window, optionally list the names in it, and watch the
  text appear.
- **Fix mistakes with ChatGPT, Claude or Gemini**: the app splits the transcript into
  numbered parts you copy into the AI, then you paste its answers back. You review
  every change side by side (each one can be undone) before the corrected
  `<name> - متن اصلاح‌شده.txt` is saved next to the raw transcript. Lines the AI
  rewrote too much are kept as they were.
- **Fix it here (private), optional**: setup has a checkbox for a small AI helper that
  runs on your own computer, so nothing leaves it. How big it is depends on the
  computer, and the app decides for you: with a graphics card of 10 GB or more, or a
  Mac with 24 GB or more, you get a larger, better model (about 6.4 GB); with a
  graphics card of 5 GB or more (such as a 6 GB laptop card), or a Mac with 12 GB or
  more, you get a 4.8 GB model. In both cases the box is ticked. On any other computer
  the same 4.8 GB model would run on the processor, which is much slower, so the box
  starts unticked and ChatGPT, Claude or Gemini is the better choice. It is a
  **first pass and it makes mistakes**: check every change in the review screen.
  ChatGPT, Claude or Gemini (above) still give the best Persian quality.
- **Loading takes a few minutes.** Each time the app starts the helper it has to load
  it into memory (about 100 s measured on an RTX 4050 laptop), with a progress bar. It
  then stays loaded while the app is open, and is unloaded before each new
  transcription so the speech model has the graphics memory.

The app keeps its downloads and settings in your user data folder
(`~/.local/share/WritingParrot` on Linux), not in the project folder. Windows and
macOS installers come in a later release.

---

## Requirements

- **Linux** (tested on Ubuntu 24.04) or **Windows 10/11** (64-bit)
- **NVIDIA GPU** with recent drivers (CPU-only also works but is much slower)
- **Python 3.11+** (tested on 3.12). On Windows install it from
  [python.org](https://www.python.org/downloads/) and tick **"Add python.exe to PATH"**.

No system-wide CUDA toolkit and no ffmpeg install are needed. The CUDA libraries
come as Python wheels (see `requirements.txt`), and audio decoding uses the FFmpeg
that ships inside PyAV.

---

## Setup (one time)

**Linux**

```bash
git clone https://github.com/javadtavakoli/book-transcriber.git
cd book-transcriber
./setup.sh
```

**Windows**: download/clone the repo, then double-click **`setup.bat`** (or run it
from a terminal).

The **model (~2.9 GB) downloads automatically on the first run** into `./models/`
and is reused offline afterwards. The first run therefore takes longer; every run
after that is fully offline.

> `venv/` and `models/` are intentionally **not** in git (they're multi-gigabyte).
> That's why you create them locally here.

---

## Usage

| | Linux | Windows |
|---|---|---|
| Transcribe a file | `./run.sh recording.m4a` | `run.bat recording.m4a`, **or drag the file onto `run.bat`** |
| See all options | `./run.sh -h` | `run.bat -h` |

The transcript is written next to the audio as `recording - متن خام.txt`.
If you double-click `run.bat` without a file, it asks for the path. You can drag
the file into the window.

### Options

```
-o, --output FILE       where to write the transcript (single input only)
-p, --prompt TEXT       proper nouns to seed the model with (see below)
-f, --prompt-file FILE  same, read from a UTF-8 text file
-l, --language CODE     language (default: fa; e.g. en, ar, ru)
-t, --timestamps        prefix each line with [h:mm:ss]
-m, --model NAME        Whisper model (default: large-v3)
-d, --device auto|cuda|cpu
```

Several files can be given at once; the model is loaded only once:

```bash
./run.sh session1.m4a session2.m4a -f prompts/my-book.txt -t
```

Both `.wav` and `.m4a` (and most other audio formats) work. **WAV is preferred** when
you have the choice.

Progress is printed live and also written to `.transcribe_progress.txt`:

```
loading large-v3 on cuda/float16 ...
loaded on cuda/float16
audio duration: 5447s (90.8 min)
 25.8%  seg#500  t=  1405s/5447s  elapsed=403s  eta=1160s
...
DONE  segments=1982  elapsed=1423s
```

### Seed the model with names (biggest quality win)

List the proper nouns you expect to hear: book title, author, characters,
thinkers. Whisper uses them to spell names correctly instead of guessing. The
easiest way is one text file per book in `prompts/` (see the examples there):

```bash
./run.sh session.m4a -f prompts/example-chasing-homer.txt
```

or inline:

```bash
./run.sh session.m4a -p "جلسهٔ کتاب‌خوانی. کتاب: تعقیب هومر، کراسناهورکای، بکت، کافکا."
```

### Run in the background (Linux)

```bash
nohup ./run.sh "/path/to/recording.wav" > run.log 2>&1 &
tail -f .transcribe_progress.txt
```

---

## How it works

- **`large-v3`** is the highest-quality general Whisper model; the transcript
  quality ceiling on group recordings is overlapping speech and mic distance, not
  the model.
- The decoder is tuned to avoid the two classic failure modes:
  - **wrong names** → fixed with the `initial_prompt` above;
  - **runaway repetition on music/silence** (`نه نه نه…`, `…`) → suppressed with
    `condition_on_previous_text=False`, a temperature fallback ladder,
    `no_speech_threshold`, and voice-activity detection (VAD).
- On startup the script makes the bundled CUDA libraries visible: on Linux via
  `LD_LIBRARY_PATH` + a one-time re-exec, on Windows via `os.add_dll_directory`.
  You don't need a system CUDA install.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Library libcublas.so.12 is not found` | Re-run `./setup.sh`. The script sets the library path itself; make sure you launch via `./run.sh`. |
| `cublas64_12.dll` / `cudnn*.dll` not found (Windows) | Re-run `setup.bat` and update the NVIDIA driver. To get going anyway, use `run.bat file.m4a -d cpu`. |
| Persian text shows as `???` in the Windows console | Only the console display is affected; the `.txt` file is fine (UTF-8). Windows Terminal shows it correctly. |
| Process dies mid-run inside a sandbox / IDE agent | Some sandboxes kill sustained GPU compute. Run it in a normal terminal. |
| Out of GPU memory | The script auto-falls back to `int8_float16`, then CPU. You can also edit the fallback list in `transcribe.py`. |
| Garbled names | Pass them with `-p` / `-f` (see above). |

---

## Project layout

```
transcribe.py        the transcription CLI (run with -h)
run.sh / run.bat     launchers for Linux / Windows
run-gui.sh / .bat    open the desktop app
setup.sh / setup.bat one-time venv + dependency install
booktranscriber/     engine shared by the CLI and the desktop app (gui/ = the app's screens)
  llm_catalog.py       which AI helper model and llama.cpp build fit this computer
  llm_sources.py       where the helper's files come from; safe unpacking
  llm_server.py        runs llama-server: load progress, CPU fallback, no orphans
  local_fix.py         fixes a transcript in small numbered chunks via llama-server
  gui/local_view.py    the "Fix it here" screen
prompts/             example prompt files (one per book/session)
requirements.txt     pinned dependencies (CLI)
requirements-gui.txt   + desktop app
requirements-dev.txt   + tests (run: venv/bin/python -m pytest)
tests/               automated tests
venv/                local Python env            (created by you, gitignored)
models/              faster-whisper large-v3     (auto-downloaded, gitignored)
```

---

## Privacy

Everything runs on your machine. Transcripts and audio are gitignored so you can't
accidentally commit private session data.

## License

MIT — do whatever you like.
