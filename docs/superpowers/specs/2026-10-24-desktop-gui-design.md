# Book Transcriber desktop app: design

Date: 2026-10-24 · Status: draft for approval

## 1. Intent

Book-club members record their sessions, which are mostly in Persian, and want a clean text version.
Today that takes a terminal, a Python venv and `./run.sh`, which only the
project owner can manage. The goal is a **desktop app that someone who is not comfortable with
computers can install and use alone**: drop in a recording, optionally list a few names, wait,
and get a transcript whose misheard words and names have been fixed.

Privacy stays a core value. Transcription always runs on the user's own machine. The text
leaves the machine only if the user deliberately pastes it into an online AI.

## 2. Goals, non-goals, anti-goals

**Goals**
- GUI only for end users on **Windows, macOS and Ubuntu**, with a normal installer per OS.
  Users never see a terminal or console window, and no command is ever typed.
- A **first-run setup** that checks the machine and downloads only what it needs: the GPU
  libraries, the Whisper model and, optionally, an AI model for fixing. It shows live,
  resumable progress.
- A home screen with **one big "drop your recording" area** that guides through optional seed names,
  transcription progress, the fix step, and review and save.
- An **AI fix** that corrects misheard words and names. It works in one of two ways:
  1. a local model downloaded by the app (offline and private), or
  2. a ready-to-paste export for ChatGPT, Claude or Gemini, with a box to paste the corrected text back in.
- **Persian and English UI**, switchable. It starts in the OS language and has a فا / EN toggle. Persian is laid out right to left.
- **The existing CLI keeps working**, with the same flags and the same output filenames.

**Non-goals (v1)**
- Mobile phones and tablets.
- A server, client/server mode, or accounts.
- Speaker labels (who said what), audio editing, live recording inside the app.
- Output formats other than UTF-8 `.txt`.
- Calling cloud AI APIs from inside the app. The export/paste flow covers online AIs.

**Anti-goals (a failure even if it "works")**
- **The AI changes meaning.** It rephrases, summarizes, "improves" style, removes or adds
  sentences, or merges or splits lines. The fix may touch **only misheard words and names**.
- The user faces a technical decision (model names, CUDA, quantization) or a technical
  error message on the normal path.
- Audio or text is uploaded anywhere without the user explicitly doing it themselves.
- The local AI makes transcripts *worse* on average and the app still recommends it.

## 3. Constraints

- **Hardware reference:** the owner's laptop has an RTX 4050 with **6 GB of VRAM**. large-v3 at fp16 and a
  4–8B quantized LLM **do not both fit**. Whisper and the LLM must therefore run one after the other, and
  Whisper's process must end before the LLM loads.
- **macOS has no CUDA.** faster-whisper runs only on the CPU there, which is very slow.
- **An installed app can't write next to its own binary.** All downloaded and user data goes in the
  per-user data directory.
- The current `transcribe.py` has **side effects at import time**: it calls `os.execv` to set
  `LD_LIBRARY_PATH` on Linux and `add_dll_directory` on Windows. A GUI process or a frozen app
  can't re-exec itself, so this has to be restructured (see §6.1).
- Native crashes have happened before (the `faulthandler`/`.transcribe_fault.txt` setup exists for that reason). A crash in the
  engine must never take the window down.

## 4. User experience

### 4.1 First-run setup (shown once)
Mockups: `.superpowers/brainstorm/*/content/setup-flow.html`.

1. **Welcome.** "Before your first transcript, the app needs to download a few things.
   This happens only once." It shows the result of the computer check in plain words
   ("works well, NVIDIA graphics card found"), the estimated time, and the space needed against the space free. There is
   **one checkbox**: *Also download the AI helper (recommended)*, ticked by default only if the
   machine can run it well. Otherwise it is unticked, with the note "This computer may be slow with the AI
   helper. You can still use ChatGPT instead." Then one button: **Start download**.
