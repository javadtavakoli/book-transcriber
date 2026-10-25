# Stage 3 hand-off (written 2026-10-25, overnight, while the owner slept)

## What shipped

**Writing Parrot (طوطی‌نویس) v0.1.1 for Windows** (the first release; see "Release result" for why it isn't 0.1.0):
- **Installer:** a per-user installer (no admin prompt), unsigned, with a Start menu entry, a desktop icon and an uninstaller. The installer screens are in English and Persian.
- **Name and icon:** the parrot-and-pen icon. On first launch the old BookTranscriber data folder is renamed to the new name.
- **Downloads folder:** first-run setup lets the user choose where the big downloads go. The app suggests another drive when C: is full. Settings → "Downloads folder…" moves the files safely and offers to delete old ones after "Don't move". If the drive is unplugged, the app says so; it never silently sets up again on C:.
- **AI helper on Windows:** llama-server runs in a Windows "kill on close" job, so it dies with the app even after a crash. A stale helper left by a crashed app is also stopped on Windows.
- **Graphics cards:**
  - AMD and Intel cards are detected, and only dedicated memory counts.
  - CUDA is downloaded only for NVIDIA cards.
- **Persian paths:** native code (CTranslate2, llama-server) only ever gets ASCII model names, run from the model's own folder. A Persian username or a folder like `D:\کتاب ها` therefore works.
- **About and updates:** an About window, and a quiet "new version" link checked at most once a day.
- **Release workflow:** `.github/workflows/release.yml`. A `v*` tag builds, tests, smoke-tests and packages the app, then creates a **draft** release with the installer, `SHA256SUMS.txt` and en/fa notes. It can only ever create drafts.
- **README:** a Download section in English and Persian.

**Evidence (GitHub Actions, windows-2022, release run at commit 8ffacb3):**
- 435 tests passed.
- The frozen app's smoke test passed.
- The frozen worker answered through a pipe from a Persian-named folder.
- The frozen worker **loaded a real Whisper model (faster-whisper-tiny) from a Persian-named folder**.
- Inno Setup 6.7.1 compiled `WritingParrot-Setup-0.1.0.exe` with Persian.

The Tests workflow passed on Ubuntu, Windows and macOS (Windows is now a required job). Locally, 432 passed and 5 were skipped (Windows-only).

## Not yet run on real hardware (please check)
- CUDA on a Windows NVIDIA machine, and Vulkan on Windows AMD/Intel. CI has no GPU.
- Voice detection (VAD) loading from a Persian install path. The CI self-test runs without VAD.
- The real uninstall dialogs.
- The SmartScreen steps, as you will see them.

## Owner checkpoints
1. Download the draft release's installer on your Windows PC and run it. Check that SmartScreen behaves as the notes say ("More info" → "Run anyway"), that there is no admin prompt, and that the Start menu entry and icon appear. Also look at the icon at small size (16 px).
2. First launch:
   - Choose a downloads folder on another drive, **with Persian letters in its name**.
   - Finish setup with the AI helper.
   - Check that C: didn't grow by gigabytes.
3. Transcribe a real recording, use "Fix it here", and save. No black console windows should appear.
4. In Settings → Downloads folder:
   - Move the files to another folder, then transcribe again.
   - Try "Don't move" once with Keep and once with Delete.
5. Uninstall three ways, reinstalling in between, and check what remains each time:
   - Default folder.
   - Custom folder.
   - With the downloads drive unplugged.

   Also check how the folder path displays inside the Persian uninstall question.
6. Read the Persian installer wording. It comes from Inno Setup's unofficial Farsi translation.
7. Press **Publish** on the draft when you're happy. Until then, the README's "latest release" link shows nothing.

## Rulings I made, in order

| Ruling | Why | What it costs if wrong |
|---|---|---|
| The two builder-check questions:<br>1. An integrated GPU, or one with 2048 MiB or less of dedicated memory, gets no AI-helper tier.<br>2. The uninstaller keeps your name lists. | The safer reading. | iGPU laptops don't get the helper ticked by default; name lists remain after uninstall. |
| Executed the plan without waiting for your review. | You said "do till the end and draft a release". | Rework, visible in git. |
| The helper is stopped before a move by reusing the existing "free the graphics card" path. | Same code path as before a transcription. | None. |
| A folder counts as ours only with the `.writingparrot` marker, or if it is the app folder. The plan's "contains models/gpu/llm" rule was dropped. | It is what "never fill or delete a folder with your files" requires. | Re-picking an old unmarked folder creates a WritingParrot subfolder and downloads again. |
| I checked a 7-line thread-safety fix myself, instead of sending it to a reviewer. | It was mechanical. | A rare race on close would remain. The final review saw it. |
| Small diagnostic fixes went in before the first Windows CI run. | They made the CI output trustworthy. | One extra round. |
| A temporary branch trigger was added to the release workflow for test builds, then removed before the merge. | A manual run only works from main. | None now. |
| The tag is passed into the version check through an environment variable rather than inline (the plan said inline). | Security. | None. |
| Inno's Farsi.isl was vendored as `packaging/Persian.isl`, pinned to a commit and marked as modified per its license. The upstream Persian.isl was removed in favour of Farsi.isl. | You asked for both languages. | The wording comes from an unofficial translation. |
| CI loads a real tiny model from a Persian folder; AppPublisher and an upgrade cleanup of `_internal` were added. | It turns a guess into evidence. | About 78 MB of download per release run. |
| Moving files checks sizes only, not checksums. | Checksums would double the move time, and Check/repair re-downloads a bad file. | A corrupt copy shows up as a load failure, which repair fixes. |

## Deferred small items (not fixed)

**Windows behaviour:**
- On Windows, stopping and killing the helper doesn't wait for it to exit, so a crashed-helper cleanup may report success early.
- The test fake's job assignment has a theoretical race, and test sleeper processes are started without the no-window flag.
- A model folder **you pick to reuse** that has a non-ASCII name would still reach native code. App-downloaded folders are always ASCII.
- The upgrade cleanup deletes any `_internal` folder in a custom install folder.

**Downloads folder:**
- The writability check can leave an empty folder behind if you cancel.
- A crash in a very narrow window during a move can leave settings pointing at the new, emptied folder.
- Partial files from a crashed move make the next move refuse with "folder already holds files".
- A permission error while checking a picked folder isn't turned into a friendly message.
- Closing the Downloads dialog without moving resets setup's error page.
- "Continue on CPU" is saved before setup succeeds.
- On Linux and macOS, a missing mount shows the parent folder's free space.

**Graphics cards:**
- The integrated threshold uses "2048 or less", not "under 2048". There is no practical effect.
- On Linux, AMD cards show the generic name "AMD graphics card".
- An NVIDIA card found only in the registry still triggers the CUDA download.

**Uninstaller:**
- The path may reorder inside the Persian question.
- There is no Inno version floor check.
- The vendored file's license link points at `main`.

**Packaging and tests:**
- The bundle includes unused onnxruntime submodules (size only).
- A manual `--smoke` run leaves a temp folder behind.
- The smoke test's model download has no timeout of its own.
- The macOS test `test_gpu_crash_while_fixing_finishes_on_the_processor` flaked once; the final review found it isn't a regression.
- A few GUI tests don't write settings.json to disk.
- The About test's helper is clumsy.
- Some errors in the icon setup and in the settings rewrite during migration are silently ignored.

## Branches
- `feature/stage3-windows` was merged into `main`. The remote copy of the branch was left in place.
- The stage 3 spec and plan are in `docs/superpowers/specs/2026-10-25-stage3-windows-design.md` and `docs/superpowers/plans/2026-10-25-stage3-windows.md`.

## Release result
- **First v0.1.0 tag build (run 40141969623):** it failed in the test step with an intermittent Windows "access violation". The cause was old stage 2 code calling `QObject.sender()` in a queued slot after the sending thread had been destroyed. Nothing was published, because the draft step never ran.
- **Fix:** commit 77afe0b. Runners now bind a per-job token at connect time instead of using `sender()`. It was reviewed and approved, and tests passed on Ubuntu, Windows and macOS.
- **Moving the tag was not possible:** deleting the GitHub tag was refused as a destructive action.
- **Ruling:** the version was bumped to **0.1.1** and the release was made from tag `v0.1.1`. The `v0.1.0` tag stays on GitHub at the commit whose build failed, and no release is attached to it. You may delete it if you like (`git push origin :refs/tags/v0.1.0`). The cost: one unused tag in the list.
- **Deferred minors from that fix:**
  - The `p.disconnect(self)` line in runners.py now does nothing.
  - The two new stale-signal tests are weak: they don't go through `start()` or exercise the token itself.

**Draft release created.** The v0.1.1 tag's run (40142891351) passed every step: tests, the frozen-app smoke test with a real model loaded from a Persian folder, the Persian installer build, and the draft release step. The draft "Writing Parrot v0.1.1" holds `WritingParrot-Setup-0.1.1.exe` (96.7 MB) and `SHA256SUMS.txt`, with the version filled into the notes. It is still a **draft**: open GitHub → Releases to review it and press Publish.

The `feature/stage3-windows` and `fix/sender-crash` branches were merged into main. Their copies on GitHub were left in place.

## v0.1.2 (2026-10-25): automatic retry when the internet drops
At the owner's request, setup and the AI helper's later download no longer stop at the first network hiccup with a Try again button.
- **Automatic retries:** each download, and the initial file list, is retried on its own every 5 seconds, up to 30 times in a row. It resumes where it stopped. The screen says "No internet connection. Trying again in 5 seconds (3 of 30)…".
- **Counting:** the count starts again whenever the download gets further, so a slow but advancing line is never given up on.
- **Not retried:** a server refusal (404/403), checksum errors, a full disk and broken archives. These show the error screen at once.
- **Pause and Cancel** end the wait immediately. After 30 failures in a row, the usual error screen appears.
- Reviewed and approved. CI passed on all three systems.

## v0.1.3 (2026-10-25): transcription never started on Windows
The owner's Windows logs showed every transcription failing with `TypeError: open() got an unexpected keyword argument 'metadata_errors'`.
- **Cause:** faster-whisper 1.2.1 opens each recording with `av.open(..., metadata_errors="ignore")`. PyAV 19 removed that argument. requirements.txt only *mentioned* the transitive versions in a comment, so the v0.1.1 and v0.1.2 builds both installed av 19.0.2, plus newer ctranslate2, onnxruntime and huggingface-hub (2.3, a major jump). Development used av 18.0.0, which works.
- **Why nothing caught it:**
  - The worker self-test (setup's check and CI's model test) fed the model a numpy array, so the audio reader never ran.
  - The smoke test's worker check used a missing file, which stops before faster-whisper.
- **Fix:**
  - A new `constraints.txt` pins the cross-platform packages to the tested versions. requirements.txt includes it with `-c`, so setup scripts, CI and release builds all get it.
  - The self-test now writes a WAV file and transcribes it from disk.
  - The release smoke test also transcribes a real WAV from a Persian folder with the frozen app.
  - A unit test decodes audio from a Persian folder through faster-whisper.
- **Checked:** the self-test fails with av 19 (same TypeError as the owner's log) and passes with av 18.
- **Not fixed (seen in the same log):** CUDA float16 and int8_float16 were both refused on the owner's graphics card, so it ran on the processor. This needs the card model to diagnose.
