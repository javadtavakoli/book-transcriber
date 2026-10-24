"""Transcription engine shared by the CLI and the GUI worker.

No import-time side effects: faster_whisper is only imported inside load_model(),
and GPU library paths are the caller's job (see gpu.py).
"""
import os
from dataclasses import dataclass
from typing import Callable, Iterator

RAW_SUFFIX = " - متن خام.txt"
CORRECTED_SUFFIX = " - متن اصلاح‌شده.txt"
DEFAULT_PROMPT_FA = "جلسهٔ کتاب‌خوانی به زبان فارسی."

# Tuned against the two classic failure modes: wrong names (fixed via the prompt)
# and runaway repetition on music/silence ("نه نه نه…").
DECODE_PARAMS = dict(
    beam_size=5,
    condition_on_previous_text=False,   # stop runaway "نه نه نه…" / "…" loops
    temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],  # fallback when a chunk looks bad
    compression_ratio_threshold=2.4,    # reject over-repetitive output
    no_speech_threshold=0.6,            # drop silent/music chunks
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=500),
)

BACKENDS = [("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")]


class ModelLoadError(RuntimeError):
    pass


@dataclass
class TranscribeOptions:
    language: str = "fa"
    prompt: str | None = None
    timestamps: bool = False


@dataclass
class Segment:
    start: float
    end: float
    text: str


def output_path(audio: str, explicit: str | None = None, suffix: str = RAW_SUFFIX) -> str:
    if explicit:
        return explicit
    base = os.path.splitext(os.path.basename(audio))[0]
    return os.path.join(os.path.dirname(os.path.abspath(audio)), base + suffix)


def corrected_path_for(raw_path: str) -> str:
    folder, name = os.path.split(raw_path)
    if name.endswith(RAW_SUFFIX):
        stem = name[: -len(RAW_SUFFIX)]
    else:
        stem = os.path.splitext(name)[0]
    return os.path.join(folder, stem + CORRECTED_SUFFIX)


def format_timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"[{h:d}:{m:02d}:{s:02d}]"


def format_line(seg: Segment, timestamps: bool) -> str:
    text = seg.text.strip()
    return f"{format_timestamp(seg.start)} {text}" if timestamps else text


def local_model_ref(name_or_path: str) -> str:
    """A local model folder becomes its bare (always ASCII) name, with the working directory set to its parent.

    CTranslate2 opens the model with a narrow string on Windows, so a Persian user name or downloads
    folder in the path would break the load. Model names ("large-v3") are returned unchanged.
    Changes the process's working directory: only for the worker child.
    """
    if not os.path.isdir(name_or_path):
        return name_or_path
    path = os.path.abspath(name_or_path)
    os.chdir(os.path.dirname(path))     # Python's chdir takes the wide path
    return os.path.basename(path)


def load_model(name_or_path: str, device: str, download_root: str | None,
               log: Callable[[str], None]):
    """Try GPU fp16, GPU int8, then CPU. Returns (model, "device/compute")."""
    from faster_whisper import WhisperModel
    backends = BACKENDS if device == "auto" else [b for b in BACKENDS if b[0] == device]
    for dev, compute in backends:
        try:
            log(f"loading {name_or_path} on {dev}/{compute} ...")
            model = WhisperModel(name_or_path, device=dev, compute_type=compute,
                                 download_root=download_root)
            log(f"loaded on {dev}/{compute}")
            return model, f"{dev}/{compute}"
        except Exception as e:
            log(f"failed {dev}/{compute}: {e}")
    raise ModelLoadError("could not load model on any backend")


def transcribe(model, audio, opts: TranscribeOptions, **overrides) -> tuple[Iterator[Segment], float]:
    """Returns a lazy segment iterator and the audio duration in seconds."""
    params = {**DECODE_PARAMS, **overrides}
    segments, info = model.transcribe(audio, language=opts.language,
                                      initial_prompt=opts.prompt, **params)
    return (Segment(s.start, s.end, s.text) for s in segments), info.duration