2. **Downloading.** One **Overall** bar (percent and time left), and below it a row per item:
   checking computer → graphics-card support → speech-to-text model → AI helper → quick test.
   The active row shows its own bar and the MB/GB downloaded. A **Pause** button is available. The note "If the internet
   drops, it will continue where it stopped" is shown.
3. **Ready.** "All set! From now on the app works without internet." Then the button
   **Transcribe my first recording →**.

Errors are friendly, with one obvious action:
- lost internet: "nothing is lost, 2.1 GB saved", **Try again**
- not enough space: **Skip AI helper** / **Check again**
- GPU libraries fail: "Continue without graphics card (slower)?"

**Settings → Check / repair** re-runs the setup check later. The AI helper can also be
downloaded later in one click from the result screen.

### 4.2 Main flow (layout C, chosen by the owner)
Mockup: `.superpowers/brainstorm/*/content/main-layout.html`, option C.

- **Home:** a large drop area ("Drop your recording here", or **Choose a file…**) and a short
  list of recent transcripts. Each opens its result screen.
- After a file is dropped, each next step **appears in place, one at a time**, with no
  Back/Next wizard:
  1. **Names (optional).** "Any names in this recording? Book titles, authors, characters.
     This helps spell them right." A multi-line box (one name per line, RTL-aware),
     **Load saved list ▾**, a **Save this list as…** checkbox, and the buttons **Skip** and **Continue**. Saved
     lists replace `prompts/*.txt` for GUI users, and the existing `prompts/*.txt` files can be imported.
  2. **Transcribing.** A progress bar, time left, and a **Cancel** button. The raw text appears live as it is
     produced.
  3. **Fix mistakes.** Two big choices:
     - **Fix it here (private)**, using the local AI helper. If it isn't downloaded yet, one
       click downloads it with the same progress UI.
     - **Prepare for ChatGPT / Claude / Gemini**: see §5.3.
     - The user can also skip the fix and just save the raw text.
  4. **Review and save.** Raw and corrected text side by side, line aligned, with changed words
     highlighted. Each changed line can be reverted with one click. **Save**, **Copy**, and
     **Open folder** buttons are available.
- **Advanced** (collapsed and never needed): language, Whisper model (large-v3 / large-v3-turbo),
  timestamps, device. The defaults are fa, large-v3 (turbo when VRAM is low or the GPU is missing), no timestamps, and auto device.

### 4.3 Language
All UI strings are translatable in Persian and English. The app starts in the OS language (Persian if
the locale is `fa`, otherwise English), and a فا / EN switch in the corner changes it live and remembers the choice. In Persian
the whole layout is mirrored (Qt `RightToLeft`). Transcript text views are always RTL when the
transcript language is Persian, whatever the UI language.

## 5. AI fix

### 5.1 Rules (shared by local and export)
The prompt and the guardrails both enforce: **fix only misheard words and proper names. Never
change meaning, wording style, word order, or sentence boundaries. Never add, remove, merge,
or split lines.** The prompt includes the seed names as the authoritative spelling of names.
Filler words and colloquial speech are kept.

### 5.2 Local AI helper
- **Runtime:** a prebuilt **`llama-server`** binary from llama.cpp releases, downloaded during
  setup in the build that matches the machine (CUDA on NVIDIA, Vulkan on other Win/Linux GPUs, Metal on
  Apple Silicon, CPU otherwise). It runs as a subprocess on `127.0.0.1` with a random port. *(Builder's
  call, my recommendation: avoid bundling GPU builds of `llama-cpp-python`, which is the
  packaging trap.)*
- **Model:** one GGUF model is chosen automatically from VRAM and RAM. The user never sees a model
  list. Candidates are Gemma 3 and Qwen3 at roughly 4B for ≤6 GB VRAM and roughly 12B / 8B where it fits.
  *Final choice is the builder's after evaluation (below).*
- **Line protocol:** send numbered lines with timestamps stripped and require the same numbered lines back.
  Chunks are sized to the model's context with room left for output, since Persian uses many tokens per
  word. The previous chunk's last few lines are included as read-only context.
