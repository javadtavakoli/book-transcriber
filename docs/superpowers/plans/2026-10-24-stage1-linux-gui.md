# Stage 1 — Linux GUI (setup, transcribe, export-for-AI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A PySide6 desktop app, run from source on Ubuntu, that does first-run setup with live download progress, then drop recording → optional names → transcribe → export for ChatGPT/Claude/Gemini → paste back → review & save, in Persian or English — while the existing CLI keeps working unchanged.

**Architecture:** Transcription logic moves into a side-effect-free package `booktranscriber/`. `transcribe.py` becomes a thin CLI over it. The GUI never runs Whisper in-process: it spawns a worker child process (`python -m booktranscriber.worker`) that streams JSON-line events; the GPU library path is injected into the child's environment, so nothing re-execs. Setup (system check, resumable downloads of CUDA wheels from PyPI and model files from Hugging Face, self-test) is plain Python driven from a `QThread`. All non-GUI logic is unit-tested; GUI gets offscreen smoke tests.

**Tech Stack:** Python 3.12, faster-whisper 1.2.1 (existing), PySide6, platformdirs, httpx (already present via huggingface_hub), huggingface_hub (present), pytest, pytest-qt.

**Spec:** `docs/superpowers/specs/2026-10-24-desktop-gui-design.md` (stage 1 of §7). Read §4, §5.1, §5.3, §6.1–6.4 before starting.

## Global Constraints

- CLI keeps **identical flags, defaults, output filename `<name> - متن خام.txt`, progress file `.transcribe_progress.txt` and log line formats**; `run.sh`/`run.bat`/`setup.sh`/`setup.bat` keep working.
- Decoding parameters carry over unchanged: `beam_size=5`, `condition_on_previous_text=False`, `temperature=[0.0,0.2,0.4,0.6,0.8,1.0]`, `compression_ratio_threshold=2.4`, `no_speech_threshold=0.6`, `vad_filter=True`, `vad_parameters=dict(min_silence_duration_ms=500)`.
- Modules under `booktranscriber/` have **no import-time side effects** (no `execv`, no `add_dll_directory`, no env mutation).
- Whisper never runs in the GUI process; only in the worker child.
- All app data under `platformdirs.user_data_dir("BookTranscriber", appauthor=False)`, overridable by env `BT_DATA_DIR` (tests use this).
- Corrected transcript filename: `<name> - متن اصلاح‌شده.txt` next to the audio.
- All text files UTF-8; worker stdout is UTF-8 JSON lines with `ensure_ascii=False`.
- UI strings only via `I18n.tr(key)`; every key exists in both `en` and `fa`. Persian UI ⇒ `Qt.RightToLeft`. Transcript views are RTL when transcript language is `fa`, regardless of UI language.
- No technical words on the normal path (no "CUDA", "cuDNN", "model.bin", stack traces) — errors map to friendly `error.*` strings with one obvious action.
- AI-fix rule text (§5.1): fix only misheard words and proper names; never change meaning, style, word order or sentence boundaries; never add, remove, merge or split lines; seed names are authoritative spelling; keep filler words and colloquial speech.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Persian/space-laden paths** (`~/جلسه ۱۲/ضبط شده.m4a`) — worker args, output naming and JSON events round-trip intact (tests in Tasks 1, 2).
2. **Messy AI answers pasted back** — Persian/Arabic-Indic digits (`[۱۲]`), markdown fences, chatter before/after, missing or duplicate numbers, answers for several parts pasted in one go — parse what is recognisable, keep originals for the rest, never crash (tests in Task 7).
3. **Wrong file dropped** — a PDF, a folder, several files, a file that vanished — friendly message before the 3 GB model loads; silent audio → "no speech found", not an empty review (tests in Tasks 2, 11).
4. **Interrupted downloads** — connection drop mid-file resumes; server ignoring `Range` (200 instead of 206) restarts cleanly rather than corrupting; checksum mismatch deletes and reports (tests in Task 5).
5. **Closing the window mid-work** — while transcribing or downloading: confirm dialog, child process killed, `.part` files left only where resume needs them, no orphan worker (test in Task 11).

---

## Owner checkpoints

`<scratch>` = the session's scratchpad directory.

Steps marked **👤 Owner checkpoint** need the owner at the keyboard (GUI interaction, network toggling, long GPU runs). The executing agent finishes all automated steps of the task, commits, lists that task's checkpoint items for the owner, and continues with the next task; nothing in a checkpoint is reported as verified until the owner confirms it.

## File Structure

```
booktranscriber/
  __init__.py          __version__ = "0.1.0"
  __main__.py          `python -m booktranscriber` → GUI; `--worker ...` → worker (frozen-app friendly)
  engine.py            options, decode params, model load, segment iteration, transcript writing, naming
  gpu.py               find NVIDIA lib dirs; build child env; register DLL dirs (Windows, called explicitly)
  protocol.py          worker JSON-line event encode/decode
  worker.py            child-process entry: probe audio, load model, stream events; --selftest
  paths.py             data-dir layout
  settings.py          Settings dataclass + tolerant JSON load/save
  recents.py           recent-transcripts index
  namelists.py         saved name lists, prompt building, import of prompts/*.txt
  syscheck.py          GPU/disk detection, model choice, existing-model discovery
  downloader.py        resumable, verified HTTP download
  setup_sources.py     PyPI CUDA wheels + HF model files → list of RemoteFile; wheel extraction
  setup_runner.py      orchestrates setup items with aggregated progress + self-test
  fixexport.py         line protocol, export parts, parsing answers, guardrails, word diff
  i18n.py              STRINGS (en/fa) + I18n QObject + initial_language()
  gui/
    __init__.py
    app.py             main(argv) -> int
    main_window.py     MainWindow: stacked views, language toggle, close guard
    runners.py         TranscribeRunner (QProcess), SetupRunner (QThread)
    widgets.py         DropArea, ProgressRow, shared styling helpers
    setup_view.py      Welcome / Downloading / Ready / error panels
    home_view.py       drop area + recent list
    flow_view.py       names step, transcribing step, result/fix-choice step
    export_view.py     parts + copy/save + paste-back
    review_view.py     line-aligned table, highlights, per-line revert, save
transcribe.py          thin CLI over booktranscriber.engine (keeps Linux re-exec, now in main path only)
run-gui.sh / run-gui.bat   launchers
requirements-gui.txt   -r requirements.txt + PySide6 + platformdirs (pinned)
requirements-dev.txt   -r requirements-gui.txt + pytest + pytest-qt (pinned)
tests/                 one test module per core module + tests/gui/
```

---

### Task 1: Engine extraction, GPU helpers, thin CLI

**Files:**
- Create: `booktranscriber/__init__.py`, `booktranscriber/engine.py`, `booktranscriber/gpu.py`, `requirements-dev.txt`, `tests/test_engine.py`, `tests/test_gpu.py`, `tests/conftest.py`
- Modify: `transcribe.py` (whole file)

**Interfaces:**
- Produces (`engine.py`):
  - `RAW_SUFFIX = " - متن خام.txt"`, `CORRECTED_SUFFIX = " - متن اصلاح‌شده.txt"`, `DEFAULT_PROMPT_FA = "جلسهٔ کتاب‌خوانی به زبان فارسی."`
  - `DECODE_PARAMS: dict` — exactly the Global Constraints values (excluding `language`/`initial_prompt`).
  - `@dataclass TranscribeOptions(language: str = "fa", prompt: str | None = None, timestamps: bool = False)`
  - `@dataclass Segment(start: float, end: float, text: str)`
  - `output_path(audio: str, explicit: str | None = None, suffix: str = RAW_SUFFIX) -> str`
  - `corrected_path_for(raw_path: str) -> str` — same folder as the raw file; replaces a trailing `RAW_SUFFIX` with `CORRECTED_SUFFIX`, else `<stem> + CORRECTED_SUFFIX`.
  - `format_timestamp(seconds: float) -> str` → `"[h:mm:ss]"`
  - `format_line(seg: Segment, timestamps: bool) -> str` → `"[0:01:05] text"` or `"text"` (stripped, no newline)
  - `load_model(name_or_path: str, device: str, download_root: str | None, log: Callable[[str], None]) -> tuple[WhisperModel, str]` — same backend ladder as today `[("cuda","float16"),("cuda","int8_float16"),("cpu","int8")]`, filtered by device; returns `(model, "cuda/float16")`; raises `ModelLoadError` if all fail (no `sys.exit`).
  - `transcribe(model, audio: str, opts: TranscribeOptions) -> tuple[Iterator[Segment], float]` — (segments, duration seconds).
