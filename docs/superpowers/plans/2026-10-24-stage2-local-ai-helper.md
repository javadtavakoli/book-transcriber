# Stage 2 — Local AI helper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Fix it here (private)" works: setup can download a local AI helper (llama-server + one GGUF model chosen for the machine), the app loads it with a real progress bar, fixes the transcript in numbered chunks with the shared guardrails, and opens the existing review screen.

**Architecture:** Four new non-GUI modules:
- `llm_catalog`: pinned llama.cpp build, runtime archives and model tiers.
- `llm_sources`: the download list, plus safe unpacking of tar.gz/zip archives.
- `llm_server`: starts and stops llama-server, reports loading progress, falls back from GPU to CPU.
- `local_fix`: the stronger local prompt, chunking, retry, and calls to the OpenAI-compatible API.

Setup gains an `llm` item. The GUI gains a "Fix it here" path: download if needed, then load with progress, then fix with progress, then the existing `ReviewView`. Everything non-GUI is tested against a fake llama-server script that prints realistic log lines and serves `/health` and `/v1/chat/completions`.

**Tech Stack:** existing (Python 3.12, PySide6, httpx, pytest, pytest-qt); llama.cpp `b11539` prebuilt binaries (Vulkan / Metal / CPU); GGUF models from Hugging Face.

**Spec:** `docs/superpowers/specs/2026-10-24-desktop-gui-design.md` — §5.1, §5.2 (revised), §5.4. Stage 1 plan for existing interfaces: `docs/superpowers/plans/2026-10-24-stage1-linux-gui.md`.

## Global Constraints

- llama.cpp build pinned to **`b11539`**. Each archive is verified by the release's sha256, as listed in Task 2.
- GPU route is **Vulkan** on Windows and Linux and **Metal** on macOS arm64. No CUDA build. The **CPU build is always downloaded** and is the automatic fallback.
- Models: a single tier table (`llm_catalog.MODELS`, `choose_llm`). The user never sees a model list.
- `llama-server` listens on `127.0.0.1` only, on a free port picked by the app. It gets `--jinja` and no API key, and requests set `chat_template_kwargs: {"enable_thinking": false}`.
- Loading is never assumed fast. The progress UI must work for 10 s or 10 min alike.
- `llama-server` is stopped **before any transcription starts** and when the app closes. Otherwise it stays loaded for the session.
- The local prompt keeps §5.1's rules. Its worked example (Task 6) must not share sentences with any test transcript.
- Guardrails are shared with export (§5.3). The new rule: a proposal that drops a word without replacing it is rejected (`too_different`).
- The result and review screens say the local helper makes mistakes and that each change should be checked. The online route stays recommended.
- No technical words on the normal path. Strings go only through `I18n.tr`, with every key in `en` and `fa`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Orphaned llama-server**: the app closes, crashes, or starts a transcription while the helper is loading or answering. Expected: the server process is gone and VRAM is freed. Tests in Tasks 5 and 7.
2. **GPU build won't run** (no Vulkan driver, old GPU, or it crashes mid-load). Expected: automatic CPU retry with a plain message, no infinite loop. Tests in Task 5.
3. **Model answers badly**: chatter, missing lines, a different language, a `<think>` block, an empty answer, or an HTTP 500 mid-run. Expected: those chunks keep their originals, the fix finishes, and the summary says how many lines weren't answered. Tests in Task 6.
4. **Archive contents**: a tar/zip entry with `..`, an absolute path or a symlink that escapes the folder, or an executable bit lost on unpack. Expected: rejected, and `llama-server` stays runnable. Tests in Task 3.
5. **Not enough memory for the chosen model**: the server exits during load with an out-of-memory message. Expected: the plain message "not enough memory for the AI helper", with the online route offered. Tests in Task 5.

---

## File Structure

```
booktranscriber/
  llm_catalog.py   LLAMA_BUILD, RUNTIME_ASSETS, MODELS, choose_backend(), choose_llm()
  llm_sources.py   runtime_files(), model_file(), extract_archive(), runtime_dir(), server_binary()
  llm_server.py    LlamaServer (start/stop/is_ready/port), LOAD_STAGES, parse_stage(), LoadEstimator
  local_fix.py     LOCAL_PROMPT, chunk_lines(), fix_transcript()
  syscheck.py      + total_ram_bytes(); SystemInfo gains ram_bytes
  setup_runner.py  + "llm" item; SetupPlan gains include_llm, llm_model, llm_backend
  settings.py      + llm_model, llm_model_path, llm_backend, llm_load_seconds
  fixexport.py     + dropped-word guardrail
  i18n.py          + strings
  gui/runners.py   + LocalFixRunner (QThread: load → fix)
  gui/setup_view.py   + AI-helper checkbox and row
  gui/flow_view.py    + "Fix it here" enabled; local_requested signal
  gui/local_view.py   loading / fixing panel with progress + cancel
  gui/main_window.py  wiring; stop server before transcribing and on close
tests/fake_llama_server.py   test double for llama-server
```