- **Guardrails:** any line where the response is missing, malformed, or edited more than a
  misheard-word fix would plausibly need (an edit-distance ratio threshold, for example) **keeps the original
  line**. A wrong line count for a chunk means one retry, then that chunk keeps its originals.
- **Memory:** the LLM starts only after the Whisper process has ended. `llama-server` is stopped when the fix
  finishes or is cancelled.
- **Acceptance test:** on at least one of the owner's real Persian transcripts, the local fix
  must not make it worse, judged by the owner. If no candidate model passes on a given hardware tier,
  that tier's checkbox defaults to unticked and the result screen recommends the export route.

### 5.3 Export for an online AI
- **Prepare for ChatGPT / Claude / Gemini** splits the transcript into numbered parts sized for a
  chat message. Each part begins with the same instructions (§5.1 rules plus the seed names). For each part
  the user can **Copy part N** or **Save all parts** as `.txt` files.
- A short how-to is shown in the UI language: open the AI, paste part 1, copy its answer back, and repeat.
- A **Paste corrected text** box for each part (or one box for everything) brings the answers back. The app re-aligns lines
  using the line numbers, applies the same guardrails as §5.2, and opens the review screen.
- This route needs no download and always works, even on weak machines.

## 6. Architecture

### 6.1 Engine module (shared by the CLI and the GUI)
- Move the transcription logic into a package (for example `booktranscriber/engine.py`) with **no
  import-time side effects**.
- GPU library discovery becomes an explicit function. It preloads the CUDA `.so`/`.dll` files by full
  path (for example `ctypes.CDLL(path, RTLD_GLOBAL)` on Linux, `add_dll_directory` on Windows) before
  ctranslate2 loads, so neither the GUI nor the frozen app needs to re-exec.
- `transcribe.py` becomes a thin CLI over the engine, with the **same flags, defaults, output filenames
  (`<name> - متن خام.txt`) and progress file**. `run.sh`, `run.bat`, `setup.sh` and `setup.bat` keep working.
- The decoding parameters already tuned (beam 5, `condition_on_previous_text=False`, temperature
  ladder, compression and no-speech thresholds, VAD 500 ms) carry over unchanged.

### 6.2 Process model
- The **GUI** is PySide6 (Qt). *(My call: native on all three OSes, good RTL/bidi support, and it reuses the
  Python engine directly.)*
- **Transcription runs in a child process**, not a thread. The child streams JSON lines (progress, segment text,
  done, error) over stdout. Cancel kills the child. A native crash becomes a friendly error with
  "Try again" / "Use CPU instead" instead of killing the window.
- The **LLM** runs in a separate `llama-server` child process (§5.2).
- **Downloads** (models, GPU libraries, `llama-server`) run in a worker with resumable HTTP range
  requests, checksum or size verification, and per-item and overall progress. Hugging Face downloads use
  `huggingface_hub`, which has resume support, wired to the progress UI.

### 6.3 Engines per platform
| Platform | Engine | Notes |
|---|---|---|
| Windows / Ubuntu + NVIDIA | faster-whisper on CUDA | CUDA wheels (`nvidia-cublas`, `nvidia-cudnn`) are **downloaded during setup**, not bundled, so the installer stays small |
| Windows / Ubuntu without NVIDIA | faster-whisper on CPU (int8) | defaults to large-v3-turbo; setup warns that it is slow |
| macOS Apple Silicon | **mlx-whisper** | it lacks faster-whisper's `vad_filter` and some decoding options, so **Persian quality and anti-repetition behaviour must be verified separately** before macOS ships |
| macOS Intel | faster-whisper on CPU | best-effort (untested) |

### 6.4 Data locations
Everything lives in the per-user data directory (`platformdirs`):
- models
- GPU libraries
- `llama-server`
- saved name lists
- recent transcripts index
- settings (UI language)
- logs

