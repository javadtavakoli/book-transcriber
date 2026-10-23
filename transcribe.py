#!/usr/bin/env python3
"""
Local audio transcription for book-club sessions (faster-whisper, large-v3, GPU).

Self-contained project: the venv lives in ./venv and the model in ./models, so this
does NOT depend on ~/.cache and survives cache-cleaning tools.

Usage (run with -h for all options):
    ./run.sh session.m4a                          # Linux/macOS
    run.bat  session.m4a                          # Windows (or drag a file onto run.bat)
    ./run.sh session.m4a -o out.txt --prompt-file prompts/my-book.txt --timestamps
Seeding the prompt with the book/author/character names is the single biggest fix
for garbled proper nouns.
"""
import os, sys, time, argparse, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
WINDOWS = sys.platform == "win32"

# --- Make bundled CUDA libs (nvidia-* pip wheels) discoverable. --------------
def _nvidia_libdirs():
    spec = importlib.util.find_spec("nvidia")
    roots = list(spec.submodule_search_locations) if spec else []
    sub = "bin" if WINDOWS else "lib"   # wheels put DLLs in bin/, .so files in lib/
    return [os.path.join(r, pkg, sub) for r in roots
            for pkg in ("cudnn", "cublas", "cuda_nvrtc", "cuda_runtime")
            if os.path.isdir(os.path.join(r, pkg, sub))]

libdirs = _nvidia_libdirs()
if WINDOWS:
    # Windows: register the DLL dirs in-process (no re-exec; execv on Windows
    # spawns a detached child and breaks the console / .bat).
    for d in libdirs:
        os.add_dll_directory(d)
    os.environ["PATH"] = os.pathsep.join(libdirs + [os.environ.get("PATH", "")])
elif os.environ.get("_WHISPER_REEXEC") != "1" and libdirs:
    # Linux: LD_LIBRARY_PATH is only read at process startup, so inject it and
    # re-exec ourselves once (guarded by a sentinel env var).
    cur = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = ":".join(libdirs + ([cur] if cur else []))
    os.environ["_WHISPER_REEXEC"] = "1"
    os.execv(sys.executable, [sys.executable] + sys.argv)

# Persian text/paths must not crash a cp1252/cp437 Windows console.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# --- Config -----------------------------------------------------------------
MODELS_DIR = os.path.join(HERE, "models")     # local, cache-independent model store
PROG       = os.path.join(HERE, ".transcribe_progress.txt")
DEFAULT_PROMPT = "جلسهٔ کتاب‌خوانی به زبان فارسی."

def parse_args():
    p = argparse.ArgumentParser(
        prog="transcribe",
        description="Transcribe recordings locally with faster-whisper (offline, on your GPU).")
    p.add_argument("audio", nargs="*", help="audio file(s) to transcribe (.wav, .m4a, .mp3, ...)")
    p.add_argument("-o", "--output", help="output .txt path (only with a single input; "
                   "default: '<audio name> - متن خام.txt' next to the audio)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("-p", "--prompt", help="proper nouns / context to seed the model with "
                   "(book title, author, characters...). Env: WHISPER_PROMPT")
    g.add_argument("-f", "--prompt-file", help="read the prompt from a UTF-8 text file")
    p.add_argument("-l", "--language", default="fa", help="language code (default: fa; e.g. en, ar)")
    p.add_argument("-t", "--timestamps", action="store_true",
                   help="prefix each line with [h:mm:ss]. Env: TIMESTAMPS=1")
    p.add_argument("-m", "--model", default="large-v3", help="Whisper model (default: large-v3)")
    p.add_argument("-d", "--device", choices=("auto", "cuda", "cpu"), default="auto",
                   help="where to run (default: auto = GPU if possible, else CPU)")
    a = p.parse_args()

    if not a.audio:
        # No arguments (e.g. double-clicked run.bat): ask instead of failing.
        try:
            path = input("Audio file to transcribe (you can drag it here): ").strip().strip('"\'')
        except EOFError:
            path = ""
        if not path:
            p.error("no audio file given")
        a.audio = [path]
    if a.output and len(a.audio) > 1:
        p.error("--output can only be used with a single audio file")
    for f in a.audio:
        if not os.path.isfile(f):
            p.error(f"file not found: {f}")

    if a.prompt_file:
        with open(a.prompt_file, encoding="utf-8-sig") as fh:   # -sig: drop Notepad BOM
            a.prompt = fh.read().strip()
    elif not a.prompt:
        a.prompt = os.environ.get("WHISPER_PROMPT") or (DEFAULT_PROMPT if a.language == "fa" else None)
    a.timestamps = a.timestamps or os.environ.get("TIMESTAMPS") == "1"
    return a

def log(msg):
    print(msg, flush=True)
    with open(PROG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def output_path(audio, explicit):
    if explicit:
        return explicit
    base = os.path.splitext(os.path.basename(audio))[0]
    return os.path.join(os.path.dirname(os.path.abspath(audio)), base + " - متن خام.txt")

def load_model(name, device):
    from faster_whisper import WhisperModel
    backends = [("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")]
    if device != "auto":
        backends = [b for b in backends if b[0] == device]
    for dev, compute in backends:
        try:
            log(f"loading {name} on {dev}/{compute} ...")
            model = WhisperModel(name, device=dev, compute_type=compute, download_root=MODELS_DIR)
            log(f"loaded on {dev}/{compute}")
            return model
        except Exception as e:
            log(f"failed {dev}/{compute}: {e}")
    log("could not load model on any backend"); sys.exit(1)

def transcribe(model, audio, out, a):
    segments, info = model.transcribe(
        audio,
        language=a.language,
        beam_size=5,
        initial_prompt=a.prompt,            # seed proper nouns
        condition_on_previous_text=False,   # stop runaway "نه نه نه…" / "…" loops
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],  # fallback when a chunk looks bad
        compression_ratio_threshold=2.4,    # reject over-repetitive output
        no_speech_threshold=0.6,            # drop silent/music chunks
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )
    total = info.duration
    log(f"audio: {audio}")
    log(f"audio duration: {total:.0f}s ({total/60:.1f} min)")

    start = time.time(); n = 0
    with open(out, "w", encoding="utf-8") as f:
        for seg in segments:
            n += 1
            if a.timestamps:
                m, sec = divmod(int(seg.start), 60); h, m = divmod(m, 60)
                f.write(f"[{h:d}:{m:02d}:{sec:02d}] ")
            f.write(seg.text.strip() + "\n"); f.flush()
            if n % 25 == 0:
                pct = 100 * seg.end / total if total else 0
                el = time.time() - start
                rate = seg.end / el if el else 0
                eta = (total - seg.end) / rate if rate else 0
                log(f"{pct:5.1f}%  seg#{n}  t={seg.end:6.0f}s/{total:.0f}s  elapsed={el:.0f}s  eta={eta:.0f}s")

    log(f"DONE  segments={n}  elapsed={time.time()-start:.0f}s")
    log(f"written to {out}")

def main():
    a = parse_args()

    import faulthandler, traceback
    fh = open(os.path.join(HERE, ".transcribe_fault.txt"), "w")
    faulthandler.enable(fh, all_threads=True)
    open(PROG, "w", encoding="utf-8").close()

    model = load_model(a.model, a.device)
    for i, audio in enumerate(a.audio, 1):
        if len(a.audio) > 1:
            log(f"=== [{i}/{len(a.audio)}] ===")
        try:
            transcribe(model, audio, output_path(audio, a.output), a)
        except Exception:
            log("PYTHON EXCEPTION:\n" + traceback.format_exc())
            raise

if __name__ == "__main__":
    main()