---

### Task 1: Dropped-word guardrail

**Files:** Modify `booktranscriber/fixexport.py` (`_too_different`). Test: `tests/test_fixexport.py`.

**Interfaces:** Produces the same `apply_answer` signature, with stricter behaviour.

- [ ] **Step 1: Failing tests**

```python
def test_dropped_word_is_rejected():
    fixes = apply_answer(["یه چی بگیر بخوریم"], {1: "یه چی بخوریم"})
    assert fixes[0].reason == "too_different" and not fixes[0].accepted

def test_merged_words_still_allowed():
    assert apply_answer(["علی رزا نقاشه"], {1: "علیرضا نقاشه"})[0].reason == "fixed"

def test_replaced_word_still_allowed():
    assert apply_answer(["زندگیم با انقاشی میکنه"], {1: "زندگیم با نقاشی میکنه"})[0].reason == "fixed"
```

- [ ] **Step 2:** `venv/bin/python -m pytest tests/test_fixexport.py -q` → the first test FAILS.
- [ ] **Step 3:** In `_too_different`, also return True when `word_diff(a, b)` contains a `"removed"` run that is **not** immediately followed or preceded by an `"added"` run.
- [ ] **Step 4:** Run the whole suite → PASS.
- [ ] **Step 5:** Commit `Reject AI proposals that drop words`.

---

### Task 2: Catalog — build, runtime assets, model tiers, RAM

**Files:** Create `booktranscriber/llm_catalog.py`. Modify `booktranscriber/syscheck.py` (`ram_bytes` field, `total_ram_bytes()`). Tests: `tests/test_llm_catalog.py`, `tests/test_syscheck.py`.

**Interfaces:**
- Produces (`llm_catalog.py`):
  - `LLAMA_BUILD = "b11539"`; `RELEASE_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b11539/"`
  - `@dataclass(frozen=True) Asset(filename: str, size: int, sha256: str)`
  - `RUNTIME_ASSETS: dict[tuple[str, str], Asset]` keyed by `(os, backend)`, `backend ∈ {"vulkan","metal","cpu"}`. Exact values below.

    | key | filename | sha256 |
    |---|---|---|
    | ("linux","vulkan") | `llama-b11539-bin-ubuntu-vulkan-x64.tar.gz` | `c94e4cf093d38054e4b3384491b0948a659474a207149e65a12b9e5993498182` |
    | ("linux","cpu") | `llama-b11539-bin-ubuntu-x64.tar.gz` | `f2476a4337d2ab2efc4d845f40d362518b74442a4c9833a5e02d219f4c2086fb` |
    | ("windows","vulkan") | `llama-b11539-bin-win-vulkan-x64.zip` | `6f668beec2d159bb4cbb3b4407522c48e868571a9baf939ddcde46a548965bd7` |
    | ("windows","cpu") | `llama-b11539-bin-win-cpu-x64.zip` | `9895735aeef579aa46c356047f1e095ee6fcfe5558bd6b37ae83a7b4397d898e` |
    | ("macos","metal") | `llama-b11539-bin-macos-arm64.tar.gz` | `449f111de594ff5dfec7ac27d5b1233dd8a10a3e37ac1ceab9ce7d39d436ad32` |

    Sizes: take each `size` from the GitHub release API once (`GET https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b11539`) and hard-code it.
    macOS has no separate CPU asset: the Metal build runs on the CPU with `-ngl 0`, so `("macos","cpu")` maps to the same asset as Metal.
  - `@dataclass(frozen=True) LlmModel(key: str, repo: str, revision: str, filename: str, size: int, sha256: str, min_vram_mb: int, min_mac_ram_mb: int)`
  - `MODELS: dict[str, LlmModel]`:
    - `"gemma-4-e4b"`: repo `unsloth/gemma-4-E4B-it-GGUF`, revision `bfc15c382204943c3a8fff0c750b94ae2364d7a3`, file `gemma-4-E4B-it-IQ4_XS.gguf`, size `4715416704`, sha256 `0847f7300471e9a61abaeb46b45b3d61e393af8fa6d6aa70c563623773670dd9`
    - `"gemma-4-12b"`: repo `unsloth/gemma-4-12b-it-GGUF`, revision `fc034cfff751157913579611efad8462ac1be606`, file `gemma-4-12b-it-IQ4_XS.gguf`, size `6375734080`, sha256 `b0037d0e0de0290177045ca214b2a0fb1079d18bde57842b3ca32f5b0cd76774`
    - Tiers (spec §5.4): `"gemma-4-12b"` needs a GPU with ≥ 10 000 MB VRAM, or macOS with ≥ 24 GB RAM. `"gemma-4-e4b"` needs a GPU with ≥ 5 000 MB, or macOS with ≥ 12 GB RAM. Store these as `min_vram_mb` / `min_mac_ram_mb` fields instead of `min_ram_mb`.
  - `choose_backend(info: SystemInfo) -> str`: `"metal"` on macOS, otherwise `"vulkan"`. The CPU route is only a runtime fallback.
  - `choose_llm(info: SystemInfo) -> tuple[str | None, bool]`: `(model_key, recommended)`. It picks the largest model whose tier the machine meets. A machine meeting no tier gets `("gemma-4-e4b", False)` (downloadable, but the checkbox is unticked).