On first run the app **detects an existing `./models/` from a CLI checkout and offers to reuse it**,
so the owner doesn't download 2.9 GB again. Transcripts are saved next to the audio by default (same as
the CLI): `<name> - متن خام.txt` and `<name> - متن اصلاح‌شده.txt` *(corrected filename is my call)*.
If that folder isn't writable, the app asks where to save.

### 6.5 Packaging
- **PyInstaller**, windowed (no console), one build per OS. *(My call.)*
- Installer formats:
  - Windows: an installer `.exe` (for example Inno Setup), with Start menu entry and uninstaller
  - macOS: `.dmg` containing the `.app`
  - Ubuntu: `.deb` and/or AppImage with a desktop entry
- The installer contains the app and Python dependencies **without** CUDA libraries or models. Those come during the
  first-run setup.
- Builds are produced by CI (GitHub Actions) on each OS runner. *(My call.)*

### 6.6 Releases on GitHub (owner's request)
- When the owner pushes a version tag (for example `v1.0.0`), GitHub Actions builds the installers on Windows, macOS and
  Ubuntu runners and **publishes them as a GitHub Release** on `javadtavakoli/book-transcriber`.
  Each release has the installer files, checksums, and short release notes in Persian and English.
- The README gets a simple **Download** section that links to the latest release, with one plain
  line per OS ("Windows: download `…-Setup.exe` and double-click it").
- Releases are published as **drafts first**. The owner reviews them and presses Publish. *(My call: nothing goes
  public by accident.)*
- In the app, **Settings → About** shows the version, and a quiet "A new version is available,
  Download" notice appears when the GitHub Releases API reports a newer tag. It only links to
  the release page and does not auto-update. *(My call.)*

## 7. Delivery order

Each stage is usable on its own and gets its own plan:

1. **Engine extraction + Linux GUI.** Engine module, thin CLI, child-process transcription, first-run setup
   (GPU libraries + Whisper model), home → names → transcribe → **export for online AI** → review and save,
   فا/EN UI. Runs from source on Ubuntu.
2. **Local AI helper.** `llama-server` download, model auto-selection, the line protocol with guardrails, the
   acceptance test on real transcripts, and the AI helper checkbox in setup.
3. **Windows.** Installer, DLL handling in the frozen app, CI build, and the **tag → draft GitHub Release**
   workflow (§6.6) set up here with the first installer.
4. **Ubuntu packaging.** `.deb`/AppImage, added to the release workflow.
5. **macOS.** mlx-whisper engine, Persian quality check, `.dmg`, added to the release workflow.

## 8. Testing
- Unit tests: line protocol and alignment, guardrail thresholds, export chunking and re-import,
  progress-line parsing, data-dir migration of `./models/`.
- A short bundled test clip is used by the setup's "quick test" step and by an automated smoke test.
- Manual acceptance per OS: a non-technical tester installs the app and transcribes one real recording with no help.

## 9. Left to the builder
- Exact LLM model, quantization and VRAM tiers, chosen after the §5.2 acceptance test.
- Chunk sizes for local and export, and the edit-distance threshold.
- The bundled test clip, icons, visual styling (following the mockups' simplicity), app name in Persian
  (mockups use «کتاب‌نویس», a placeholder).
- Diff/highlight implementation and the recent-transcripts storage format.

## 10. Owner decisions
- **Unsigned builds.** No Apple Developer ID and no Windows code-signing certificate. The release notes and README
  Download section therefore include short illustrated "first time opening" steps, in Persian and English:
  - **macOS:** right-click the app → **Open** → **Open**, or *System Settings → Privacy & Security →
    Open Anyway*.
  - **Windows:** on the SmartScreen warning, click **More info** → **Run anyway**.
  - The setup's Welcome screen does not depend on these steps, because they happen before the app runs.
- **Test machines:** the owner has a Windows PC and an **Apple Silicon Mac**. macOS on Apple Silicon is
  therefore fully supported and tested. Intel Macs remain best-effort.