- Produces (`gpu.py`):
  - `CUDA_PACKAGES = ("cudnn", "cublas", "cuda_nvrtc", "cuda_runtime")`
  - `site_nvidia_roots() -> list[str]` (via `importlib.util.find_spec("nvidia")`)
  - `nvidia_lib_dirs(roots: list[str], windows: bool) -> list[str]` — `<root>/<pkg>/{bin|lib}` that exist.
  - `gpu_env(lib_dirs: list[str], base: Mapping[str, str], windows: bool) -> dict[str, str]` — Linux: prepend to `LD_LIBRARY_PATH`; Windows: prepend to `PATH` and set `BT_DLL_DIRS` (os.pathsep-joined).
  - `register_dll_dirs_from_env() -> None` — Windows only, `os.add_dll_directory` for each `BT_DLL_DIRS` entry; no-op elsewhere.

- [ ] **Step 1: Dev requirements.** Create `requirements-dev.txt` containing `-r requirements.txt`, `pytest`, then `venv/bin/python -m pip install -r requirements-dev.txt` and pin the installed pytest version in the file (`pytest==X.Y.Z`). Create `tests/conftest.py` with an autouse fixture setting `BT_DATA_DIR` to `tmp_path / "data"`.

- [ ] **Step 2: Write failing tests** in `tests/test_engine.py` and `tests/test_gpu.py`:

```python
def test_output_path_default_next_to_audio(tmp_path):
    audio = tmp_path / "جلسه ۱۲" / "ضبط شده.m4a"
    assert output_path(str(audio)) == str(tmp_path / "جلسه ۱۲" / "ضبط شده - متن خام.txt")

def test_output_path_corrected_suffix(tmp_path):
    assert output_path(str(tmp_path / "a.wav"), suffix=CORRECTED_SUFFIX).endswith("a - متن اصلاح‌شده.txt")

def test_corrected_path_follows_raw_location():
    assert corrected_path_for("/docs/جلسه - متن خام.txt") == "/docs/جلسه - متن اصلاح‌شده.txt"
    assert corrected_path_for("/docs/notes.txt") == "/docs/notes - متن اصلاح‌شده.txt"

def test_output_path_explicit_wins():
    assert output_path("/x/a.wav", "/y/out.txt") == "/y/out.txt"

def test_format_timestamp():
    assert format_timestamp(0) == "[0:00:00]"
    assert format_timestamp(65.9) == "[0:01:05]"
    assert format_timestamp(3725) == "[1:02:05]"

def test_format_line():
    s = Segment(65.0, 70.0, "  سلام  ")
    assert format_line(s, False) == "سلام"
    assert format_line(s, True) == "[0:01:05] سلام"

def test_decode_params_unchanged():
    assert DECODE_PARAMS == dict(beam_size=5, condition_on_previous_text=False,
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0], compression_ratio_threshold=2.4,
        no_speech_threshold=0.6, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500))

def test_import_has_no_side_effects(monkeypatch):
    monkeypatch.setattr(os, "execv", lambda *a: pytest.fail("execv at import"))
    importlib.reload(booktranscriber.engine); importlib.reload(booktranscriber.gpu)

# test_gpu.py
def test_nvidia_lib_dirs_linux(tmp_path):
    (tmp_path / "cublas" / "lib").mkdir(parents=True); (tmp_path / "cudnn" / "lib").mkdir(parents=True)
    assert nvidia_lib_dirs([str(tmp_path)], windows=False) == [str(tmp_path/"cudnn"/"lib"), str(tmp_path/"cublas"/"lib")]

def test_nvidia_lib_dirs_windows_uses_bin(tmp_path):
    (tmp_path / "cublas" / "bin").mkdir(parents=True)
    assert nvidia_lib_dirs([str(tmp_path)], windows=True) == [str(tmp_path/"cublas"/"bin")]

def test_gpu_env_linux_prepends():
    env = gpu_env(["/a", "/b"], {"LD_LIBRARY_PATH": "/old"}, windows=False)
    assert env["LD_LIBRARY_PATH"] == "/a:/b:/old"

def test_gpu_env_windows():
    env = gpu_env(["C:\\a"], {"PATH": "C:\\w"}, windows=True)
    assert env["PATH"].startswith("C:\\a") and env["BT_DLL_DIRS"] == "C:\\a"
```

- [ ] **Step 3: Run** `venv/bin/python -m pytest tests/test_engine.py tests/test_gpu.py -v` — Expected: FAIL (ImportError).

- [ ] **Step 4: Implement** `engine.py` and `gpu.py` per Interfaces. `faster_whisper` is imported inside `load_model` only (keeps import cheap). Use `os.pathsep`-independent joins in `gpu_env` (`":"` for Linux, `";"` for Windows) so tests pass on any host.

- [ ] **Step 5: Rewrite `transcribe.py`** as a thin CLI: same `parse_args` (unchanged text and flags), same `log()`/progress file, same `"loading … / loaded on … / audio: / audio duration: / pct seg# … / DONE / written to"` lines. In `main()` (not at module top), before importing the engine's model loader: on Linux, if `_WHISPER_REEXEC != "1"` and lib dirs exist (from `site_nvidia_roots()` plus `paths.gpu_dir()/"nvidia"` once Task 3 exists — for now site roots only), set env via `gpu_env` and `os.execv` once (current behaviour); on Windows, set env and call `register_dll_dirs_from_env()`. Keep the utf-8 stdout reconfigure and the faulthandler setup. On `ModelLoadError`, `log("could not load model on any backend")` and exit 1 (as today).

- [ ] **Step 6: Run tests** — Expected: PASS.

- [ ] **Step 7: Real-GPU regression check.** Make a 60-second clip: `venv/bin/python -c "import av"` is available; use `ffmpeg` if installed, else PyAV: write a small script in the scratchpad that copies the first 60 s of `~/Downloads/577e5c4b_28.m4a` to `<scratch>/clip.wav`. Run `./run.sh /path/clip.wav -t` and check: log shows `loaded on cuda/float16`, output file `clip - متن خام.txt` exists with `[0:00:..]` lines. Run `./run.sh -h` and diff against `git show HEAD:transcribe.py`-era help (identical options).

- [ ] **Step 8: Commit** — `git add booktranscriber tests transcribe.py requirements-dev.txt && git commit -m "Extract side-effect-free engine package; thin CLI over it"`

---

### Task 2: Worker process and event protocol

**Files:**
- Create: `booktranscriber/protocol.py`, `booktranscriber/worker.py`, `booktranscriber/__main__.py`, `tests/test_protocol.py`, `tests/test_worker.py`

**Interfaces:**
- Consumes: `engine.load_model`, `engine.transcribe`, `engine.format_line`, `engine.TranscribeOptions`, `gpu.register_dll_dirs_from_env`.
- Produces (`protocol.py`): `encode(event: dict) -> str` (one line, `ensure_ascii=False`, no newline); `decode(line: str) -> dict | None` (None for blank/non-JSON/no `"type"`).
- Event shapes (all `type` values the GUI handles):
  - `{"type":"loaded","backend":"cuda/float16"}`
  - `{"type":"duration","seconds":5447.0}`
  - `{"type":"segment","start":1.2,"end":4.0,"text":"..."}`
  - `{"type":"progress","done":1405.0,"total":5447.0,"eta":1160.0}` (at most once per second)
  - `{"type":"done","out":"/path/x - متن خام.txt","segments":1982}`
  - `{"type":"error","kind":K,"message":"..."}` with `K ∈ {"not_found","bad_audio","model","write","unknown"}`
- Produces (`worker.py`):
  - CLI: `--audio PATH --out PATH --model NAME_OR_PATH [--download-root DIR] [--language fa] [--prompt TEXT] [--device auto|cuda|cpu] [--timestamps]`, or `--selftest --model … [--device …]`.
  - `probe_audio(path: str) -> float` — opens with `av.open`, returns duration seconds; raises `BadAudio` for missing audio stream / decode error; `FileNotFoundError` passthrough.
  - `run(argv: list[str], emit: Callable[[dict], None], loader=engine.load_model) -> int` — exit 0 on done, 1 on error (after emitting an `error` event).
  - Writes to `out + ".part"` and `os.replace` to `out` on success; on any failure the `.part` is removed.
  - `--selftest`: load model, transcribe 2 s of low-level noise (`numpy.random.default_rng(0).normal(0, 0.01, 32000).astype(float32)`) **with `vad_filter=False`** and **fully consume** the segment generator (so the encoder and CUDA kernels really run), emit `loaded` then `done` with `out=""`, `segments=N`.
  - `worker_command(args: list[str]) -> list[str]` — `[sys.executable, "-m", "booktranscriber.worker", *args]`, or `[sys.executable, "--worker", *args]` when `getattr(sys, "frozen", False)`.
- `__main__.py`: `--worker` as first arg → `worker.main(rest)`; otherwise `gui.app.main(sys.argv)`.

- [ ] **Step 1: Write failing tests**

