#!/usr/bin/env python3
"""
Local Persian audio transcription for book-club sessions (faster-whisper, large-v3, GPU).

Self-contained project: the venv lives in ./venv and the model in ./models, so this
does NOT depend on ~/.cache and survives cache-cleaning tools.

Usage:
    ./run.sh "/path/to/session.m4a"                      # OUT auto-derived next to it
    ./run.sh "/path/to/session.m4a" "/path/to/out.txt"   # explicit output
Edit PROMPT below each session with the book/author/character names — it is the
single biggest fix for garbled proper nouns.
"""
import os, sys, site, time

HERE = os.path.dirname(os.path.abspath(__file__))

# --- Make bundled CUDA libs discoverable BY THE DYNAMIC LINKER. -------------
# LD_LIBRARY_PATH is only read at process startup, so if it isn't already set
# we inject it and re-exec ourselves once (guarded by a sentinel env var).
sp = site.getsitepackages()[0]
libdirs = [os.path.join(sp, s) for s in
           ("nvidia/cudnn/lib", "nvidia/cublas/lib", "nvidia/cuda_nvrtc/lib",
            "nvidia/cuda_runtime/lib")
           if os.path.isdir(os.path.join(sp, s))]

if os.environ.get("_WHISPER_REEXEC") != "1" and libdirs:
    cur = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = ":".join(libdirs + ([cur] if cur else []))
    os.environ["_WHISPER_REEXEC"] = "1"
    os.execv(sys.executable, [sys.executable] + sys.argv)

# --- Config -----------------------------------------------------------------
MODEL      = "large-v3"                       # best general Whisper model
MODELS_DIR = os.path.join(HERE, "models")     # local, cache-independent model store
PROG       = os.path.join(HERE, ".transcribe_progress.txt")

# Audio/output come from the command line (fall back to a default for quick runs).
AUDIO = sys.argv[1] if len(sys.argv) > 1 else \
        "/home/javad/Documents/جلسه اول کتاب تعقیب هومر .m4a"
if len(sys.argv) > 2:
    OUT = sys.argv[2]
else:
    base = os.path.splitext(os.path.basename(AUDIO))[0]
    OUT = os.path.join(os.path.dirname(AUDIO), base + " - متن خام.txt")

# EDIT THIS EACH SESSION: seed Whisper with the correct proper nouns (book title,
# author, characters, thinkers). Biggest single fix for garbled names.
PROMPT = ("جلسهٔ کتاب‌خوانی به زبان فارسی. کتاب: تعقیب هومر، نوشتهٔ لاسلو کراسناهورکای. "
          "همچنین: دست آخر اثر ساموئل بکت، جاودانگی اثر میلان کوندرا، اودیسه، هومر، "
          "کالیپسو، پنه‌لوپه، کافکا، نیچه، برادران کارامازوف، جنگ و صلح، بلا تار، تانگوی شیطان.")

import faulthandler
_fh = open(os.path.join(HERE, ".transcribe_fault.txt"), "w")
faulthandler.enable(_fh, all_threads=True)

from faster_whisper import WhisperModel

def log(msg):
    print(msg, flush=True)
    with open(PROG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

open(PROG, "w").close()

# diagnostic: linker env + can we load cublas?
import ctypes
_ld = os.environ.get("LD_LIBRARY_PATH", "")
try:
    ctypes.CDLL("libcublas.so.12"); _cub = "ctypes cublas OK"
except OSError as e:
    _cub = "ctypes cublas FAIL: " + str(e)[:100]
log("reexec=" + os.environ.get("_WHISPER_REEXEC", "?") + " libdirs=" + str(len(libdirs)))
log("model_dir=" + MODELS_DIR + "  audio=" + AUDIO)
log("LD=" + _ld[:200]); log(_cub)

model = None
for device, compute in [("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")]:
    try:
        log(f"loading {MODEL} on {device}/{compute} ...")
        model = WhisperModel(MODEL, device=device, compute_type=compute, download_root=MODELS_DIR)
        log(f"loaded on {device}/{compute}")
        break
    except Exception as e:
        log(f"failed {device}/{compute}: {e}")
if model is None:
    log("could not load model on any backend"); sys.exit(1)

import traceback
try:
    segments, info = model.transcribe(
        AUDIO,
        language="fa",
        beam_size=5,
        initial_prompt=PROMPT,              # seed proper nouns
        condition_on_previous_text=False,   # stop runaway "نه نه نه…" / "…" loops
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],  # fallback when a chunk looks bad
        compression_ratio_threshold=2.4,    # reject over-repetitive output
        no_speech_threshold=0.6,            # drop silent/music chunks
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )
    total = info.duration
    log(f"audio duration: {total:.0f}s ({total/60:.1f} min)")

    start = time.time(); n = 0
    with open(OUT, "w", encoding="utf-8") as f:
        for seg in segments:
            n += 1
            f.write(seg.text.strip() + "\n"); f.flush()
            if n % 25 == 0:
                pct = 100 * seg.end / total if total else 0
                el = time.time() - start
                rate = seg.end / el if el else 0
                eta = (total - seg.end) / rate if rate else 0
                log(f"{pct:5.1f}%  seg#{n}  t={seg.end:6.0f}s/{total:.0f}s  elapsed={el:.0f}s  eta={eta:.0f}s")

    log(f"DONE  segments={n}  elapsed={time.time()-start:.0f}s")
    log(f"written to {OUT}")
except Exception:
    log("PYTHON EXCEPTION:\n" + traceback.format_exc())
    raise
