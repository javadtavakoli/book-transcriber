# book-transcriber

Local, offline Persian transcription for book-club recordings.
Runs **faster-whisper `large-v3`** on the GPU. Nothing is uploaded anywhere.

Self-contained — the Python environment (`venv/`) and the model (`models/`) live
inside this folder, so it is **independent of `~/.cache`** and survives cache-cleaning.

## Usage

```bash
cd ~/Projects/book-transcriber
./run.sh "/home/javad/Documents/<recording>.m4a"
```

Output goes to `<recording> - متن خام.txt` next to the audio (or pass a second
argument for an explicit path). Progress is written live to
`.transcribe_progress.txt`.

A ~90-minute recording takes roughly 20–25 minutes on the RTX 4050.

## Each session: edit the prompt

Open `transcribe.py` and update `PROMPT` with the book title, author, characters
and any thinkers likely to be named. Whisper uses it to spell proper nouns
correctly — it's the single biggest quality win.

## Layout

```
transcribe.py   the script (CUDA lib re-exec + tuned decoding)
run.sh          wrapper: venv/bin/python transcribe.py "$@"
venv/           Python env (faster-whisper + bundled CUDA libs)
models/         faster-whisper large-v3 (~2.9 GB)
```

## Notes / gotchas

- **Run un-sandboxed** for the real decode — a sandbox kills sustained GPU compute
  with signal 16.
- Prefer **WAV** if available; `.m4a` also works (decoded via PyAV/ffmpeg).
- The pip wheel cache stays in `~/.cache/pip` (build-time only); deleting it just
  means a slower rebuild if the venv is ever recreated, never a failed run.