```python
# test_protocol.py
def test_roundtrip_persian():
    ev = {"type": "segment", "start": 1.0, "end": 2.0, "text": "تعقیب هومر"}
    line = encode(ev); assert "\n" not in line and "تعقیب" in line
    assert decode(line) == ev
@pytest.mark.parametrize("junk", ["", "   ", "warning: something", "[1,2]", '{"no_type": 1}'])
def test_decode_ignores_junk(junk): assert decode(junk) is None

# test_worker.py
def test_missing_file_emits_not_found(tmp_path):
    events = []; rc = run(["--audio", str(tmp_path/"nope.m4a"), "--out", str(tmp_path/"o.txt"), "--model", "x"], events.append,
                          loader=lambda *a, **k: pytest.fail("model must not load"))
    assert rc == 1 and events[-1]["type"] == "error" and events[-1]["kind"] == "not_found"

def test_non_audio_file_emits_bad_audio_before_model_load(tmp_path):
    pdf = tmp_path / "book.pdf"; pdf.write_bytes(b"%PDF-1.4 not audio")
    events = []; rc = run(["--audio", str(pdf), "--out", str(tmp_path/"o.txt"), "--model", "x"], events.append,
                          loader=lambda *a, **k: pytest.fail("model must not load"))
    assert rc == 1 and events[-1]["kind"] == "bad_audio"

def test_success_writes_atomically(tmp_path, wav_file, fake_loader):
    # fake_loader returns (FakeModel, "cpu/int8"); FakeModel.transcribe yields two segments, duration 4.0
    out = tmp_path / "ضبط - متن خام.txt"; events = []
    assert run(["--audio", str(wav_file), "--out", str(out), "--model", "x", "--timestamps"], events.append, loader=fake_loader) == 0
    assert out.read_text("utf-8") == "[0:00:00] سلام\n[0:00:02] دنیا\n"
    assert not (tmp_path / (out.name + ".part")).exists()
    assert [e["type"] for e in events][0] == "loaded" and events[-1] == {"type": "done", "out": str(out), "segments": 2}

def test_failure_removes_part(tmp_path, wav_file, exploding_loader):
    # model.transcribe raises mid-iteration
    out = tmp_path / "o.txt"; events = []
    assert run([... same args ...], events.append, loader=exploding_loader) == 1
    assert not out.exists() and not (tmp_path / "o.txt.part").exists() and events[-1]["kind"] == "unknown"

def test_cuda_error_mid_stream_is_model_kind(tmp_path, wav_file, cuda_failing_loader):
    # cuda_failing_loader: transcribe yields one segment then raises RuntimeError("Library libcublas.so.12 is not found")
    out = tmp_path / "o.txt"; events = []
    assert run(["--audio", str(wav_file), "--out", str(out), "--model", "x"], events.append, loader=cuda_failing_loader) == 1
    assert events[-1]["kind"] == "model" and not (tmp_path / "o.txt.part").exists()

def test_worker_command_source_mode(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert worker_command(["--selftest"])[1:] == ["-m", "booktranscriber.worker", "--selftest"]
```

`wav_file` fixture (in `tests/conftest.py`): 2 s of 16 kHz silence written with the stdlib `wave` module. `fake_loader`/`exploding_loader` fixtures live in `tests/test_worker.py`; `FakeModel.transcribe(audio, **kw)` returns `(iter(segs), SimpleNamespace(duration=4.0))` with objects having `.start/.end/.text`.

- [ ] **Step 2: Run** `venv/bin/python -m pytest tests/test_protocol.py tests/test_worker.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `protocol.py`, `worker.py`, `__main__.py`. `worker.main(argv)` reconfigures stdout to utf-8, calls `register_dll_dirs_from_env()`, and passes `emit=lambda e: print(encode(e), flush=True)`. `engine.transcribe` is called on the model returned by the loader; `bad_audio` also covers `av.error.InvalidDataError` raised during decode. A `RuntimeError`/`OSError` whose message contains `cublas`, `cudnn`, `cuda` (case-insensitive) — at load **or mid-iteration** — maps to kind `model`. Write lines via `format_line` + `"\n"`, flushing each.
- [ ] **Step 4: Run tests** — Expected: PASS.
- [ ] **Step 5: Real run.** `LD_LIBRARY_PATH=$(venv/bin/python -c "from booktranscriber.gpu import *; print(':'.join(nvidia_lib_dirs(site_nvidia_roots(), False)))") venv/bin/python -m booktranscriber --worker --audio clip.wav --out <scratch>/w.txt --model large-v3 --download-root models` — Expected: JSON lines `loaded` (`cuda/float16`), `duration`, `segment`s, `progress`, `done`. Then `--selftest --model large-v3 --download-root models` — Expected: `done`.
- [ ] **Step 6: Commit** — `git commit -m "Add transcription worker process with JSON-line events"`

---

### Task 3: Data dir, settings, recents, name lists

**Files:**
- Create: `booktranscriber/paths.py`, `booktranscriber/settings.py`, `booktranscriber/recents.py`, `booktranscriber/namelists.py`, `requirements-gui.txt`, tests `tests/test_paths.py`, `tests/test_settings.py`, `tests/test_recents.py`, `tests/test_namelists.py`
- Modify: `requirements-dev.txt` (`-r requirements-gui.txt` instead of `-r requirements.txt`), `transcribe.py` (also search `paths.gpu_dir()/"nvidia"`)

**Interfaces:**
- Produces (`paths.py`, all return `pathlib.Path`, creating dirs on access): `data_dir()`, `models_dir()`, `gpu_dir()`, `namelists_dir()`, `logs_dir()`, `settings_file()`, `recents_file()`. `data_dir()` honours `BT_DATA_DIR`.
- Produces (`settings.py`):
  - `@dataclass Settings(ui_language: str | None = None, setup_done: bool = False, whisper_model: str = "large-v3", whisper_model_path: str | None = None, device: str = "auto", language: str = "fa", timestamps: bool = False)`
  - `load_settings(path: Path) -> Settings` — missing/corrupt/unknown keys → defaults (unknown keys ignored).
  - `save_settings(s: Settings, path: Path) -> None` — atomic (`.tmp` + `os.replace`).
- Produces (`recents.py`): `@dataclass RecentItem(audio: str, raw_path: str, corrected_path: str | None, created: str)`; `load_recents(path) -> list[RecentItem]` (drops entries whose `raw_path` no longer exists); `add_recent(path, item, limit=20) -> list[RecentItem]` (newest first, dedupe by `raw_path`).
- Produces (`namelists.py`):
  - `parse_names(text: str) -> list[str]` — split on newlines, strip, drop empties, dedupe keeping order.
  - `build_prompt(names: list[str], language: str) -> str | None` — `fa`: `DEFAULT_PROMPT_FA + " " + "، ".join(names) + "."`, or `DEFAULT_PROMPT_FA` when empty; other languages: `", ".join(names) + "."` or `None`.
  - `list_lists(d: Path) -> list[str]`, `load_list(d, name) -> list[str]`, `save_list(d, name, names) -> None` (one name per line, filename = name with `/\:*?"<>|` replaced by `_`, `.txt`).
  - `import_prompt_file(path: Path) -> list[str]` — read `utf-8-sig`; split on newline, `،`, `,`, `.`; strip a leading `"…:"` label from each piece; drop pieces equal to `DEFAULT_PROMPT_FA` minus its final period; dedupe.

- [ ] **Step 1: GUI requirements.** Create `requirements-gui.txt` = `-r requirements.txt` + `PySide6` + `platformdirs`; install; pin installed versions. Add `pytest-qt` to `requirements-dev.txt`, install, pin. Make `setup.sh`/`setup.bat` install `requirements-gui.txt` instead of `requirements.txt`.
- [ ] **Step 2: Write failing tests**

```python
def test_data_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("BT_DATA_DIR", str(tmp_path / "d")); assert paths.models_dir() == tmp_path / "d" / "models"

def test_settings_corrupt_file_gives_defaults(tmp_path):
    p = tmp_path / "s.json"; p.write_text("{not json", "utf-8"); assert load_settings(p) == Settings()
def test_settings_roundtrip_and_unknown_keys(tmp_path):
    p = tmp_path / "s.json"; save_settings(Settings(ui_language="fa", setup_done=True), p)
    d = json.loads(p.read_text("utf-8")); d["future_key"] = 1; p.write_text(json.dumps(d), "utf-8")
    assert load_settings(p) == Settings(ui_language="fa", setup_done=True)

def test_recents_dedupe_limit_and_missing(tmp_path):
    raws = [tmp_path / f"{i}.txt" for i in range(3)]; [r.write_text("x") for r in raws]
    f = tmp_path / "recents.json"
    for r in raws + [raws[0]]: add_recent(f, RecentItem("a.m4a", str(r), None, "2026-10-24T10:00:00"), limit=2)
    assert [i.raw_path for i in load_recents(f)] == [str(raws[0]), str(raws[2])]
    raws[0].unlink(); assert [i.raw_path for i in load_recents(f)] == [str(raws[2])]

def test_build_prompt_fa():
    assert build_prompt(["هومر", "تعقیب هومر"], "fa") == "جلسهٔ کتاب‌خوانی به زبان فارسی. هومر، تعقیب هومر."
    assert build_prompt([], "fa") == "جلسهٔ کتاب‌خوانی به زبان فارسی."
    assert build_prompt([], "en") is None and build_prompt(["Homer"], "en") == "Homer."

def test_parse_names(): assert parse_names(" هومر \n\nکافکا\nهومر\n") == ["هومر", "کافکا"]

def test_import_example_prompt():
    names = import_prompt_file(Path("prompts/example-chasing-homer.txt"))
    assert names[0] == "تعقیب هومر" and "کافکا" in names and "تانگوی شیطان" in names
    assert not any(n.startswith("جلسهٔ") for n in names)

def test_save_list_sanitises_name(tmp_path):
    save_list(tmp_path, "Chasing/Homer", ["هومر"]); assert list_lists(tmp_path) == ["Chasing_Homer"]
    assert load_list(tmp_path, "Chasing_Homer") == ["هومر"]
```