- Produces (`syscheck.py`): `total_ram_bytes() -> int` (Linux `os.sysconf`; Windows `GlobalMemoryStatusEx` via ctypes; macOS `sysctl -n hw.memsize`; 0 on failure). `SystemInfo` gains `ram_bytes: int = 0`, and `detect_system` fills it in.

- [ ] **Step 1: Failing tests:**
  - `test_runtime_assets_cover_every_os_backend`: keys ⊇ the five above; every `sha256` is 64 hex characters.
  - `test_choose_backend`: macos → metal; linux and windows → vulkan, with or without a GPU.
  - `test_choose_llm_tiers`: cases RTX 4050 (6141 MB) → ("gemma-4-e4b", True); 12 288 MB → ("gemma-4-12b", True); macOS 32 GB → ("gemma-4-12b", True); macOS 16 GB → ("gemma-4-e4b", True); macOS 8 GB → ("gemma-4-e4b", False); Linux without GPU, 64 GB RAM → ("gemma-4-e4b", False).
  - `test_total_ram_bytes_positive`: `> 0` on this machine.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `Add local AI catalog (pinned llama.cpp build, model tiers) and RAM detection`.

---

### Task 3: Sources and safe archive extraction

**Files:** Create `booktranscriber/llm_sources.py`. Test: `tests/test_llm_sources.py`.

**Interfaces:**
- Consumes: `llm_catalog.*`, `setup_sources.RemoteFile`, `paths`.
- Produces:
  - `runtime_dir(backend: str) -> Path` = `paths.data_dir()/"llm"/f"{LLAMA_BUILD}-{backend}"`
  - `server_binary(backend: str) -> Path | None`: the `llama-server` (`llama-server.exe` on Windows) found anywhere under `runtime_dir(backend)`, else None.
  - `runtime_files(os_name: str, backend: str) -> list[RemoteFile]`: the GPU asset plus the CPU asset (deduplicated on macOS), each with dest `paths.data_dir()/"llm"/"archives"/filename`.
  - `model_file(key: str) -> RemoteFile`: url `huggingface_hub.hf_hub_url(repo, filename, revision=revision)`, dest `paths.data_dir()/"llm"/"models"/filename`.
  - `extract_archive(archive: Path, dest: Path, cancel: threading.Event | None = None) -> None`:
    - Handles `.tar.gz` and `.zip`.
    - Rejects (skips) members with absolute paths, `..`, or links pointing outside `dest`. Uses `tarfile` `filter="data"`; for zip, checks paths manually.
    - Makes `llama-server` executable on POSIX.
    - Writes a `dest/".done"` marker last and deletes the archive afterwards.
    - Raises `DownloadCancelled` when cancelled.

- [ ] **Step 1: Failing tests** (build tiny archives in `tmp_path`):
  - `test_extract_tar_makes_server_executable`: a tar holding `llama-b11539/llama-server` with mode 0o644 → after extraction `os.access(path, os.X_OK)`, and `server_binary` finds it.
  - `test_extract_zip_windows_layout`: a zip holding `llama-server.exe` plus a dll → both extracted, `.done` marker present, archive deleted.
  - `test_extract_rejects_traversal_and_symlink_escape`: tar with `../evil` and a symlink `x -> /etc/passwd`; zip with `/abs/evil` → nothing written outside `dest`.
  - `test_extract_cancel_keeps_archive`.
  - `test_runtime_files_dedupes_macos`: `runtime_files("macos","metal")` has one entry; linux vulkan has two.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `Add local AI download sources and safe archive extraction`.

