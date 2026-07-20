# book-transcriber

Turn long spoken-word recordings (book-club sessions, lectures, interviews) into
plain-text transcripts — **locally and offline**, on your own GPU. Nothing is ever
uploaded to a cloud service.

Built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with OpenAI's
**`large-v3`** model. Tuned for **Persian (فارسی)** by default, but works for any
language Whisper supports by changing one line.

- 🔒 **Private** — audio never leaves your machine
- ⚡ **Fast** — a ~90-minute recording transcribes in ~20–25 min on a laptop RTX 4050
- 🎯 **Accurate names** — seed the model with a session's proper nouns to fix the
  usual garbling of book titles, authors, and characters
- 🧱 **Self-contained** — the Python environment and the model live inside the
  project folder, so it doesn't depend on (and isn't wiped by) `~/.cache`

---

## Requirements

- **Linux** (tested on Ubuntu 24.04)
- **NVIDIA GPU** with recent drivers (CPU-only also works but is much slower)
- **Python 3.10+** (tested on 3.12)
- **ffmpeg** — for decoding audio: `sudo apt install ffmpeg`

No system-wide CUDA toolkit is needed — the required CUDA libraries are installed
as Python wheels (see `requirements.txt`).

---

## Setup (one time)

```bash
git clone https://github.com/javadtavakoli/book-transcriber.git
cd book-transcriber

# create the local virtual environment
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

The **model (~2.9 GB) downloads automatically on the first run** into `./models/`
and is reused offline afterwards. The first run therefore takes longer; every run
after that is fully offline.

> `venv/` and `models/` are intentionally **not** in git (they're multi-gigabyte).
> That's why you create them locally here.

---

## Usage

```bash
./run.sh "/path/to/recording.m4a"
```

- The transcript is written next to the audio as `recording - متن خام.txt`.
- Pass a second argument to choose the output path:
  ```bash
  ./run.sh "/path/to/recording.m4a" "/path/to/transcript.txt"
  ```
- Progress is printed live and also written to `.transcribe_progress.txt`:
  ```
  loading large-v3 on cuda/float16 ...
  loaded on cuda/float16
  audio duration: 5447s (90.8 min)
   25.8%  seg#500  t=  1405s/5447s  elapsed=403s  eta=1160s
  ...
  DONE  segments=1982  elapsed=1423s
  ```

Both `.wav` and `.m4a` (and anything ffmpeg reads) work. **WAV is preferred** when
you have the choice.

### Run in the background

For long recordings, detach it so it keeps running:

```bash
nohup ./run.sh "/path/to/recording.wav" > run.log 2>&1 &
tail -f .transcribe_progress.txt
```

---

## Configure it for each session

Open **`transcribe.py`** and edit the two things at the top:

**1. `PROMPT`** — the single biggest quality win. List the proper nouns you expect
to hear (book title, author, characters, thinkers). Whisper uses it to spell names
correctly instead of guessing.

```python
PROMPT = ("جلسهٔ کتاب‌خوانی به زبان فارسی. کتاب: تعقیب هومر، نوشتهٔ لاسلو کراسناهورکای. "
          "همچنین: دست آخر اثر ساموئل بکت، اودیسه، هومر، کالیپسو، کافکا، نیچه.")
```

**2. Language** (only if not Persian) — change `language="fa"` in the
`model.transcribe(...)` call to your language code (`"en"`, `"ar"`, …).

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
- On startup the script makes the bundled CUDA libraries visible to the dynamic
  linker (via `LD_LIBRARY_PATH` + a one-time re-exec), so you don't need a
  system CUDA install.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Library libcublas.so.12 is not found` | Reinstall deps: `venv/bin/pip install -r requirements.txt`. The script sets the library path itself; make sure you launch via `./run.sh`. |
| Process dies mid-run inside a sandbox / IDE agent | Some sandboxes kill sustained GPU compute. Run it in a normal terminal. |
| Out of GPU memory | The script auto-falls back to `int8_float16`, then CPU. You can also edit the fallback list in `transcribe.py`. |
| `ffmpeg not found` | `sudo apt install ffmpeg`. |
| Garbled names | Add them to `PROMPT`. |

---

## Project layout

```
transcribe.py        the transcription script (edit PROMPT here)
run.sh               wrapper: venv/bin/python transcribe.py "$@"
requirements.txt     pinned dependencies
venv/                local Python env            (created by you, gitignored)
models/              faster-whisper large-v3     (auto-downloaded, gitignored)
```

---

## Privacy

Everything runs on your machine. Transcripts and audio are gitignored so you can't
accidentally commit private session data.

## License

MIT — do whatever you like.