- [ ] **Step 3: Run** — Expected: FAIL. **Step 4: Implement.** **Step 5: Run** — Expected: PASS.
- [ ] **Step 6: Commit** — `git commit -m "Add data dir, settings, recents and name lists"`

---

### Task 4: System check

**Files:**
- Create: `booktranscriber/syscheck.py`, `tests/test_syscheck.py`

**Interfaces:**
- Produces:
  - `@dataclass GpuInfo(name: str, vram_mb: int)`; `@dataclass SystemInfo(os: str, gpu: GpuInfo | None, free_bytes: int)` with `os ∈ {"linux","windows","macos"}`.
  - `parse_nvidia_smi(output: str) -> GpuInfo | None` — first non-empty line `"<name>, <MiB>"`.
  - `detect_system(target_dir: Path) -> SystemInfo` — runs `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits` (timeout 5 s; `creationflags=CREATE_NO_WINDOW` on Windows; missing binary/non-zero → `gpu=None`); `free_bytes` from `shutil.disk_usage(target_dir)`.
  - `WHISPER_REPOS = {"large-v3": "Systran/faster-whisper-large-v3", "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo"}`
  - `choose_whisper_model(info: SystemInfo) -> str` — `"large-v3"` if `gpu and gpu.vram_mb >= 4000`, else `"large-v3-turbo"`.
  - `find_existing_model(search_dirs: list[Path], model: str) -> Path | None` — for HF cache layout `<dir>/models--<org>--<name>/snapshots/<rev>/model.bin` return that snapshot dir; also accept `<dir>/<name>/model.bin`.
  - `source_checkout_dir() -> Path | None` — repo root when running from source (parent of `booktranscriber/` contains `transcribe.py`), else None.

- [ ] **Step 1: Write failing tests**

```python
def test_parse_nvidia_smi():
    assert parse_nvidia_smi("NVIDIA GeForce RTX 4050 Laptop GPU, 6141\n") == GpuInfo("NVIDIA GeForce RTX 4050 Laptop GPU", 6141)
    assert parse_nvidia_smi("") is None and parse_nvidia_smi("garbage") is None

def test_detect_system_without_nvidia_smi(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    info = detect_system(tmp_path); assert info.gpu is None and info.free_bytes > 0

@pytest.mark.parametrize("gpu,expected", [(GpuInfo("x", 6141), "large-v3"), (GpuInfo("x", 2048), "large-v3-turbo"), (None, "large-v3-turbo")])
def test_choose_whisper_model(gpu, expected): assert choose_whisper_model(SystemInfo("linux", gpu, 10**11)) == expected

def test_find_existing_model_hf_layout(tmp_path):
    snap = tmp_path / "models--Systran--faster-whisper-large-v3" / "snapshots" / "abc"; snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(b"x"); assert find_existing_model([tmp_path], "large-v3") == snap
    assert find_existing_model([tmp_path], "large-v3-turbo") is None
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS. Also run `venv/bin/python -c "from booktranscriber.syscheck import *; print(detect_system(__import__('pathlib').Path('.')))"` — Expected: shows RTX 4050, 6141.
- [ ] **Step 5: Commit** — `git commit -m "Add system check (GPU, disk, model choice, existing model)"`

---

### Task 5: Resumable verified downloader

**Files:**
- Create: `booktranscriber/downloader.py`, `tests/test_downloader.py`

**Interfaces:**
- Produces:
  - `class DownloadCancelled(Exception)`, `class ChecksumError(Exception)`, `class NetworkError(Exception)` (wraps `httpx.HTTPError`/`OSError` from the network)
  - `download_file(url: str, dest: Path, size: int | None, sha256: str | None, on_progress: Callable[[int], None], cancel: threading.Event, client: httpx.Client | None = None) -> None`
    - `on_progress(bytes_done_for_this_file)` — absolute, monotonic except when a restart resets to 0.
    - If `dest` exists and (`size` is None or matches) → `on_progress(size)` and return.
    - Writes `dest.with_name(dest.name + ".part")`; if a `.part` exists, sends `Range: bytes=N-`; on `206` appends, on `200` truncates and restarts from 0.
    - After completion: size mismatch or sha256 mismatch → delete `.part`, raise `ChecksumError`. Else `os.replace` to `dest`.
    - `cancel` checked between 1 MiB chunks → raise `DownloadCancelled`, `.part` kept.
    - `follow_redirects=True` (HF and PyPI redirect to CDNs).

- [ ] **Step 1: Write failing tests** using a local `http.server.ThreadingHTTPServer` fixture serving a 3 MiB random payload, with handler flags: `honour_range: bool`, `fail_after: int | None` (close connection after N bytes).

```python
def test_full_download_verifies(server, tmp_path):
    dest = tmp_path / "f.bin"; seen = []
    download_file(server.url, dest, len(PAYLOAD), sha(PAYLOAD), seen.append, threading.Event())
    assert dest.read_bytes() == PAYLOAD and seen[-1] == len(PAYLOAD) and not (tmp_path / "f.bin.part").exists()

def test_resume_after_drop(server, tmp_path):
    server.fail_after = 1_000_000
    with pytest.raises(NetworkError): download_file(server.url, tmp_path/"f.bin", len(PAYLOAD), sha(PAYLOAD), lambda n: None, threading.Event())
    assert (tmp_path / "f.bin.part").stat().st_size > 0
    server.fail_after = None; download_file(server.url, tmp_path/"f.bin", len(PAYLOAD), sha(PAYLOAD), lambda n: None, threading.Event())
    assert (tmp_path / "f.bin").read_bytes() == PAYLOAD and server.last_range.startswith("bytes=")

def test_server_ignoring_range_restarts_cleanly(server, tmp_path):
    (tmp_path / "f.bin.part").write_bytes(PAYLOAD[:500_000]); server.honour_range = False
    download_file(server.url, tmp_path/"f.bin", len(PAYLOAD), sha(PAYLOAD), lambda n: None, threading.Event())
    assert (tmp_path / "f.bin").read_bytes() == PAYLOAD

def test_checksum_mismatch_deletes_part(server, tmp_path):
    with pytest.raises(ChecksumError): download_file(server.url, tmp_path/"f.bin", len(PAYLOAD), "0"*64, lambda n: None, threading.Event())
    assert not (tmp_path / "f.bin.part").exists() and not (tmp_path / "f.bin").exists()

def test_cancel_keeps_part(server, tmp_path):
    ev = threading.Event()
    def prog(n):
        if n > 1_000_000: ev.set()
    with pytest.raises(DownloadCancelled): download_file(server.url, tmp_path/"f.bin", len(PAYLOAD), None, prog, ev)
    assert (tmp_path / "f.bin.part").exists()

def test_existing_dest_skips(server, tmp_path):
    (tmp_path / "f.bin").write_bytes(PAYLOAD); server.requests = 0
    download_file(server.url, tmp_path/"f.bin", len(PAYLOAD), sha(PAYLOAD), lambda n: None, threading.Event())
    assert server.requests == 0
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** with `httpx.Client.stream("GET", …)`, 1 MiB `iter_bytes`, sha256 computed incrementally (on resume, hash the existing `.part` first). **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `git commit -m "Add resumable, verified downloader"`

---

### Task 6: Setup sources and setup runner

**Files:**
- Create: `booktranscriber/setup_sources.py`, `booktranscriber/setup_runner.py`, `tests/test_setup_sources.py`, `tests/test_setup_runner.py`, `tests/fixtures/pypi_cublas.json` (trimmed real PyPI JSON: `urls` list with a `manylinux…x86_64` wheel, a `win_amd64` wheel and an sdist entry)