---

### Task 4: Setup integration

**Files:** Modify `booktranscriber/setup_runner.py`, `booktranscriber/settings.py`. Test: `tests/test_setup_runner.py`.

**Interfaces:**
- `ITEMS = ("check", "gpu", "whisper", "llm", "test")`
- `SetupPlan` gains `include_llm: bool = False`, `llm_model: str | None = None`, `llm_backend: str = "vulkan"`.
- `make_plan(info, existing, include_llm: bool | None = None)`:
  - `None` means "use the recommendation from `choose_llm`".
  - `needed_bytes` adds the model size plus the runtime archives (estimate 60 MB) when the helper is included.
- `Settings` gains `llm_model: str | None = None`, `llm_model_path: str | None = None`, `llm_backend: str | None = None`, `llm_load_seconds: float | None = None`.
- `run_setup`:
  - After the whisper downloads, if `plan.include_llm`: download `runtime_files` and `model_file` under item `"llm"`, then `llm_sources.extract_archive` each runtime archive into `runtime_dir(backend)` (or into `runtime_dir("cpu")` for the CPU archive).
  - Set the settings fields.
  - The self-test is unchanged; the LLM is not tested in setup, because its load time is long and is shown at first use.
- New helper `run_llm_setup(model_key: str, backend: str, settings: Settings, on_progress, cancel, *, downloader=download_file) -> Settings`: the same llm steps on their own, used for "download later" (Task 7).

- [ ] **Step 1: Failing tests** (extending the stage 1 fakes):
  - `test_plan_includes_llm_when_recommended`
  - `test_run_setup_downloads_llm_and_sets_settings`: fake downloads write tiny archives and model; assert `settings.llm_model_path` exists and `llm_backend == "vulkan"`.
  - `test_run_setup_without_llm_skips_it`
  - `test_disk_check_includes_llm`
  - `test_run_llm_setup_alone`
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `Download the local AI helper during setup`.

---

### Task 5: llama-server manager with loading progress and CPU fallback

**Files:** Create `booktranscriber/llm_server.py` and `tests/fake_llama_server.py`. Test: `tests/test_llm_server.py`.

**Interfaces:**
- `LOAD_STAGES: list[tuple[str, float]]`, matched in order against stderr lines (substring) and mapped to a fraction:
  - `"load_model: loading model"` → 0.05
  - `"llama_model_loader: loaded meta data"` → 0.15
  - `"load_tensors: loading model tensors"` → 0.25
  - `"model buffer size"` → 0.30
  - `"llama_context:"` → 0.80
  - `"KV buffer size"` → 0.85
  - `"warming up the model"` → 0.90
  - `"all slots are idle"` → 1.0
- `parse_stage(line: str, current: float) -> float`: returns the highest matching fraction ≥ `current`.
- `class LoadEstimator(previous_seconds: float | None)`:
  - `fraction(stage_fraction: float, elapsed: float) -> float` = `max(stage_fraction, min(0.97, elapsed / previous_seconds))` when `previous_seconds` is known, else `stage_fraction`.
  - `eta(elapsed) -> float | None`.
- `class LlmStartError(Exception)` with `.kind ∈ {"memory","crash","timeout","missing"}`.
- `class LlamaServer`:
  - `__init__(binary: Path, model: Path, gpu: bool, ctx: int = 8192)`
  - `start(on_progress: Callable[[float, float | None], None], cancel: threading.Event, timeout: float = 1800) -> None`
    - Spawns with `-m model -c ctx --host 127.0.0.1 --port <free> --jinja`. On the GPU route no `-ngl` is passed, so llama-server fits layers to free memory itself (spec §5.4); on the CPU route it passes `-ngl 0`. On Windows it uses `CREATE_NO_WINDOW`.
    - Reads stderr in a thread and polls `/health` every 0.5 s until `{"status":"ok"}`.
    - On process exit before ready it raises `LlmStartError`: kind `"memory"` if the stderr tail contains `out of memory`, `ErrorOutOfDeviceMemory`, `failed to allocate` or `unable to allocate`; else `"crash"`.
    - On cancel it kills the process and raises `DownloadCancelled`.
  - `port: int`, `is_ready() -> bool`, `stop() -> None` (terminate, then kill after 5 s; idempotent), `load_seconds: float | None`.
