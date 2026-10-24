# Stage 3: Windows installer, download location and releases — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Writing Parrot as an unsigned, no-admin Windows installer built by a tag-triggered draft GitHub
Release. Users can put the big downloads on any drive.

**Architecture:** `paths.py` splits into an *app folder* (small files) and a *downloads folder* (models, CUDA
wheels, AI helper). The downloads folder is read from `settings.json` and mirrored to the Windows registry for
the uninstaller. On Windows, llama-server runs inside a Job Object so it can never outlive the app. A PyInstaller
one-folder build plus an Inno Setup per-user installer are produced by `.github/workflows/release.yml`. That
workflow also smoke-tests the frozen app.

**Tech Stack:**
- Python 3.12 and PySide6 6.12.0.
- pytest 9.1.1 and pytest-qt 4.5.0, run headless with `QT_QPA_PLATFORM=offscreen`.
- ctypes for the Win32 calls; no new runtime dependency.
- PyInstaller 6.x, pinned in `requirements-build.txt`.
- Inno Setup 6 (preinstalled on `windows-2022` runners; otherwise installed with `choco install innosetup`).
- GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-25-stage3-windows-design.md`. Base spec:
`docs/superpowers/specs/2026-10-24-desktop-gui-design.md`.

## Global Constraints
- **Names:**
  - English: `Writing Parrot`. Persian: `طوطی‌نویس`, with a zero-width non-joiner U+200C between طوطی and نویس.
  - Folder and registry name: `WritingParrot`.
  - Installer file: `WritingParrot-Setup-<version>.exe`.
- **Version:** from `booktranscriber.__version__`, currently `"0.1.0"`. The tag is `v` + that version.
- **No admin:** the installer uses `PrivilegesRequired=lowest` and installs to `{localappdata}\Programs\Writing Parrot`.
- **No console window:** none may ever appear on Windows. Every child process (worker, nvidia-smi, llama-server,
  any helper) is started with `CREATE_NO_WINDOW`.
- **Registry:** the app mirrors the downloads folder to `HKCU\Software\WritingParrot`, value `DownloadsDir` (REG_SZ).
- **Uninstaller:**
  - It asks "Also delete the downloaded speech and AI files (`<size>`) at `<path>`?", defaulting to **No**.
  - Yes deletes only `models`, `gpu` and `llm` inside the downloads folder, plus settings.json, recents.json and
    logs. It **keeps `namelists/`**. Each folder is removed only if empty.
- **GPU rules:**
  - A non-NVIDIA GPU never triggers the CUDA download and never selects large-v3.
  - Only *dedicated* video memory counts toward the AI-helper tier.
  - A GPU with under 2048 MiB dedicated memory is treated as integrated: no tier, so `gpu=None` for the tier logic.
- **Kept working:** the CLI (`transcribe.py`, `run.sh`, `run.bat`, `setup.*`, `run-gui.*`) keeps working from a
  source checkout.
- **Tests:**
  - Isolated by the autouse `BT_DATA_DIR` fixture (tests/conftest.py).
  - No test may touch the real registry. Registry writes go through a function the tests monkeypatch.
- **Git:**
  - Commits are authored as javadtavakoli (the repo's git config already is).
  - Pushes are done by the controller only, with the javadtavakoli token (see memory `github-push-account`).
    Implementer subagents never push.
- **Copy:** UI text lives in `booktranscriber/i18n.py`. Every new key gets both `en` and `fa`;
  `tests/test_i18n.py` already checks parity.

## Review Focus
1. **Persian in paths.** A downloads folder or install path containing Persian or spaces, e.g.
   `D:\کتاب ها\Writing Parrot`, must work in the worker child, llama-server and the registry mirror.
   Task 4 tests the move with such a name. Task 7's smoke test runs the frozen worker from a Persian-named temp
   folder.
2. **Picking a folder with other files in it, or a drive root.** The app must put a `WritingParrot` subfolder
   inside it, never fill it directly, and never delete those files on a move or uninstall. Task 4:
   `test_choose_target_*`; Task 8: the uninstaller deletes only named subfolders.
3. **A move interrupted by Cancel, a full target drive or an unplugged drive.** The old location must stay in use
   and complete. Task 4: `test_move_cancel_keeps_old` and `test_move_copy_error_keeps_old`.
4. **The saved downloads folder missing at start.** For example, a USB drive that isn't plugged in. The app must say
   so and must not "re-setup" silently onto C:. Task 5: `test_missing_downloads_folder_prompts`.
5. **Stored absolute model paths after a move.** `whisper_model_path` and `llm_model_path` in settings must follow
   the move. A `whisper_model_path` that points into a source checkout's `./models` is left alone. Task 4:
   `test_move_rewrites_model_paths`.

---

### Task 1: Windows test suite green; llama-server can't outlive the app on Windows

The first GitHub run (`gh run view 40130774441`) failed 12 tests on `windows-2022`:
- **All of `tests/test_llm_server.py` that check a pid died, and 4 in `tests/gui/test_local_fix_gui.py`.** The test
  fake on Windows is a `.cmd` launcher, so `proc.terminate()` kills `cmd.exe` and leaves the Python child running.
- **`tests/test_engine.py::test_corrected_path_follows_raw_location`.** The test hard-codes `/`.

**Files:**
- Modify: `booktranscriber/llm_server.py` (Popen site ~L266, `_stop_process` ~L107, `_command_line` / `_alive` /
  `_kill` / `reap_stale` ~L150–223)
- Create: `booktranscriber/winjob.py`
- Modify: `tests/test_engine.py:21-23`
- Modify: `.github/workflows/ci.yml:25-27` (`continue-on-error` only for macOS)
- Test: `tests/test_winjob.py` (skipped off Windows), plus the existing `tests/test_llm_server.py`

**Interfaces:**
- Produces, in `booktranscriber/winjob.py` (Windows-only internals; every function is a harmless no-op returning
  `None`/`False` elsewhere):
  - `create_kill_on_close_job() -> int | None`: a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. The app
    keeps the handle open for its lifetime. When the app dies, even by a crash, Windows kills everything in the
    job.
  - `assign(job: int, pid: int) -> bool`
  - `terminate_tree(job: int) -> None`: `TerminateJobObject`.
  - `image_path(pid: int) -> str | None`: `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` +
    `QueryFullProcessImageNameW`.
  - `alive(pid: int) -> bool`: `GetExitCodeProcess == STILL_ACTIVE (259)`.
  - `kill(pid: int) -> None`: `TerminateProcess`.
- Consumes: nothing new.

- [ ] **Step 1: Fix the test.** In `tests/test_engine.py`, build both expected paths with `os.path.join` (e.g.
  `os.path.join("/docs", "جلسه - متن خام.txt")` → `os.path.join("/docs", "جلسه - متن اصلاح‌شده.txt")`).
  `engine.corrected_path_for` itself is correct.
- [ ] **Step 2: Write `tests/test_winjob.py`** (`pytestmark = pytest.mark.skipif(sys.platform != "win32", ...)`):
  - `test_job_kills_child_tree`: start `cmd /c python -c "import time; time.sleep(60)"` with `CREATE_NO_WINDOW`
    and assign it to a new job. Find the Python grandchild with a small `wmic`-free check: have the grandchild
    write its pid to a temp file. Then `terminate_tree(job)` and assert `alive(grandchild_pid)` turns False
    within 5 s.
  - `test_image_path_of_self`:
    `os.path.normcase(image_path(os.getpid())) == os.path.normcase(sys.executable)`.
  - `test_off_windows_noops` (not skipped, its own module-level guard inverted): on non-Windows,
    `create_kill_on_close_job() is None`.
- [ ] **Step 3: Implement `booktranscriber/winjob.py`** with ctypes (`kernel32`: `CreateJobObjectW`,
  `SetInformationJobObject` with `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` (class 9), `AssignProcessToJobObject`,
  `TerminateJobObject`, `OpenProcess`, `QueryFullProcessImageNameW`, `GetExitCodeProcess`, `TerminateProcess`,
  `CloseHandle`). Set `argtypes` and `restype` on each call, so 64-bit handles aren't truncated.
- [ ] **Step 4: Wire it into `llm_server.py` on Windows:**
  - **One job per server:** created in `start`, the process assigned to it right after `Popen`, and
    `_stop_process` ending it with `winjob.terminate_tree` and closing the handle in `stop`.
  - `_command_line` on Windows returns `[image_path(pid)]`. `_is_server` on Windows compares
    `os.path.normcase(os.path.realpath(...))` of that image with the recorded binary.
  - `_alive` / `_kill` dispatch to `winjob` on Windows.
  - Remove the `os.name != "posix"` early-return in `reap_stale`.
  - Update the docstring "Not on Windows yet".
- [ ] **Step 5: Make the Windows fake reapable.** The fake launcher's image is `cmd.exe` or `python.exe`, never
  the recorded `.cmd` path, so the existing reap tests would be skipped or wrong on Windows. Skip only the
  reap-matches-binary tests on Windows (`@pytest.mark.skipif(sys.platform == "win32", reason="the fake runs as
  python.exe; image-path matching is covered in test_winjob")`). Add to `test_winjob.py`:
  - `test_reap_stale_kills_recorded_image`: write a pid file for a sleeping `python.exe` child, with
    `binary=sys.executable`. Assert `reap_stale()` is True and the child dies.
  - `test_reap_stale_ignores_other_image`: the same, but with `binary` pointing at a different exe path. Assert
    False, and the child is alive.
- [ ] **Step 6: Run** `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests -q -p no:cacheprovider`.
  Expected: all pass on Linux (315 + new ones, with the Windows-only ones skipped).
- [ ] **Step 7: CI.** Change `continue-on-error` to `${{ matrix.os == 'macos-14' }}` and update the comment.
- [ ] **Step 8: Commit.** `git commit -m "Windows: llama-server in a kill-on-close job; reap on Windows; tests green"`.

*(Controller, after this task: push the branch and run `gh run watch`. Windows failures get fix rounds before
Task 2 starts.)*

### Task 2: Rename to Writing Parrot, icon, data-folder migration

**Files:**
- Modify:
  - `booktranscriber/paths.py` (`APP_NAME = "WritingParrot"`, `OLD_APP_NAME = "BookTranscriber"`)
  - `booktranscriber/__init__.py` docstring
  - `booktranscriber/i18n.py`: `app.title` is `"Writing Parrot"` / `"طوطی‌نویس"`. Replace every user-visible
    "Book Transcriber" / «کتاب‌نویس» in both languages; check with grep.
  - `booktranscriber/gui/app.py`
  - `booktranscriber/gui/setup_view.py:52`: the welcome icon shows the app icon pixmap (96 px) instead of the
    emoji.
  - `README.md` title and intro
- Create:
  - `booktranscriber/assets/icon.svg`
  - `tools/make_icons.py`: renders the svg to `booktranscriber/assets/icon.png` (256) and
    `booktranscriber/assets/icon.ico` (16, 24, 32, 48, 64, 128, 256), using PySide6 `QSvgRenderer`.
  - The generated png and ico, committed.
- Test: `tests/test_paths.py`, `tests/gui/test_app_icon.py`

**Interfaces:**
- Produces:
  - `paths.migrate_old_data_dir() -> bool`: True if the old folder was renamed.
  - `paths.asset(name: str) -> Path`: works from source and frozen, via `sys._MEIPASS` when frozen.

- [ ] **Step 1: Tests in `tests/test_paths.py`:**
  - `test_migrate_renames_old_folder`: monkeypatch `paths._platform_data_dir` (new helper:
    `(app_name) -> Path`, wrapping `platformdirs.user_data_dir(app_name, appauthor=False)`) to map both names into
    `tmp_path`. Create the old folder with `settings.json`, unset `BT_DATA_DIR`, call `migrate_old_data_dir()`.
    Assert True, the new folder has `settings.json`, and the old one is gone.
  - `test_migrate_skips_when_new_exists`: both exist. Assert False and both untouched.
  - `test_migrate_skips_with_bt_data_dir`: `BT_DATA_DIR` set. Assert False.
  - `test_asset_exists`: `paths.asset("icon.ico").is_file()` and `paths.asset("icon.png").is_file()`.
- [ ] **Step 2: Run the tests.** They fail.
- [ ] **Step 3: Implement.**
  - `migrate_old_data_dir` uses `os.rename` and swallows `OSError` (returns False).
  - `gui/app.py` calls it before `load_settings`.
  - It also sets `app.setApplicationName("Writing Parrot")` and `app.setWindowIcon(QIcon(str(paths.asset("icon.png"))))`.
  - On Windows it sets the AppUserModelID `"WritingParrot.App"` via
    `ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID`, inside try/except, so the taskbar shows the
    icon.
- [ ] **Step 4: Draw the icon.**
  - A flat parrot head and shoulder in green, yellow and red, holding a dark pen in its beak or claw, on a
    rounded-square light background.
  - It must stay recognisable at 16 px, so use bold shapes and no thin strokes.
  - Hand-written SVG, about 60 lines max.
  - Run `./venv/bin/python tools/make_icons.py`, then view the 256 png with the Read tool to check that it
    reads as a parrot with a pen. Iterate if it doesn't.
- [ ] **Step 5:** `tests/gui/test_app_icon.py::test_window_has_icon`: after building the `MainWindow`,
  `QApplication.windowIcon().isNull()` is False when `app.main`'s icon setup function
  (`apply_app_identity(app)`, factored out) has run.
- [ ] **Step 6: Run the full suite** (it passes), then
  `grep -rn "Book Transcriber\|کتاب‌نویس" booktranscriber README.md`. Expected: no user-visible hits; the
  package name `booktranscriber` stays.
- [ ] **Step 7: Commit.** `"Rename the app to Writing Parrot (طوطی‌نویس) with a parrot-and-pen icon"`.

### Task 3: Detect AMD and Intel graphics; GPU rules

**Files:**
- Modify: `booktranscriber/syscheck.py`, `booktranscriber/setup_runner.py:62` (`include_gpu`)
- Test: `tests/test_syscheck.py`, `tests/test_setup_runner.py`, `tests/test_llm_catalog.py`

**Interfaces:**
- Produces:
  - `GpuInfo(name: str, vram_mb: int, vendor: str = "nvidia")`. Vendor is `"nvidia" | "amd" | "intel" | "other"`.
  - `syscheck.is_nvidia(info: SystemInfo) -> bool`.
  - `syscheck.parse_windows_adapters(entries: list[dict]) -> GpuInfo | None`. Each entry is a dict with
    `DriverDesc`, an optional `HardwareInformation.qwMemorySize` (int bytes), an optional
    `HardwareInformation.MemorySize` (int or bytes, little-endian), and an optional `MatchingDeviceId`. It
    picks the adapter with the most dedicated memory. Adapters under `INTEGRATED_MAX_MB = 2048` count as
    absent (None).
  - `syscheck.parse_amdgpu_sysfs(cards: dict[str, int]) -> GpuInfo | None`, Linux, from
    `/sys/class/drm/card*/device/mem_info_vram_total`.
- Detection order in `detect_system`:
  1. `nvidia-smi` first (unchanged).
  2. Then, on Windows, the registry under
     `HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000..`.
  3. Then, on Linux, amdgpu sysfs.
  4. The vendor comes from the PCI id in `MatchingDeviceId`: `VEN_10DE` nvidia, `VEN_1002` amd, `VEN_8086` intel.
     Without it, from the name.

- [ ] **Step 1: Tests:**
  - `test_parse_windows_adapters_picks_dedicated`: Intel UHD (128 MiB) plus a Radeon RX 7600 (qwMemorySize
    8 GiB) → `GpuInfo("AMD Radeon RX 7600", 8192, "amd")`.
  - `test_integrated_only_is_none`: Intel Iris Xe with 128 MiB → None.
  - `test_memorysize_fallback_bytes`: only a 4-byte little-endian `MemorySize` of 4 GiB−1 → `vram_mb` 4095.
  - `test_parse_amdgpu_sysfs`.
  - `test_make_plan_amd_no_cuda`: an AMD 8 GiB GPU → `plan.include_gpu is False` and `whisper_model ==
    "large-v3-turbo"`.
  - `test_choose_llm_amd_8gb_gets_e4b_recommended`: → `("gemma-4-e4b", True)`.
  - `test_nvidia_unchanged`: the existing behaviour.
- [ ] **Step 2: Run.** They fail.
- [ ] **Step 3: Implement.**
  - `include_gpu = info.os != "macos" and is_nvidia(info)`.
  - `choose_whisper_model` requires `is_nvidia`.
  - The registry read uses `winreg`, guarded by `sys.platform == "win32"`, and swallows `OSError`.
  - The setup welcome line `setup.check.gpu_ok` shows any detected GPU's name, so an AMD card shows too. Add the
    key `setup.check.gpu_no_cuda` ("Graphics card: {gpu}. Speech recognition will use the processor; the AI
    helper can use the graphics card.", plus Persian) and use it in `setup_view._update_welcome` when the GPU is
    not NVIDIA.
- [ ] **Step 4: Run the full suite.** Expected: it passes.
- [ ] **Step 5: Commit.** `"Detect AMD and Intel graphics cards; CUDA only on NVIDIA"`.

### Task 4: Downloads folder: paths, choosing a folder, safe move

**Files:**
- Modify:
  - `booktranscriber/paths.py`
  - `booktranscriber/settings.py`: add `downloads_dir: str | None = None`.
  - `booktranscriber/llm_sources.py:15-16` and `booktranscriber/gpu.py:31`: use the downloads root.
  - `booktranscriber/setup_runner.py:215`: the free space comes from `paths.downloads_dir()`.
- Create: `booktranscriber/downloads.py`
- Test: `tests/test_downloads.py`, `tests/test_paths.py`

**Interfaces:**
- Produces in `paths.py`:
  - `downloads_dir_path() -> Path`: `settings.json`'s `downloads_dir` if set (read directly from JSON, no import
    of `settings`, and tolerant of a missing or broken file), else `data_dir_path()`.
  - `downloads_dir() -> Path`: creates it.
  - `models_dir()` and `gpu_dir()` now live under `downloads_dir()`.
  - New `llm_dir() -> Path`, under `downloads_dir()`. `llm_sources._llm_dir` and the gpu.py root use it.
  - The llama-server pid file stays in the **app folder**: `data_dir() / "llm" / "server.pid"`, unchanged.
- Produces in `booktranscriber/downloads.py`:
  - `DOWNLOAD_SUBDIRS = ("models", "gpu", "llm")`.
  - `FOLDER_NAME = "WritingParrot"`.
  - `choose_target(picked: Path) -> Path`:
    - Returns `picked` if it is empty, or already looks like ours (contains any of `DOWNLOAD_SUBDIRS` or a
      `.writingparrot` marker file).
    - Otherwise returns `picked / FOLDER_NAME`. A drive root is never empty in practice, and the rule covers it.
  - `writable(folder: Path) -> bool`: creates the folder and a temp file, then deletes the temp file.
  - `downloads_size(root: Path) -> int`: total bytes under `DOWNLOAD_SUBDIRS`.
  - `suggest_default(needed_bytes: int, drives: list[tuple[Path, int, bool]] | None = None) -> tuple[Path, str | None]`:
    - `drives` is `(root, free_bytes, removable)`. When None, it is enumerated: on Windows via
      `GetLogicalDrives` + `GetDriveTypeW` (DRIVE_FIXED=3; removable=2); elsewhere `[]`.
    - It returns `(paths.data_dir_path(), None)` when the app folder's drive has `needed_bytes` free.
    - Otherwise it returns the first fixed non-system drive with room, as `drive / FOLDER_NAME`, with reason
      `"c_full"`.
    - If none has room, it returns `(data_dir_path(), None)`; the normal space error then shows.
  - `set_downloads_dir(settings: Settings, folder: Path) -> None`:
    - Writes `settings.downloads_dir` and saves settings.
    - Drops a `.writingparrot` marker in the folder.
    - Calls `mirror_to_registry(folder)`.
  - `mirror_to_registry(folder: Path) -> None`: writes `HKCU\Software\WritingParrot\DownloadsDir` on Windows
    only, and swallows `OSError`. The tests monkeypatch it.
  - `MoveProgress(done: int, total: int)` dataclass.
  - `move_downloads(settings: Settings, new_root: Path, progress: Callable[[MoveProgress], None], cancel: threading.Event) -> None`:
    1. Raise `MoveError("space", needed, free)` if the target lacks `downloads_size` × 1.05.
    2. Copy each of `DOWNLOAD_SUBDIRS` with 1 MiB chunks, reporting progress and checking `cancel` between
       chunks.
    3. Verify that each copied file's size matches.
    4. Rewrite `settings.whisper_model_path` / `llm_model_path` if they are under the old root (`Path.is_relative_to`).
    5. `set_downloads_dir`.
    6. Delete the old `DOWNLOAD_SUBDIRS`.

    On cancel (raise `MoveCancelled`) or any `OSError` (raise `MoveError("copy", ...)`), it deletes what it copied
    into the new root and leaves settings untouched. Same-drive moves still copy (simple and uniform).
  - `MoveError(kind: str, needed: int = 0, free: int = 0)` and `MoveCancelled` exceptions.

- [ ] **Step 1: Tests in `tests/test_downloads.py`** (the autouse fixture; registry monkeypatched to record calls):
  - `test_default_downloads_is_app_folder`
  - `test_downloads_dir_from_settings`: set `downloads_dir`. Then `paths.models_dir()` and `paths.llm_dir()` are
    under it, and `paths.settings_file()` is not.
  - `test_broken_settings_falls_back`
  - `test_choose_target_empty_folder_used_directly`
  - `test_choose_target_nonempty_gets_subfolder`: a folder with `photo.jpg` → `.../WritingParrot`.
  - `test_choose_target_ours_reused`
  - `test_suggest_default_c_full_picks_other_fixed_drive`: the injected drives list; the app folder's drive
    reported by monkeypatching `shutil.disk_usage`. Removable drives are skipped.
  - `test_move_copies_verifies_switches_deletes`: a fake `models/x/model.bin` (3 MiB) and `llm/models/a.gguf`
    (2 MiB). After the move, the files exist under the new root, the old subdirs are gone, `downloads_dir`
    points at the new root, and the registry mock was called with it.
  - `test_move_rewrites_model_paths`: `whisper_model_path` under the old root is rewritten. One under an
    unrelated `/checkout/models` is unchanged.
  - `test_move_cancel_keeps_old`: cancel after the first progress callback. Raises `MoveCancelled`; the old
    files are intact; the new root has no `models`; settings are unchanged.
  - `test_move_copy_error_keeps_old`: monkeypatch the chunk copy to raise `OSError(28, "No space")` midway.
    `MoveError("copy")` is raised, with the same guarantees.
  - `test_move_persian_path`: the new root is `tmp_path / "کتاب ها" / "Writing Parrot"`.
  - `test_move_space_check`: monkeypatch `shutil.disk_usage` for the target to return a tiny free value.
    Raises `MoveError("space")` before anything is copied.
- [ ] **Step 2: Run.** They fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** Expected: it passes. Existing tests that build paths from `BT_DATA_DIR`
  still work, because the default downloads root is the app folder.
- [ ] **Step 5: Commit.** `"Downloads folder separate from the app folder, with a safe move"`.

### Task 5: Downloads folder in the GUI

**Files:**
- Modify:
  - `booktranscriber/gui/setup_view.py`: the welcome page; `refresh()` uses
    `detect_system(self.downloads_target)`.
  - `booktranscriber/gui/main_window.py`: the ⚙ menu gets "Downloads folder…" and "About" (About itself comes
    in Task 6); a missing-folder check runs at start.
  - `booktranscriber/i18n.py`
- Create: `booktranscriber/gui/downloads_dialog.py`
- Test: `tests/gui/test_downloads_gui.py`

**Interfaces:**
- Consumes: Task 4's `downloads.*`, `paths.downloads_dir_path()`.
- Produces:
  - `SetupView.downloads_target: Path`. The folder chosen on the welcome page, applied with
    `downloads.set_downloads_dir` when Start is pressed (before downloading).
  - `DownloadsDialog(i18n, settings, parent)`: a `QDialog` showing the current folder and its size, with
    Change…. After a pick, it asks "Move the downloaded files (N GB) there?" with Move / Don't move / Cancel.
    Move runs `move_downloads` in a `QThread`, with a progress bar and Cancel.
  - `MainWindow.check_downloads_folder() -> None`.
- Folder pickers go through a `pick_folder(parent, start: Path) -> Path | None` module function. It wraps
  `QFileDialog.getExistingDirectory`, and the tests monkeypatch it.

- [ ] **Step 1: Tests:**
  - `test_welcome_shows_location_and_free`: the label text contains the path and "free" in en.
  - `test_change_picks_subfolder_and_rechecks_space`: monkeypatch `pick_folder` to return a non-empty folder.
    `downloads_target` becomes `<folder>/WritingParrot`, and the space line was recomputed with
    `detect_system` on it (monkeypatched to return 1 TB free → Start enabled).
  - `test_unwritable_pick_shows_message`: `writable` is monkeypatched False → an inline red message, and the
    target is unchanged.
  - `test_c_full_suggestion_explained`: `suggest_default` is monkeypatched to return `(D, "c_full")` → the
    explanation sentence is visible.
  - `test_start_applies_downloads_dir`: after `start()`, `settings.downloads_dir == str(target)`.
  - `test_move_dialog_moves`: with fake files, a pick, and Move → wait until done (qtbot); the files are at the
    new place.
  - `test_move_blocked_while_busy`: `MainWindow.busy()` is True → the menu action shows the "Finish or cancel
    the current work first" message and opens no dialog.
  - `test_missing_downloads_folder_prompts`: `settings.downloads_dir` points to a non-existent path, with
    `setup_done=True`. `check_downloads_folder()` shows a message with "Try again" and "Choose another
    folder" (driven through a monkeypatched `ask_missing(...) -> str` hook). "choose" sets the new folder and
    opens setup; "retry" re-checks.
  - The helper is stopped before a move: `local_runner.stop_server` (or whatever `_free_graphics_card` calls)
    is called.
- [ ] **Step 2: Run.** They fail.
- [ ] **Step 3: Implement.**
  - New i18n keys (en + fa), at minimum:
    - `setup.location` ("Save downloads on: {path} — {free} free")
    - `setup.location.change`
    - `setup.location.c_full`
    - `setup.location.unwritable`
    - `downloads.title`, `downloads.current`, `downloads.move_q`, `downloads.move`, `downloads.dont_move`,
      `downloads.moving`, `downloads.done`, `downloads.failed_space`, `downloads.failed_copy`
    - `downloads.missing`, `downloads.retry`, `downloads.choose`
    - `busy.finish_first` (if not already present)
  - Persian must be natural, not literal.
  - On "Don't move": `set_downloads_dir` only, then `open_repair()` so setup downloads what is missing.
  - `app.py` calls `check_downloads_folder()` after `w.show()`.
- [ ] **Step 4: Run the full suite.** Expected: it passes.
- [ ] **Step 5: Commit.** `"Choose where downloads go, and move them later from Settings"`.

### Task 6: About and the new-version notice

**Files:**
- Create: `booktranscriber/updates.py`, `booktranscriber/gui/about_dialog.py`
- Modify:
  - `booktranscriber/gui/main_window.py` (About action; a quiet notice label in the top bar, hidden by default)
  - `booktranscriber/settings.py` (`last_update_check: float | None = None`)
  - `booktranscriber/i18n.py`
- Test: `tests/test_updates.py`, `tests/gui/test_about.py`

**Interfaces:**
- `updates.RELEASES_API = "https://api.github.com/repos/javadtavakoli/book-transcriber/releases/latest"`.
  (`/latest` only returns published, non-draft, non-prerelease releases.)
- `updates.RELEASES_PAGE = "https://github.com/javadtavakoli/book-transcriber/releases/latest"`.
- `updates.parse_version(tag: str) -> tuple[int, ...] | None`: `"v0.1.10"` → `(0, 1, 10)`; anything else → None.
- `updates.newer_version(current: str, latest_tag: str) -> str | None`.
- `updates.check_latest(client: httpx.Client | None = None, timeout=5) -> str | None`:
  - Returns the latest tag, or None on any error.
  - Uses `trust_env=True`: unlike the localhost client, a user's proxy is wanted here.
  - Sends `User-Agent: WritingParrot/<version>`.
- `updates.due(settings, now: float) -> bool`: once per 24 h.
- `MainWindow` runs the check in a background thread at start if it is due, and stores `last_update_check`.
  If there is a newer version, a small link label "A new version is available — Download" opens
  `RELEASES_PAGE`.

- [ ] **Step 1: Tests:**
  - parse and compare cases: `v0.2.0` > `0.1.0`; `v0.1.0` is not newer; `garbage` → None.
  - `check_latest` with `httpx.MockTransport` returning `{"tag_name": "v0.2.0"}` → `"v0.2.0"`; a 404 → None; a
    `ConnectError` → None.
  - `due` boundaries.
  - GUI: `test_about_shows_version` (the dialog text contains `__version__` and the app name).
  - GUI: `test_update_notice_shown_when_newer`: monkeypatch `updates.check_latest`, then trigger and wait. The
    label is visible.
  - GUI: `test_no_notice_offline`.
- [ ] **Step 2: Run.** They fail.
- [ ] **Step 3: Implement.**
  - About: the app name in the current language, the version, one line ("Transcribes recordings on your own
    computer."), a link to the GitHub page, and the license (MIT, from LICENSE; check the file).
  - i18n keys: `about.title`, `about.body`, `update.available`.
  - In tests, the conftest must stop the real network check. Add an autouse fixture in `tests/conftest.py`
    that monkeypatches `booktranscriber.updates.check_latest` to return None, unless a test overrides it.
- [ ] **Step 4: Run the full suite.** Expected: it passes.
- [ ] **Step 5: Commit.** `"About window and a quiet new-version notice"`.

### Task 7: Frozen app (PyInstaller) and its smoke test

**Files:**
- Create:
  - `packaging/writing_parrot.spec` (PyInstaller, one-folder, windowed, icon `booktranscriber/assets/icon.ico`,
    name `WritingParrot`, entry `packaging/entry.py`)
  - `packaging/entry.py`: `from booktranscriber.__main__ import main; sys.exit(main())`, plus
    `multiprocessing.freeze_support()`.
  - `packaging/smoke_test.py`
  - `requirements-build.txt` (`pyinstaller==<latest 6.x at time of writing; check pip index versions pyinstaller>`)
- Modify:
  - `booktranscriber/worker.py` (`main`: the frozen-windowed stdout fix)
  - `booktranscriber/__main__.py` (a `--smoke` flag for the GUI self-check)
- Test: `tests/test_worker.py`, plus the smoke script run by CI

**Interfaces:**
- **Worker stdout.** `worker.ensure_stdio() -> None`. If `sys.stdout` or `sys.stderr` is None (a PyInstaller
  windowed child), rebind them to the inherited OS handles: `os.fdopen(1/2, "w", encoding="utf-8",
  buffering=1)` when `os.get_osfhandle(1)` works on Windows. Otherwise use `open(os.devnull, "w")` for stderr.
  `main()` calls it first.
- **GUI self-check.** `python -m booktranscriber --smoke`, or the frozen `WritingParrot.exe --smoke`:
  - It creates `QApplication` with the offscreen platform set by the caller and builds `MainWindow`.
  - It imports `ctranslate2`, `av`, `faster_whisper` and `httpx`.
  - It prints `SMOKE OK <version>` to a file given by `--smoke-out PATH` (a windowed exe has no visible stdout),
    then exits 0.
- **`packaging/smoke_test.py <dist_dir>`:**
  1. Copies the dist folder into a temp dir named `طوطی تست` (Review Focus 1).
  2. Runs `WritingParrot.exe --smoke --smoke-out <file>` with `QT_QPA_PLATFORM=offscreen` and checks that the
     file says `SMOKE OK`.
  3. Runs `WritingParrot.exe --worker --audio <missing.wav> --out <x> --model large-v3` through a pipe, with
     `CREATE_NO_WINDOW`, and asserts a JSON line with `"type": "error"` and `"kind": "not_found"` arrives within
     60 s.

  It exits non-zero on any failure.
- **Spec file.**
  - It collects data and binaries for `faster_whisper` (its `assets/` VAD model), `ctranslate2`, `av`,
    `PySide6` (only the QtCore, QtGui, QtWidgets and QtSvg plugins needed), `tokenizers` and `huggingface_hub`.
  - It includes `booktranscriber/assets/*`.
  - It excludes the CUDA wheels (`nvidia`), `tkinter` and `pytest`.
  - `console=False`, `upx=False` (antivirus false positives).
- **`paths.asset`** (Task 2) must resolve in the frozen build. The smoke test proves it, because `MainWindow`
  loads the icon.
- **CUDA DLLs.** The frozen worker reads them from `paths.gpu_dir()` via `gpu.default_lib_dirs` and
  `BT_DLL_DIRS`, exactly as from source. `site_nvidia_roots()` finds nothing frozen, which is fine.

- [ ] **Step 1: Test** `tests/test_worker.py::test_ensure_stdio_rebinds_none`: monkeypatch `sys.stdout = None`,
  call `ensure_stdio()`, and `sys.stdout` is not None and writable. Restore the stream afterwards.
- [ ] **Step 2: Test** `tests/test_app_smoke.py::test_smoke_flag_writes_ok`: run
  `[sys.executable, "-m", "booktranscriber", "--smoke", "--smoke-out", f]` with `QT_QPA_PLATFORM=offscreen` and
  `BT_DATA_DIR` set. Exit code 0, and the file starts with `SMOKE OK`.
- [ ] **Step 3: Implement, then run** both tests and the full suite. Expected: they pass.
- [ ] **Step 4: Build locally on Linux** as a sanity check (it doesn't need to be shippable):
  `./venv/bin/pip install -r requirements-build.txt && ./venv/bin/pyinstaller packaging/writing_parrot.spec --noconfirm --distpath build/dist --workpath build/work`.
  Then run `./venv/bin/python packaging/smoke_test.py build/dist/WritingParrot`. The smoke script must work on
  Linux too: `WritingParrot` without `.exe`, and no `CREATE_NO_WINDOW` there. Expected: `SMOKE OK`, and the
  worker error line. Add `build/` to `.gitignore`.
- [ ] **Step 5: Commit.** `"Frozen app: PyInstaller spec, windowed worker output, smoke test"`.

### Task 8: Inno Setup installer, release workflow, README and release notes

**Files:**
- Create:
  - `packaging/installer.iss`
  - `packaging/release_notes.md` (en + fa, with the SmartScreen steps)
  - `packaging/smartscreen.png`: a simple illustrative drawing of the two clicks, made with PySide6 by
    `tools/make_smartscreen.py`. Not a screenshot of Microsoft UI; labelled boxes "More info" → "Run anyway".
  - `.github/workflows/release.yml`
  - `tools/check_version.py <tag>`: exits 1 if `tag != "v" + __version__`.
- Modify: `README.md` (Download section near the top), `.gitignore`
- Test: `tests/test_check_version.py`

**Interfaces and decisions:**
- **`installer.iss`:**
  - `AppId={{<fixed new GUID, generate once>}`, `AppName=Writing Parrot`, `AppVersion` from
    `/DMyAppVersion=...`.
  - `DefaultDirName={localappdata}\Programs\Writing Parrot`, `PrivilegesRequired=lowest`,
    `DisableProgramGroupPage=yes`, `OutputBaseFilename=WritingParrot-Setup-{#MyAppVersion}`.
  - `SetupIconFile=..\booktranscriber\assets\icon.ico`, `UninstallDisplayIcon={app}\WritingParrot.exe`,
    `WizardStyle=modern`.
  - `ArchitecturesAllowed=x64compatible`, `ArchitecturesInstallIn64BitMode=x64compatible`.
  - Languages: `english` (Default.isl), plus `persian` from `compiler:Languages\Persian.isl` if present.
    The workflow checks: if the file is missing from the runner's Inno install, the build defines
    `NoPersian` and the script `#ifndef`s that language out.
  - A `[Tasks]` desktopicon, checked by default (no `unchecked` flag). `[Icons]` for the Start menu and the
    desktop.
  - `[Run]` offers "Launch Writing Parrot" at the end (`postinstall nowait skipifsilent`).
- **Uninstall `[Code]`:**
  - In `CurUninstallStepChanged(usPostUninstall)`, read `HKCU\Software\WritingParrot\DownloadsDir`. If it
    exists and the folder exists, compute the size of `models`, `gpu` and `llm`, then ask
    `MsgBox(..., mbConfirmation, MB_YESNO or MB_DEFBUTTON2)`, which defaults to No. The question is in the
    uninstaller's language.
  - On Yes:
    - `DelTree` each of those three subfolders, then `.writingparrot`.
    - `RemoveDir` the downloads folder (only removed if empty).
    - In the app folder `{localappdata}\WritingParrot`: delete `settings.json`, `recents.json`, `logs\` and
      `llm\server.pid` (+ `RemoveDir llm`). Keep `namelists\`. `RemoveDir` the app folder (only if empty).
    - Delete the registry key `HKCU\Software\WritingParrot`.
  - If the downloads folder is the app folder (the default), the same rules apply. Never `DelTree` the
    downloads folder or the app folder themselves.
- **`release.yml`:**
  - Triggers: `push: tags: ['v*']` and `workflow_dispatch`.
  - Job `windows` on `windows-2022`, with steps in this order:
    1. checkout, then setup-python 3.12.
    2. Install deps the same way as ci.yml (the nvidia filter), plus `requirements-build.txt`, pytest and
       pytest-qt.
    3. On a tag, `python tools/check_version.py ${{ github.ref_name }}`.
    4. pytest.
    5. pyinstaller.
    6. `python packaging/smoke_test.py dist/WritingParrot`.
    7. `iscc /DMyAppVersion=<version> packaging/installer.iss`, with Inno found at
       `"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"` or installed via choco.
    8. Write `SHA256SUMS.txt` (PowerShell `Get-FileHash`, lowercase, `<hash>  <file>`).
    9. Upload the installer and the sums as a workflow artifact (always).
  - Job `release`:
    - `needs: windows`, `if: startsWith(github.ref, 'refs/tags/v')`, `permissions: contents: write`.
    - Downloads the artifact, then runs
      `gh release create "$TAG" --draft --title "Writing Parrot $TAG" --notes-file packaging/release_notes.md <files> --repo ${{ github.repository }}`.
    - If the draft for that tag exists, it runs `gh release upload --clobber` instead.
    - `GH_TOKEN: ${{ github.token }}`.
  - Top-level `permissions: contents: read`. Pin actions to major versions already used in ci.yml
    (`checkout@v4`, `setup-python@v5`), plus `actions/upload-artifact@v4` / `download-artifact@v4`.
- **README Download section:**
  - Shown in both English and Persian.
  - Windows: "Download `WritingParrot-Setup-<version>.exe` from the latest release and double-click it. Windows
    may warn because the app isn't signed: click **More info**, then **Run anyway**."
  - Ubuntu and macOS: "coming soon".
  - It links to `https://github.com/javadtavakoli/book-transcriber/releases/latest`, and keeps the developer and
    CLI sections below.

- [ ] **Step 1: Tests** in `tests/test_check_version.py`: `v0.1.0` passes, and `v0.1.1` and `0.1.0` fail
  (subprocess run, check the exit codes).
- [ ] **Step 2: Implement** all the files. Validate the YAML with
  `./venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/release.yml'))"` (install
  pyyaml in the venv if missing; the dev venv only).
- [ ] **Step 3: Run the full suite.** Expected: it passes.
- [ ] **Step 4: Commit.** `"Windows installer (Inno Setup), tag → draft release workflow, Download section"`.

*(Controller, after this task:*
1. *Push the branch and run `gh workflow run release.yml --ref feature/stage3-windows`.*
2. *Watch the run and fix failures in rounds.*
3. *Download the artifact and inspect it: the size, and that the .iss compiled.*
4. *Then do the final review, merge to main, push, and tag `v0.1.0`.*
5. *Verify that the draft release exists with the installer and `SHA256SUMS.txt`.)*