**Interfaces:**
- Consumes: `downloader.download_file` + its exceptions, `syscheck.*`, `paths.*`, `settings.Settings`, `worker.worker_command`, `gpu.nvidia_lib_dirs/gpu_env`, `protocol.decode`.
- Produces (`setup_sources.py`):
  - `GPU_WHEELS = {"nvidia-cublas-cu12": "12.9.2.10", "nvidia-cudnn-cu12": "9.24.0.43", "nvidia-cuda-nvrtc-cu12": "12.9.86"}` (the versions installed in the venv today).
  - `@dataclass RemoteFile(url: str, size: int, sha256: str | None, dest: Path)`
  - `pick_wheel(pypi_json: dict, os_name: str) -> tuple[str, int, str, str]` → `(url, size, sha256, filename)`; linux = `manylinux` + `x86_64`, windows = `win_amd64`; `LookupError` if none.
  - `gpu_wheel_files(os_name: str, gpu_dir: Path, client: httpx.Client) -> list[RemoteFile]` — fetch `https://pypi.org/pypi/{name}/{version}/json`; dest `gpu_dir/"wheels"/filename`.
  - `extract_nvidia_libs(wheel: Path, gpu_dir: Path, windows: bool) -> list[Path]` — extract only members matching `nvidia/<pkg>/{lib|bin}/*` into `gpu_dir` (result layout `gpu_dir/nvidia/<pkg>/lib/…`, which `gpu.nvidia_lib_dirs([gpu_dir/"nvidia"], …)` finds); delete the wheel afterwards.
  - `model_files(repo_id: str, dest_dir: Path) -> list[RemoteFile]` — `HfApi().model_info(repo_id, files_metadata=True)`; one `RemoteFile` per sibling (size from metadata, sha256 from `lfs.sha256` when present), url `huggingface_hub.hf_hub_url(repo_id, filename, revision=info.sha)`, dest `dest_dir/filename`.
- Produces (`setup_runner.py`):
  - `ITEMS = ("check", "gpu", "whisper", "test")`
  - `@dataclass SetupPlan(info: SystemInfo, include_gpu: bool, whisper_model: str, reuse_model_path: Path | None, needed_bytes: int)`
  - `make_plan(info: SystemInfo, existing: Path | None) -> SetupPlan` — `include_gpu = info.os != "macos" and info.gpu is not None`; `needed_bytes` estimate = 1.6 GB GPU libs (if included) + 3.1 GB large-v3 / 1.7 GB turbo (0 if reusing) + 10% margin. (Exact figures are estimates for the Welcome screen; actual totals come from file sizes.)
  - `@dataclass SetupProgress(item: str, item_done: int, item_total: int, overall_done: int, overall_total: int, bytes_per_sec: float, eta_seconds: float | None)`
  - `class SetupError(Exception)` with `.kind ∈ {"network","disk","checksum","gpu","test","cancelled"}`.
  - `run_setup(plan: SetupPlan, settings: Settings, on_progress: Callable[[SetupProgress], None], cancel: threading.Event, *, downloader=download_file, sources=setup_sources, selftest=run_selftest) -> Settings` — resolves all `RemoteFile`s first (so `overall_total` is the true byte total), downloads in order gpu → whisper, extracts wheels, runs self-test, returns updated settings (`setup_done=True`, `whisper_model`, `whisper_model_path`). Free space re-checked against the true total before downloading → `SetupError("disk")`. Speed = bytes over the last 5 s window.
  - `run_selftest(model_path: str, device: str) -> None` — spawns `worker_command(["--selftest", "--model", model_path, "--device", device])` with `gpu_env(...)`, timeout 600 s, raises `SetupError("gpu")` if `device != "cpu"` and the worker errors with kind `model`, else `SetupError("test")`.

- [ ] **Step 1: Write failing tests**