- `start_with_fallback(settings: Settings, on_progress, cancel, on_fallback: Callable[[], None]) -> LlamaServer`:
  - Tries the GPU binary first.
  - On a `"crash"` start error, or a missing GPU binary, it calls `on_fallback()` and retries `server_binary("cpu")` with `gpu=False`.
  - `"memory"` raises without retrying (the CPU route needs at least as much memory).
  - Stores the measured `load_seconds` into `settings.llm_load_seconds`.
- `tests/fake_llama_server.py <mode> --port N ...`: prints scripted log lines with delays and serves `/health` (503 until ready, then ok) and `/v1/chat/completions` (echo mode: returns the input lines unchanged; `fix` mode replaces `انقاشی` → `نقاشی`). Modes: `ok`, `slow`, `oom`, `crash`, `hang`, `http500`, `think`.

- [ ] **Step 1: Failing tests:**
  - `test_parse_stage_monotonic`
  - `test_estimator_uses_previous_duration`
  - `test_start_reports_progress_and_ready` (fake `ok`): progress values non-decreasing and ending at 1.0; `is_ready()`.
  - `test_oom_is_memory_kind`
  - `test_crash_falls_back_to_cpu_once`: GPU fake `crash`, CPU fake `ok` → `on_fallback` called once and server ready.
  - `test_cancel_during_load_kills_process`
  - `test_stop_is_idempotent_and_frees_port`
  - `test_no_orphan_after_owner_dies`: start, then delete the `LlamaServer` object and call `stop()` via `atexit`-registered cleanup → process gone.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Register every started server in a module-level `weakref.WeakSet` and stop them all in an `atexit` handler.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `Add llama-server manager with stage-based loading progress and CPU fallback`.

---

### Task 6: Local fixer

**Files:** Create `booktranscriber/local_fix.py`. Test: `tests/test_local_fix.py`.

**Interfaces:**
- `LOCAL_PROMPT: str`, the system prompt.
  - Same rules as §5.1, plus: "These lines DO contain such errors"; keep colloquial Persian; "If a line is fine, return it unchanged".
  - Worked example (exact):
    - Input: `[1] دیروز رفتیم کطابخونه و یه رمان از داستایوسکی گرفطیم` / `[2] نویسندش خیلی معرفه` / `[3] آره خب`
    - Output: `[1] دیروز رفتیم کتابخونه و یه رمان از داستایفسکی گرفتیم` / `[2] نویسندش خیلی معروفه` / `[3] آره خب`
  - Names line `"- Correct spellings of names: …"` only when names are given.
- `LINES_PER_REQUEST = 15`
- `chunk_lines(lines: list[str], per: int = LINES_PER_REQUEST) -> list[list[int]]`: 1-based numbers of non-empty lines.
- `fix_transcript(lines: list[str], names: list[str], port: int, on_progress: Callable[[int, int], None], cancel: threading.Event, client: httpx.Client | None = None) -> list[LineFix]`
  - Posts `{"messages":[system, user], "temperature":0.2, "max_tokens":4096, "chat_template_kwargs":{"enable_thinking":False}}`.
  - Strips any `<think>…</think>` before `parse_answer`.
  - A chunk missing lines gets one retry with only the missing lines; after that they stay missing.
  - An HTTP error marks that chunk missing and continues.
  - Ends with `apply_answer(lines, answer)`.

- [ ] **Step 1: Failing tests** against `fake_llama_server` (started via a `LlamaServer` fixture in `ok`/`fix`/`think`/`http500` modes):
  - `test_fix_mode_fixes_and_keeps_rest`
  - `test_think_block_is_ignored`
  - `test_http500_chunk_kept_original_and_others_fixed`
  - `test_missing_lines_retried_once`
  - `test_cancel_stops_between_chunks`
  - `test_prompt_example_does_not_overlap_test_transcript`: no 3-word sequence of the example appears in the shared test fixture text.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `Add local transcript fixer`.

---

### Task 7: GUI — setup checkbox, "Fix it here", loading/fixing panel, lifecycle

**Files:**
- Create `booktranscriber/gui/local_view.py`.
- Modify `gui/runners.py` (`LocalFixRunner`), `gui/setup_view.py`, `gui/flow_view.py`, `gui/main_window.py`, `i18n.py`.
- Test: `tests/gui/test_local_fix_gui.py`.

