# Stage 3: Windows installer, download location and GitHub Releases

Builds on `2026-10-24-desktop-gui-design.md`, which defines stage 3 as §7.3 and covers packaging in
§6.5 and releases in §6.6. This document records what the owner decided in the stage 3 conversation
on 2026-10-25, and what is still open. Where the two documents disagree, this one wins.

## 1. Intent

The owner's book-club friends are not comfortable with computers. They should be able to download one
file from GitHub, double-click it, and get a working app on Windows, with no Python, no terminal and no
admin password. Stage 3 turns the Linux-from-source app from stages 1–2 into that Windows product. It
also sets up the release pipeline that stages 4 (Ubuntu) and 5 (macOS) will add to.

Success means two things:
- The owner installs the draft release's installer on their own Windows PC and transcribes one real
  recording.
- They fix it with the local AI helper, without touching anything technical.

## 2. Goals
1. **Name and icon.** The app is called **Writing Parrot**, «طوطی‌نویس» in Persian (owner's decision).
   That name is used everywhere a user can see it: the window title, the installer, the Start menu, the
   uninstall list and the README. The icon is a simple **parrot holding a pen** (owner accepted). It
   must read well at 16×16 and at 256×256.
2. **Windows installer** `WritingParrot-Setup-<version>.exe`:
   - Built with PyInstaller in windowed mode, then Inno Setup.
   - Unsigned, as the owner already decided.
   - Adds a Start menu entry, an optional desktop icon, and an entry in the Windows uninstall list.
3. **Users choose where the big downloads go** (owner's decision). See §4.
4. **The frozen app works on Windows**, with no difference from running from source:
   - The transcription worker child process and its JSON-line output.
   - CUDA DLLs downloaded during setup.
   - The llama-server subprocess.
   - Persian file paths.
5. **Stage-2 items deferred to "the Windows stage"** are finished here:
   - **Crash cleanup on Windows.** `llm_server.reap_stale()` is currently a no-op there. On Windows it
     should stop a leftover llama-server, with the same rule that it only kills the recorded binary,
     never a process that reused the pid.
   - **The test suite on Windows.** The fake llama-server launcher in tests is POSIX-only. Fix that and
     anything else that fails on Windows, then make the `windows-2022` CI job **required**: remove its
     `continue-on-error`.
   - **AMD and Intel graphics cards.** Detect them, with their video memory, so the AI-helper tier
     (spec §5.4) picks a sensible model on them. Today only `nvidia-smi` is queried.
   Rules (my calls, after the builder check):
   - Only **dedicated** video memory counts toward the tier. An integrated GPU (Intel iGPU, AMD APU)
     never counts shared system memory, so it lands in the "anything else" tier (E4B, unticked). The
     Vulkan build is still tried first when the helper runs.
   - A non-NVIDIA GPU never triggers the CUDA download and never counts for picking large-v3, because
     CUDA is NVIDIA-only. Whisper runs on the CPU there, as today.
6. **Release pipeline.** Pushing a `v*` tag builds the Windows installer on GitHub Actions and creates a
   **draft** GitHub Release on `javadtavakoli/book-transcriber`. The draft holds:
   - The installer.
   - `SHA256SUMS.txt`.
   - Short release notes in Persian and English, with the illustrated SmartScreen step: **More info** →
     **Run anyway**.

   The owner reviews the draft and presses Publish.
7. **README Download section.** One plain line per OS, linking to the latest release. Windows is the only
   OS available in this stage.
8. **About and new-version notice** (spec §6.6, my call to include it here, since releases start in this
   stage):
   - Settings → About shows the version.
   - A quiet "A new version is available — Download" link appears when GitHub's latest *published*
     release has a higher version.
   - It is checked at most once a day and never blocks or nags. If there is no internet, nothing is
     shown. There is no auto-update.

## 3. Non-goals and anti-goals
- **Non-goals:**
  - Code signing, Microsoft Store, winget.
  - Auto-update.
  - Installers for Ubuntu or macOS (stages 4 and 5).
  - Intel Macs.
  - A Windows ARM build.
  - Bundling models or CUDA in the installer: they still download during first-run setup, so the
    installer stays small.
- **Anti-goals (failures even if the build "works"):**
  - The installer asks for an admin password, or a UAC prompt appears for a normal install.
  - A console window flashes when the app starts, transcribes, runs the self-test or starts the AI
    helper.
  - A release becomes public without the owner pressing Publish.
  - A user who picks D:\ for downloads still ends up with gigabytes on C:.
  - Uninstalling silently leaves gigabytes behind, or deletes a folder the user picked that contains
    other files.
  - The CLI (`transcribe.py`, `run.bat`, `setup.bat`) stops working from a source checkout. It stays.

## 4. Download location (owner's decision; details are my calls unless marked)

**Two folders.** The app's data splits into two places:
- **App folder:** stays in the usual per-user place, `platformdirs.user_data_dir("WritingParrot")`,
  which is `%LOCALAPPDATA%\WritingParrot` on Windows. It holds the small things:
  - `settings.json` and `recents.json`
  - the name lists
  - logs
  - the llama-server pid file
  - the saved location of the downloads folder
- **Downloads folder:** the big things: `models/` (Whisper), `gpu/` (CUDA wheels), and `llm/` (runtimes
  and the AI model). The default is the app folder.

**`paths.py`:**
- Gains a downloads root, read from the settings, plus the `BT_DATA_DIR` override that the tests rely on.
- `models_dir()`, `gpu_dir()` and the llm dirs resolve under it.
- Everything that today calls these keeps working unchanged.

**First-run setup screen** (owner accepted the shape):
- It shows "Save downloads on: `<path>` — `<N> GB free`  [Change…]".
- Change… opens a native folder picker. The folder must be writable.
- The free-space check that already exists (`detect_system(target_dir)` and `SetupError` disk-space
  handling, including "Skip AI helper") runs against the chosen folder's drive.
- If the user picks a drive root such as `D:\`, the app adds a `WritingParrot` subfolder inside it. The
  same applies to any non-empty folder. The app never fills or later deletes a folder that holds the
  user's other files.

**Default suggestion:**
- C: (the app folder) when it has room for the planned downloads.
- If it doesn't, and another fixed drive does, that drive's `\WritingParrot` is suggested, with one plain
  sentence saying why, for example "Your C: drive is nearly full, so downloads will go on D:".
- Removable drives are allowed when picked by hand, but never suggested.

**Changing it later: Settings → "Downloads folder" → Change…**
- The app offers to **move** what is already downloaded, with a progress bar and Cancel.
- The move is safe:
  1. Copy everything to the new place.
  2. Verify the copy (size, and the sha256s already used by setup where available).
  3. Switch the saved location.
  4. Only then delete the old copy.
- Cancel or failure leaves the old location in use and removes the partial copy.
- The move is not allowed while a transcription or AI fix is running. The AI helper is stopped first.
- If the user declines the move, the location switches and setup's Check/repair downloads what is
  missing.
- If the saved downloads folder is missing at start (an unplugged USB drive, for example), the app says
  so in one sentence. It offers "Try again" (after plugging it back in) or "Choose another folder", which
  runs the normal setup there.

**Rename migration (my call):** the app was called BookTranscriber in stages 1–2. On the first run of the
new version, if `user_data_dir("BookTranscriber")` exists and `user_data_dir("WritingParrot")` does not,
the app renames the old folder. Rename, not copy: this only matters to the owner's machines. It also
still offers to reuse a source checkout's `./models/` (spec §6.4).

## 5. Windows build and installer

**Installed without admin rights** (my call: no UAC prompt for non-technical users):
- A per-user install (`PrivilegesRequired=lowest`) into `{localappdata}\Programs\Writing Parrot`.
- The Start menu entry is "Writing Parrot". The desktop icon is an optional checkbox, ticked by default.
- The installer and the uninstaller use Persian and English. English is used if Inno Setup's Persian
  translation is not usable.

**Uninstaller (my call):**
- It removes the program, then asks one question: "Also delete the downloaded speech and AI files
  (`<size>`) at `<path>`?" The answer defaults to **No**.
- It reads the downloads location from a small value the app keeps up to date at
  `HKCU\Software\WritingParrot\DownloadsDir`, because Inno Setup reads the registry easily.
- It deletes only the app's own subfolders (`models`, `gpu`, `llm`) and the folder itself if it is then
  empty. It never deletes the user's files.
- The same "Yes" also removes settings, recents and logs. It **keeps the user's name lists**
  (`namelists/`), because the user typed them (my call, after the builder check). The app folder is
  removed only if it is then empty.

**Version and naming:**
- The version comes from `booktranscriber.__version__`, which is currently `0.1.0`. The first release
  is `v0.1.0`.
- The release workflow fails if the tag and `__version__` disagree.
- The installer's AppId is a fixed GUID, so later versions upgrade in place.

**Frozen-app traps the builder must handle:**
- **Worker output.** The worker is the same exe run with `--worker` (`worker.worker_command`). In a
  PyInstaller *windowed* build, `sys.stdout` can be `None` in that child even when the parent passes a
  pipe. Worker events must still reach the GUI. One fix is to rebind stdout to the inherited handle;
  another is a separate console-mode worker exe started with `CREATE_NO_WINDOW`. The builder picks.
- **CUDA DLLs.** The CUDA wheels are downloaded into the downloads folder. Their DLL folders must be
  registered (`add_dll_directory` / `PATH`) in the worker before ctranslate2 loads.
- **Bundled data.** PySide6 plugins, ctranslate2 and PyAV DLLs, faster-whisper's bundled assets (for
  example the VAD model), i18n, and the test clip used by setup's quick test must all be present.
- **Persian paths.** Persian characters in the install path, the downloads path and the audio path must
  work in both processes.

**CI smoke test of the built app:**
- It runs on the Windows runner, without models or a GPU, after PyInstaller.
- At minimum:
  - The GUI exe starts offscreen and exits cleanly.
  - `--worker` with a bad audio path returns the expected JSON error event through a pipe, which proves
    the worker-output trap above is handled.
  - ctranslate2, av and PySide6 import inside the frozen app.

## 6. Workflows
- **`.github/workflows/ci.yml` (exists):**
  - Make `windows-2022` required once its tests pass.
  - macOS stays report-only until stage 5.
- **New `.github/workflows/release.yml`:**
  - Triggers: a `v*` tag push, and manual `workflow_dispatch`. The manual run builds and uploads the
    installer as a workflow artifact, with no release (my call: the owner gets a test build without
    making a release).
  - Steps:
    1. Run the tests.
    2. Check the tag against the version.
    3. Build with PyInstaller.
    4. Run the smoke test.
    5. Build with Inno Setup.
    6. Write `SHA256SUMS.txt`.
    7. Create or update a **draft** release holding the files and the notes template.
  - `contents: write` only on the release job.
  - Pin action versions.
  - Stages 4 and 5 add jobs to this same workflow.
- **Pushing:** the release workflow file must be pushed with the **javadtavakoli** account, never
  arlert-armin. Its token has the `workflow` scope.

## 7. Left to the builder
- How AMD and Intel GPUs are detected, and how their video memory is read. Options:
  - `Win32_VideoController` (its `AdapterRAM` caps at 4 GB, so it is not enough on its own).
  - The registry `HardwareInformation.qwMemorySize`.
  - DXGI.
  - Asking the downloaded Vulkan llama-server for its devices.
- How `reap_stale` checks a process's command line on Windows. No new heavy dependency is allowed
  without a reason.
- The PyInstaller spec details: one-folder or one-file. One-folder is likely better for startup time
  and antivirus false positives.
- The icon artwork and the `.ico` sizes.
- Release-notes wording and the SmartScreen screenshot.
- How the tests exercise the move and the downloads-location logic, which is mostly testable without
  Windows.

## 8. Owner checkpoints (stage end)
1. Download the draft release's installer on the Windows PC and run it. Confirm:
   - the SmartScreen step matches the notes,
   - there is no admin prompt,
   - the Start menu entry and icon are present.
2. On first launch, choose a folder on another drive, finish setup with the AI helper, and confirm that
   C: did not grow by gigabytes.
3. Transcribe a real recording, use Fix it here, and save. Confirm that no console windows appear.
4. Settings → move the downloads to another folder, then transcribe again.
5. Uninstall, answering No once and Yes once (reinstalling in between), and check what remains.
6. Press Publish on the draft when happy.