```python
def test_pick_wheel_linux_and_windows():
    j = json.loads(Path("tests/fixtures/pypi_cublas.json").read_text())
    assert "manylinux" in pick_wheel(j, "linux")[3] and pick_wheel(j, "windows")[3].endswith("win_amd64.whl")
    with pytest.raises(LookupError): pick_wheel({"urls": []}, "linux")

def test_extract_only_libs(tmp_path):
    whl = tmp_path / "x.whl"
    with zipfile.ZipFile(whl, "w") as z:
        z.writestr("nvidia/cublas/lib/libcublas.so.12", b"so"); z.writestr("nvidia/cublas/include/cublas.h", b"h")
        z.writestr("nvidia_cublas_cu12-12.9.dist-info/METADATA", b"m")
    out = extract_nvidia_libs(whl, tmp_path / "gpu", windows=False)
    assert out == [tmp_path / "gpu/nvidia/cublas/lib/libcublas.so.12"] and not whl.exists()
    assert nvidia_lib_dirs([str(tmp_path / "gpu/nvidia")], False) == [str(tmp_path / "gpu/nvidia/cublas/lib")]

def test_make_plan_reuse_and_no_gpu():
    p = make_plan(SystemInfo("linux", None, 10**12), existing=None); assert not p.include_gpu and p.whisper_model == "large-v3-turbo"
    p = make_plan(SystemInfo("linux", GpuInfo("x", 6141), 10**12), existing=Path("/m")); assert p.reuse_model_path == Path("/m")

def test_run_setup_progress_aggregates_and_finishes(tmp_path, fake_sources):
    # fake_sources: gpu → two files 100 + 300 bytes, whisper → one file 600 bytes; fake downloader reports in 2 steps
    seen = []; s = run_setup(plan_with_gpu, Settings(), seen.append, threading.Event(), downloader=fake_dl, sources=fake_sources, selftest=lambda *a: None)
    assert seen[-1].overall_done == seen[-1].overall_total == 1000
    assert [p.overall_done for p in seen] == sorted(p.overall_done for p in seen)   # monotonic overall bar
    assert s.setup_done and s.whisper_model_path

def test_run_setup_reuse_skips_model_download(...):  # plan.reuse_model_path set → no whisper downloads; settings.whisper_model_path == str(reuse path)
def test_run_setup_disk_full(...):                   # info.free_bytes < total → SetupError kind "disk", downloader never called
def test_run_setup_network_error_maps_kind(...):     # fake_dl raises NetworkError → SetupError kind "network"
def test_run_setup_cancel(...):                      # fake_dl raises DownloadCancelled → SetupError kind "cancelled"
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Real integration (network).** Script in scratchpad with `BT_DATA_DIR=<scratch>/bt-data`: build plan from `detect_system`, `existing=None`, run `run_setup` printing progress every 2 s. Expected: three wheels download and extract into `bt-data/gpu/nvidia/{cublas,cudnn,cuda_nvrtc}/lib`, model files into `bt-data/models/…`, self-test passes on `cuda/float16`. Interrupt once with Ctrl-C mid-model and re-run → resumes (check log of Range header). **Negative check:** run `run_selftest` with `device="cuda"` and an env with *no* NVIDIA lib dirs → it must raise `SetupError("gpu")`; if it passes, the self-test isn't exercising the GPU and must be fixed before moving on. To prove the extracted libs (not the venv's) are used, the self-test env is built from `nvidia_lib_dirs([paths.gpu_dir()/"nvidia"], False)` only. Then delete `<scratch>/bt-data`.
- [ ] **Step 6: Commit** — `git commit -m "Add setup sources (PyPI CUDA wheels, HF model) and setup runner"`

---

### Task 7: Fix-export logic (line protocol, parts, parse, guardrails, diff)

**Files:**
- Create: `booktranscriber/fixexport.py`, `tests/test_fixexport.py`

**Interfaces:**
- Produces:
  - `TS_RE = re.compile(r"^\[(\d+:\d{2}:\d{2})\]\s?")`
  - `split_timestamp(line: str) -> tuple[str, str]` → `("[0:01:05] ", "text")` or `("", line)`.
  - `INSTRUCTIONS: str` — English instruction block (my call: LLMs follow English instructions most reliably; it states "keep the text in its original language"). Contains, verbatim in meaning, the §5.1 rules, the reply format ("Reply with exactly the same numbered lines, `[n] text`, nothing else"), and a `{names}` placeholder line ("Correct spellings of names: {names}") omitted when there are no names.
  - `MAX_PART_CHARS = 6000` (transcript text per part, excluding instructions — my call).
  - `@dataclass ExportPart(index: int, total: int, first_line: int, last_line: int, text: str)` — `text` = instructions + `"Part {i} of {n}"` + numbered lines `"[n] text"` (1-based global numbers, timestamps stripped).
  - `build_export_parts(lines: list[str], names: list[str], max_chars: int = MAX_PART_CHARS) -> list[ExportPart]` — never splits a line; empty lines are skipped but keep their numbering gap (numbers stay the transcript's line numbers).
  - `parse_answer(text: str) -> dict[int, str]` — accepts `[n]`, `n.`, `n)` prefixes with ASCII, Persian (`۰-۹`) or Arabic-Indic (`٠-٩`) digits; ignores fences/other lines; first occurrence of a number wins.
  - `MAX_CHANGE_RATIO = 0.5`; `@dataclass LineFix(n: int, original: str, proposed: str | None, accepted: bool, reason: str)` with `reason ∈ {"same","fixed","missing","too_different"}`.
  - `apply_answer(lines: list[str], answer: dict[int, str], max_change: float = MAX_CHANGE_RATIO) -> list[LineFix]` — compares text without timestamps; rejects when `1 - SequenceMatcher(None, a, b).ratio() > max_change` or `abs(len(a.split()) - len(b.split())) > max(2, len(a.split()) // 4)`.
  - `corrected_lines(lines: list[str], fixes: list[LineFix]) -> list[str]` — accepted proposals with original timestamp prefix re-attached; others original.
  - `word_diff(a: str, b: str) -> list[tuple[str, str]]` — `("same"|"removed"|"added", text)` over whitespace-split words.

- [ ] **Step 1: Write failing tests**

```python
LINES = ["[0:00:01] امروز درباره تعغیب حومر حرف زدیم", "[0:00:05] نویسنده اش کراسنا هورکای است", "", "[0:00:09] خب"]

def test_parts_number_and_strip_timestamps():
    parts = build_export_parts(LINES, ["تعقیب هومر"])
    assert len(parts) == 1 and "[1] امروز درباره تعغیب حومر حرف زدیم" in parts[0].text
    assert "[0:00:01]" not in parts[0].text and "[3]" not in parts[0].text and "[4] خب" in parts[0].text
    assert "تعقیب هومر" in parts[0].text and "Part 1 of 1" in parts[0].text

def test_parts_split_on_line_boundaries():
    lines = ["کلمه " * 50] * 10                     # ~250 chars each
    parts = build_export_parts(lines, [], max_chars=600)
    assert [ (p.first_line, p.last_line) for p in parts ] == [(1,2),(3,4),(5,6),(7,8),(9,10)]
    assert all(p.total == 5 for p in parts)

def test_no_names_omits_names_line():
    assert "Correct spellings of names" not in build_export_parts(["a"], [])[0].text

def test_parse_answer_messy():
    text = "Sure! Here you go:\n```\n[۱] امروز درباره تعقیب هومر حرف زدیم\n2. نویسنده‌اش کراسناهورکای است\n[٤] خب\n[1] duplicate\n```\nLet me know!"
    assert parse_answer(text) == {1: "امروز درباره تعقیب هومر حرف زدیم", 2: "نویسنده‌اش کراسناهورکای است", 4: "خب"}

def test_apply_answer_accepts_small_fixes_keeps_timestamps():
    fixes = apply_answer(LINES, {1: "امروز درباره تعقیب هومر حرف زدیم", 2: "نویسنده‌اش کراسناهورکای است", 4: "خب"})
    assert [f.reason for f in fixes if f.original] == ["fixed", "fixed", "same"]
    assert corrected_lines(LINES, fixes)[0] == "[0:00:01] امروز درباره تعقیب هومر حرف زدیم"

def test_apply_answer_rejects_rewrite_and_missing():
    fixes = apply_answer(LINES, {1: "در این جلسه، اعضا به تحلیل مفصل رمان پرداختند و نکات زیادی گفتند"})
    assert fixes[0].reason == "too_different" and not fixes[0].accepted
    assert fixes[1].reason == "missing" and corrected_lines(LINES, fixes)[1] == LINES[1]

def test_word_diff():
    assert word_diff("تعغیب حومر حرف", "تعقیب هومر حرف") == [("removed","تعغیب حومر"),("added","تعقیب هومر"),("same","حرف")]
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** (`difflib.SequenceMatcher` for ratio and word diff; digit normalisation via `str.maketrans` from `۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩`). **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `git commit -m "Add export-for-AI line protocol, answer parsing and guardrails"`

---

### Task 8: Translations

**Files:**
- Create: `booktranscriber/i18n.py`, `tests/test_i18n.py`

**Interfaces:**
- Produces:
  - `STRINGS: dict[str, dict[str, str]]` with `"en"` and `"fa"`; keys are dotted (`"setup.welcome.title"`, `"error.network"`, …). Every user-visible string from Tasks 9–12 is added here **in the same task that adds the widget** (this task seeds the table with the setup-screen copy from the spec §4.1 and the mockup `setup-flow.html`, Persian included).
  - `initial_language(saved: str | None, locale_name: str) -> str` — saved wins; else `"fa"` if `locale_name.startswith("fa")`, else `"en"`.
  - `class I18n(QObject)`: `language_changed = Signal(str)`; `language: str`; `tr(key: str, **kw) -> str` (missing key → the key itself, and logged once); `set_language(lang: str) -> None`; `is_rtl() -> bool`.
  - `fmt_number(n: int | float, lang: str) -> str` — Persian digits for `fa` (`"۵۸"`), ASCII otherwise; `fmt_bytes(n: int, lang: str) -> str` (`"2.1 GB"` / `"۲٫۱ گیگابایت"`); `fmt_duration(seconds: float, lang: str) -> str` (`"about 6 min"` / `"حدود ۶ دقیقه"`, `"less than a minute"` / `"کمتر از یک دقیقه"`).

- [ ] **Step 1: Write failing tests**

```python
def test_keys_match(): assert set(STRINGS["en"]) == set(STRINGS["fa"])
def test_placeholders_match():
    for k in STRINGS["en"]:
        assert set(re.findall(r"{(\w+)}", STRINGS["en"][k])) == set(re.findall(r"{(\w+)}", STRINGS["fa"][k])), k
def test_initial_language():
    assert initial_language(None, "fa_IR") == "fa" and initial_language(None, "en_US") == "en" and initial_language("en", "fa_IR") == "en"
def test_formatting():
    assert fmt_number(58, "fa") == "۵۸" and fmt_bytes(2_100_000_000, "fa") == "۲٫۱ گیگابایت" and fmt_bytes(2_100_000_000, "en") == "2.1 GB"
    assert fmt_duration(370, "en") == "about 6 min" and fmt_duration(30, "fa") == "کمتر از یک دقیقه"
def test_tr_and_switch(qtbot):
    i = I18n("en"); got = []; i.language_changed.connect(got.append); i.set_language("fa")
    assert got == ["fa"] and i.is_rtl() and i.tr("setup.welcome.title") == STRINGS["fa"]["setup.welcome.title"]
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS. **Step 5: Commit** — `git commit -m "Add en/fa translations and locale formatting"`

---

### Task 9: GUI shell, runners, language switch

**Files:**
- Create: `booktranscriber/gui/__init__.py`, `gui/app.py`, `gui/main_window.py`, `gui/runners.py`, `gui/widgets.py`, `run-gui.sh`, `run-gui.bat`, `tests/gui/test_shell.py`, `tests/gui/test_runners.py`

**Interfaces:**
- Consumes: `I18n`, `initial_language`, `load_settings/save_settings`, `paths.*`, `worker_command`, `gpu.*`, `protocol.decode`, `run_setup`, `SetupProgress`, `SetupError`.
- Produces (`runners.py`):
  - `@dataclass TranscribeJob(audio: str, out: str, model: str, download_root: str | None, language: str, prompt: str | None, timestamps: bool, device: str)`
  - `class TranscribeRunner(QObject)`: signals `loaded(str)`, `duration(float)`, `segment(float, str)`, `progress(float, float, float)` (done, total, eta), `finished(str, int)` (out, segments), `failed(str, str)` (kind, message); `start(job)`, `cancel()` (kill; removes `out + ".part"`), `is_running() -> bool`. Uses `QProcess` with `worker_command` and env from `gpu_env(nvidia_lib_dirs([gpu_dir/nvidia] + site roots))`; reads stdout line-buffered as UTF-8; non-zero exit without an `error` event → `failed("unknown", <last stderr lines>)`; stderr also appended to `logs_dir()/worker.log`.
  - `class SetupRunner(QObject)`: signals `progress(object)` (SetupProgress), `finished(object)` (Settings), `failed(str)` (kind); `start(plan, settings)`, `pause()` (sets cancel → `failed("cancelled")`), `is_running()`. Runs `run_setup` in a `QThread`.
- Produces (`main_window.py`): `class MainWindow(QMainWindow)` — `__init__(i18n, settings)`; a `QStackedWidget` with `setup`, `home`, `flow`, `export`, `review` pages (placeholders until Tasks 10–12 fill them); a top-right `QToolButton` showing `"EN"` when UI is fa and `"فا"` when en, toggling `i18n.set_language`, saving `settings.ui_language`; on `language_changed`: `QApplication.setLayoutDirection(RightToLeft/LeftToRight)` and every page's `retranslate()`; `show_page(name: str)`; `busy() -> bool` (any runner running); `closeEvent` asks `tr("confirm.quit_busy")` when busy, then cancels runners and **waits for the SetupRunner's QThread to finish** (`thread.quit(); thread.wait(10000)`) and for the worker QProcess to exit before accepting, avoiding "QThread destroyed while running".
- Produces (`app.py`): `main(argv) -> int` — `QApplication`, app font = system font with Persian fallbacks (`font.setFamilies([system_family, "Vazirmatn", "Noto Sans Arabic"])`), load settings, `I18n(initial_language(settings.ui_language, QLocale.system().name()))`, open `setup` if not `settings.setup_done` or model path missing, else `home`.
- `run-gui.sh`: `exec "$HERE/venv/bin/python" -m booktranscriber "$@"` (cd-independent). `run-gui.bat` analogous with `pythonw.exe` (no console).

- [ ] **Step 1: Write failing tests** (`QT_QPA_PLATFORM=offscreen` set in `tests/gui/conftest.py`)

```python
def test_starts_on_setup_when_not_done(qtbot):
    w = MainWindow(I18n("en"), Settings()); qtbot.addWidget(w); assert w.current_page() == "setup"
def test_starts_on_home_when_done(qtbot, tmp_path):
    (tmp_path / "model.bin").write_bytes(b"x")
    w = MainWindow(I18n("en"), Settings(setup_done=True, whisper_model_path=str(tmp_path))); qtbot.addWidget(w); assert w.current_page() == "home"
def test_language_toggle_flips_direction_and_saves(qtbot):
    w = MainWindow(I18n("en"), Settings()); qtbot.addWidget(w)
    qtbot.mouseClick(w.lang_button, Qt.LeftButton)
    assert QApplication.layoutDirection() == Qt.RightToLeft and w.lang_button.text() == "EN"
    assert load_settings(paths.settings_file()).ui_language == "fa"

# test_runners.py — drive TranscribeRunner with a fake worker: monkeypatch worker_command to
# [sys.executable, "tests/gui/fake_worker.py", ...] which prints scripted JSON lines (and one junk line)
def test_runner_emits_events(qtbot, monkeypatch):  # expects loaded → segment×2 → finished("…", 2)
def test_runner_crash_without_error_event(qtbot, monkeypatch):  # fake worker exits 139 → failed("unknown", …)
def test_runner_cancel_kills_and_removes_part(qtbot, monkeypatch, tmp_path):  # fake worker sleeps; cancel(); process gone; .part removed
```

- [ ] **Step 2: Run** `venv/bin/python -m pytest tests/gui -v` — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: 👤 Owner checkpoint.** `./run-gui.sh` opens a window on the setup page; toggling فا/EN mirrors the layout.
- [ ] **Step 6: Commit** — `git commit -m "Add GUI shell, worker/setup runners and language toggle"`

---

### Task 10: Setup screens

**Files:**
- Create: `booktranscriber/gui/setup_view.py`, `tests/gui/test_setup_view.py`
- Modify: `booktranscriber/i18n.py` (setup + error strings), `gui/main_window.py` (mount view; on finish → save settings, go `home`)

**Interfaces:**
- Consumes: `detect_system`, `find_existing_model`, `source_checkout_dir`, `make_plan`, `SetupRunner`, `fmt_*`.
- Produces: `class SetupView(QWidget)` — `__init__(i18n, settings)`; signal `completed(object)` (Settings); `retranslate()`; internal states `welcome | downloading | ready | error`; `state() -> str`.
- Also: a ⚙ button in `MainWindow`'s top bar with one menu item `settings.repair` ("Check / repair setup") that opens the setup page in `welcome` state (spec §4.1).

Behaviour (copy and layout per spec §4.1 and `setup-flow.html`):
- **Welcome:** runs `detect_system(paths.data_dir())` on show. Lines: computer verdict (`setup.check.gpu_ok` with GPU name / `setup.check.no_gpu` "works, but transcribing will be slower"), time estimate (`needed_bytes / 4 MB/s`), space needed vs free (red + disabled button if insufficient). If `find_existing_model([source_checkout_dir()/"models"], model)` finds a model: a ticked checkbox `setup.reuse_existing` ("Use the speech model already on this computer (saves 2.9 GB)"). **The AI-helper checkbox is not shown in stage 1** (it arrives with stage 2). Button `setup.start`.
- **Downloading:** overall bar + `fmt_number(pct)%` + `fmt_duration(eta)`; rows `check`, `gpu` (hidden if `not plan.include_gpu`), `whisper`, `test` with icons ✅/⬇️/⏳; active row shows its own bar and `fmt_bytes(done) / fmt_bytes(total)`; note `setup.resume_note`; `Pause` → runner.pause → shows `Continue` (re-runs `start`, which skips finished files).
- **Ready:** 🎉, `setup.ready.title`, `setup.ready.body`, button `setup.ready.go` → `completed`.
- **Error** (from `SetupRunner.failed(kind)`): `network` → "connection lost, nothing is lost, {done} already saved" + `Try again`; `disk` → not-enough-space text + `Check again`; `checksum` → "a file arrived damaged, it will be downloaded again" + `Try again`; `gpu` → "graphics card couldn't be used — continue without it (slower)?" + `Continue without graphics card` (sets `settings.device = "cpu"`, re-runs test only); `test` → "something went wrong during the test" + `Try again` + small `Show details` (opens `logs_dir()`); `cancelled` → back to downloading state with `Continue`.

- [ ] **Step 1: Write failing tests** with `SetupRunner` and `detect_system` monkeypatched:

```python
def test_welcome_shows_gpu_and_space(qtbot, fake_system_ok): v = SetupView(I18n("en"), Settings()); assert "RTX 4050" in v.findChild(QLabel, "check_line").text() and v.start_button.isEnabled()
def test_welcome_blocks_when_disk_full(qtbot, fake_system_full): assert not SetupView(...).start_button.isEnabled()
def test_reuse_checkbox_when_existing_model(qtbot, fake_existing): assert SetupView(...).reuse_box.isVisible() and v.reuse_box.isChecked()
def test_progress_updates_rows(qtbot, fake_runner): v.start(); fake_runner.progress.emit(SetupProgress("whisper", 1_000, 3_000, 2_000, 4_000, 4e6, 300)); assert v.overall_bar.value() == 50
def test_network_error_then_retry(qtbot, fake_runner): fake_runner.failed.emit("network"); assert v.state() == "error"; qtbot.mouseClick(v.retry_button, Qt.LeftButton); assert fake_runner.start_calls == 2
def test_gpu_error_offers_cpu(qtbot, fake_runner): fake_runner.failed.emit("gpu"); click cpu button → fake_runner.last_settings.device == "cpu"
def test_ready_emits_completed(qtbot, fake_runner): fake_runner.finished.emit(Settings(setup_done=True, whisper_model_path="/m")); click go → completed emitted with that Settings
def test_persian_digits(qtbot, fake_system_ok): v = SetupView(I18n("fa"), Settings()); t = v.findChild(QLabel, "space_line").text(); assert re.search("[۰-۹]", t) and not re.search("[0-9]", t)
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: 👤 Owner checkpoint (the agent cannot drive the Qt window — do not mark verified without the owner's report).** Owner runs `BT_DATA_DIR=<scratch>/bt-fresh ./run-gui.sh` with the reuse box unticked and watches setup to Ready; turns Wi-Fi off mid-model → network error → back on → Try again resumes. Then `./run-gui.sh` (default data dir) with reuse ticked → setup takes seconds. *Agents must not toggle networking (it would cut their own session).*
- [ ] **Step 6: Commit** — `git commit -m "Add first-run setup screens with live progress and friendly errors"`

---

### Task 11: Home, names and transcribing steps

**Files:**
- Create: `booktranscriber/gui/home_view.py`, `booktranscriber/gui/flow_view.py`, `tests/gui/test_home_flow.py`
- Modify: `i18n.py`, `gui/widgets.py` (`DropArea`), `gui/main_window.py`

**Interfaces:**
- Consumes: `TranscribeRunner`, `TranscribeJob`, `namelists.*`, `recents.*`, `engine.output_path`, `build_prompt`.
- Produces:
  - `AUDIO_EXTS = {".wav",".m4a",".mp3",".ogg",".opus",".flac",".aac",".wma",".mp4",".webm",".mkv",".amr",".3gp"}` (in `home_view.py`).
  - `class DropArea(QFrame)`: signal `file_chosen(str)`; accepts drops; `Choose a file…` button opens `QFileDialog` filtered to `AUDIO_EXTS`.
  - `validate_drop(paths: list[str]) -> tuple[str | None, str | None]` → `(audio_path, error_key)`; error keys `home.err.many` (more than one file → "please drop one recording at a time"), `home.err.folder`, `home.err.not_audio`, `home.err.missing`.
  - `class HomeView(QWidget)`: signals `audio_selected(str)`, `recent_opened(object)` (RecentItem); `refresh_recents()`; shows up to 5 recents ("session-11 ✔").
  - `class FlowView(QWidget)`: signals `transcribed(object)` (`RecentItem`), `back_home()`; `begin(audio: str)` shows **names step**; `state() -> "names" | "transcribing" | "result"`.
    - Names step: header `flow.names.title`, hint, `QPlainTextEdit` (RTL when transcript language `fa`), `Load saved list ▾` (`list_lists`), `Import from file…` (`import_prompt_file`), `Save this list as…` checkbox + name field, `Skip` / `Continue`. An **Advanced** collapsible: language (`fa`, `en`, `ar`, `ru`, `de`, `fr`, `tr` + "other code" line edit), model (`large-v3` / `large-v3-turbo`, disabled for models not downloaded), timestamps checkbox, device (`auto/cuda/cpu`); values persist into Settings.
    - Before starting: output = `output_path(audio)`; if its folder is not writable (`os.access(dir, os.W_OK)` false), `QFileDialog.getSaveFileName` defaulting to the same filename in `~/Documents`; cancel → stay on names step.
    - Transcribing step: progress bar (done/total), `fmt_duration(eta)` ("about 8 min left"), status line (`flow.loading` until `loaded`), live read-only text view appending each segment, `Cancel` (confirm → `runner.cancel()` → back to names step).
    - On `finished(out, n)`: `n == 0` → message `flow.no_speech` + `Try another file`; else `add_recent`, emit `transcribed(item)` → MainWindow goes to `result` (Task 12).
    - On `failed(kind)`: `bad_audio`/`not_found` → friendly message + `Choose another file`; `model` → "couldn't start, try without graphics card?" + button retrying with device `cpu`; `write` → "couldn't save next to the recording" + choose location; `unknown` → generic + `Try again` + `Show details`.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("paths,err", [(["a.m4a","b.m4a"], "home.err.many"), (["book.pdf"], "home.err.not_audio")])
def test_validate_drop_errors(tmp_path, paths, err): ...files created in tmp_path... assert validate_drop([...])[1] == err
def test_validate_drop_folder_and_missing(tmp_path):
    assert validate_drop([str(tmp_path)])[1] == "home.err.folder" and validate_drop([str(tmp_path/"x.m4a")])[1] == "home.err.missing"
def test_validate_drop_persian_name(tmp_path):
    f = tmp_path / "جلسه ۱۲.m4a"; f.write_bytes(b"x"); assert validate_drop([str(f)]) == (str(f), None)
def test_names_skip_starts_with_default_prompt(qtbot, fake_runner): v.begin(str(wav)); click Skip → fake_runner.last_job.prompt == "جلسهٔ کتاب‌خوانی به زبان فارسی."
def test_names_continue_builds_prompt_and_saves_list(qtbot, fake_runner): type "هومر\nکافکا", tick save as "Homer" → prompt contains "هومر، کافکا" and list_lists(...) == ["Homer"]
def test_progress_and_segments_shown(qtbot, fake_runner): emit duration(100), progress(25, 100, 60), segment(0, "سلام") → bar 25, text contains "سلام", eta label "about 1 min"
def test_no_speech_message(qtbot, fake_runner): emit finished(out, 0) → state stays "transcribing"-panel showing flow.no_speech text; no recent added
def test_cancel_returns_to_names(qtbot, fake_runner, monkeypatch): auto-accept confirm → fake_runner.cancel_called and v.state() == "names"
def test_close_while_busy_asks_and_kills(qtbot, fake_runner, monkeypatch): MainWindow with running fake runner; QMessageBox → No: window stays; → Yes: runner.cancel called, event accepted
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: 👤 Owner checkpoint.** Owner runs `./run-gui.sh`: drop the 60 s clip → names (load imported example list) → Continue → live text appears, progress moves, ends on the result page; file `clip - متن خام.txt` next to the clip. Drop a PDF → friendly error, no model load (check `nvidia-smi` shows no worker). Start a long file and close the window → confirm → no `booktranscriber.worker` left in `ps aux`.
- [ ] **Step 6: Commit** — `git commit -m "Add home, names and transcribing steps"`

---

### Task 12: Result, export-for-AI, paste back, review & save

**Files:**
- Create: `booktranscriber/gui/export_view.py`, `booktranscriber/gui/review_view.py`, `tests/gui/test_export_review.py`
- Modify: `gui/flow_view.py` (result step), `gui/main_window.py`, `i18n.py`, `recents.py` users (store `corrected_path`)

**Interfaces:**
- Consumes: `fixexport.*`, `CORRECTED_SUFFIX`, `output_path`, `add_recent`, `load_list`.
- Produces:
  - Result step in `FlowView`: shows the raw transcript (RTL for `fa`) and three choices: **Fix it here (private)** — disabled card with `result.local.soon` ("coming in the next version"); **Prepare for ChatGPT / Claude / Gemini** → export page (names pre-filled from the names step); **Just save the text** → `result.saved_at` with `Open folder`. Opening a recent item lands here too, loading the raw file, with the export page's names field empty and editable.
  - `class ExportView(QWidget)`: `load(raw_path: str, names: list[str], language: str)`; how-to text (`export.howto`, 3 numbered steps); a row per `ExportPart`: `Part {i} of {n}`, `Copy` (to `QGuiApplication.clipboard()`, button flashes "Copied ✓"), and one `Save all parts…` (folder dialog → `"<name> - part 1 of 4.txt"` …); a large `QPlainTextEdit` "Paste the AI's answers here (all parts together is fine)"; `Check the answers` → `parse_answer` over the whole box → `apply_answer` → signal `review_ready(object)` (`list[LineFix]`) with `raw_lines`. If zero lines recognised → inline message `export.nothing_recognised` and stay.
  - `class ReviewView(QWidget)`: `load(raw_path, lines, fixes, language)`; summary line ("{fixed} lines fixed · {kept} kept as they were · {missing} not answered yet"); a `QTableWidget` with columns `#`, original, corrected (HTML with `word_diff`: removed = red strikethrough, added = green bold), and a `Use fix` checkbox (checked for accepted, unchecked & disabled-looking for `too_different` with tooltip `review.too_different`, hidden for `same`/`missing`); filter toggle "Show only changed lines" (default on); `Save` → writes `corrected_lines(...)` honouring the checkboxes to `corrected_path_for(raw_path)` (beside the raw file, even if the raw file was redirected away from the audio folder), updates recents' `corrected_path`, shows `review.saved` + `Open folder`; `Copy`; `Back to answers` (keeps pasted text).
  - Text cells use `Qt.RightToLeft` when language is `fa`.

- [ ] **Step 1: Write failing tests**

```python
def test_export_parts_listed_and_copy(qtbot, raw_file):  # raw_file has 30 lines of ~400 chars → 2+ parts; click Copy on part 1 → clipboard text == parts[0].text
def test_paste_back_messy_answer_goes_to_review(qtbot, raw_file):  # paste "```\n[۱] …fixed…\n```" → review_ready emitted, fixes[0].reason == "fixed"
def test_paste_garbage_stays(qtbot, raw_file):  # paste "hello" → no signal, export.nothing_recognised visible
def test_review_save_respects_unticked(qtbot, tmp_path):
    lines = ["[0:00:01] تعغیب حومر", "[0:00:03] کراسنا هورکای"]
    fixes = apply_answer(lines, {1: "تعقیب هومر", 2: "کراسناهورکای"})
    raw = tmp_path / "a - متن خام.txt"; raw.write_text("\n".join(lines) + "\n", "utf-8")
    v = ReviewView(I18n("fa")); v.load(str(raw), lines, fixes, "fa"); v.set_use_fix(2, False); v.save()
    assert (tmp_path / "a - متن اصلاح‌شده.txt").read_text("utf-8") == "[0:00:01] تعقیب هومر\n[0:00:03] کراسنا هورکای\n"
def test_review_too_different_unticked(qtbot): ... fixes with too_different → checkbox unchecked by default
def test_review_summary_counts(qtbot): "1 lines fixed" style counts via tr with Persian digits in fa
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: 👤 Owner checkpoint.** Transcribe the 60 s clip, Prepare for ChatGPT, copy part 1 into a real chat (owner does this), paste the answer back, review highlights, untick one fix, Save → corrected file next to raw; reopen app → recent item shows ✔ and opens the result.
- [ ] **Step 6: Commit** — `git commit -m "Add export-for-AI, paste-back review and saving corrected transcript"`

---

### Task 13: Docs and full verification

**Files:**
- Modify: `README.md` (new top section "Desktop app (preview, Linux)" — `./setup.sh` then `./run-gui.sh`; keep all CLI docs; project layout updated with `booktranscriber/`, `run-gui.*`, `requirements-gui.txt`, `requirements-dev.txt`, `tests/`)

- [ ] **Step 1:** Update README as above (English, matching the existing tone and structure).
- [ ] **Step 2: Full test run** `venv/bin/python -m pytest -v` — Expected: all pass, no warnings about leaked processes/threads.
- [ ] **Step 3: 👤 Owner checkpoint — fresh-machine simulation (owner runs it in a normal terminal; sandboxes kill sustained GPU compute).** `git clone . <scratch>/bt-clone && cd <scratch>/bt-clone && ./setup.sh && BT_DATA_DIR=<scratch>/bt-data2 ./run-gui.sh` — setup from zero (no reuse option offered, since the clone has no `models/`), transcribe a real ~90-minute recording end to end, confirm time is in the CLI's range (~20–25 min) and the CLI `./run.sh` in the clone still works.
- [ ] **Step 4: 👤 Owner checkpoint — Persian UI pass.** Switch to فا: every screen mirrored, no English leftovers, numbers in Persian digits, transcript views RTL.
- [ ] **Step 5: Commit** — `git commit -m "Document the desktop app preview"`