**Interfaces:**
- `class LocalFixRunner(QObject)`:
  - Signals: `load_progress(float, object)` (fraction, eta or None), `fallback()`, `fix_progress(int, int)`, `finished(object)` (`list[LineFix]`), `failed(str)` (kind ∈ `memory`, `crash`, `timeout`, `missing`, `cancelled`, `unknown`).
  - Methods: `start(raw_lines, names, settings)`, `cancel()`, `stop_server()`, `is_running()`, `server_loaded() -> bool`.
  - Keeps the `LlamaServer` between jobs.
- `class LocalView(QWidget)`:
  - Loading state: title `local.loading.title` ("Loading the AI helper…"), body `local.loading.body` ("This can take a few minutes. You can keep using your computer."), a progress bar, time left when known, and Cancel.
  - Fallback note: `local.fallback` ("The graphics card didn't work for this, so the AI helper is using the processor instead. It will be slower.").
  - Fixing state: `local.fixing` ("Fixing… part {i} of {n}") with a bar.
  - Errors: memory → `local.err.memory` with an "Use ChatGPT / Claude / Gemini instead" button that emits `export_instead`; others → `local.err.generic` plus Try again.
  - Signals: `review_ready(object)`, `export_instead()`, `back()`.
- `SetupView` welcome screen:
  - Adds the checkbox `setup.llm_box` ("Also download the AI helper (recommended)") with the note `setup.llm_note`.
  - Ticked by default iff `choose_llm(info)[1]`; when unticked by default it shows `setup.llm_weak` ("This computer may be slow with the AI helper. You can still use ChatGPT instead.").
  - The `llm` row in downloading.
- `FlowView` result step:
  - "Fix it here (private)" is enabled.
  - Its subtitle: `result.local_hint` ("A first pass on your computer. It makes mistakes — check each change.").
  - When `settings.llm_model_path` is missing, the button reads `result.local_download` ("Download the AI helper ({size}) and fix") and runs `run_llm_setup` with an inline progress bar, then continues.
  - New signal `local_requested(str, list, str)`, same shape as `export_requested`.
- `ReviewView`: when opened from the local route, shows banner `review.local_banner` ("Made by the AI helper on your computer. Check each change.").
- `MainWindow`:
  - Calls `local_runner.stop_server()` **before** every `transcriber.start` (in `FlowView._run`, via an injected `before_transcribe` callable).
  - `closeEvent` stops it too, and `busy()` includes `local_runner.is_running()`.

- [ ] **Step 1: Failing tests** (pytest-qt, with `LocalFixRunner` driven by `fake_llama_server` through monkeypatched `server_binary`):
  - `test_setup_llm_checkbox_follows_recommendation`
  - `test_local_button_opens_loading_then_review`
  - `test_loading_bar_moves_and_shows_eta_second_time`: `settings.llm_load_seconds` set → ETA label visible.
  - `test_fallback_note_shown`
  - `test_memory_error_offers_export`
  - `test_server_stopped_before_new_transcription`: start local fix → `server_loaded()`; begin a new transcription → server process gone before `transcriber.start` is called.
  - `test_close_stops_server`
  - `test_download_then_fix_when_missing`
  - `test_review_banner_for_local_route`
  - i18n keys-match test still passing.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5: 👤 Owner checkpoint.**
  1. `./run-gui.sh` → Settings → Check / repair → tick the AI helper → setup downloads it.
  2. Transcribe the 5-minute clip → Fix it here → loading bar → review. Untick the bad fixes and save.
  3. Start another transcription right away and check that `nvidia-smi` shows no llama-server.
- [ ] **Step 6:** Commit `Add "Fix it here" with loading progress, CPU fallback and lifecycle`.

---

### Task 8: Docs and verification

**Files:** Modify `README.md` (desktop section: AI helper, first-pass caveat, loading time) and spec §5.4 (final tier table).

- [ ] **Step 1:** Update the README and spec.
- [ ] **Step 2:** `venv/bin/python -m pytest tests -q` → all pass.
- [ ] **Step 3: Real run.** Use `BT_DATA_DIR=<scratch>/bt2` and drive `run_llm_setup`, then `start_with_fallback`, then `fix_transcript` from a scratch script on the 5-minute transcript.
  - Expected: Vulkan load with progress reaching 1.0, and fixes comparable to §5.4.
  - Then run the same with the Vulkan runtime dir renamed. Expected: `on_fallback` called and the CPU build answers.
- [ ] **Step 4:** Commit `Document the local AI helper`.
