import dataclasses
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from booktranscriber import llm_server, paths, setup_runner
from booktranscriber.fixexport import LineFix
from booktranscriber.gui import flow_view, setup_view
from booktranscriber.gui.flow_view import FlowView
from booktranscriber.gui.local_view import LocalView
from booktranscriber.gui.main_window import MainWindow
from booktranscriber.gui.review_view import ReviewView
from booktranscriber.gui.runners import LocalFixRunner
from booktranscriber.gui.setup_view import SetupView
from booktranscriber.i18n import I18n
from booktranscriber.recents import RecentItem, add_recent
from booktranscriber.settings import Settings, load_settings
from booktranscriber.setup_runner import SetupError, SetupProgress
from booktranscriber.syscheck import GpuInfo, SystemInfo

from .test_home_flow import FakeRunner as FakeTranscriber
from .test_setup_view import FakeRunner as FakeSetupRunner

OK = SystemInfo("linux", GpuInfo("NVIDIA GeForce RTX 4050 Laptop GPU", 6141), 120 * 10**9)
WEAK = SystemInfo("linux", None, 120 * 10**9)
LINES = ["سلام به همه", "این کتاب انقاشی داره", "", "آره خب"]


@pytest.fixture
def binaries(monkeypatch, fake_llama):
    """binaries({"vulkan": "crash", "cpu": "ok"}): which fake each llama-server build is."""
    def use(modes):
        built = {b: fake_llama(m) for b, m in modes.items()}
        monkeypatch.setattr(llm_server, "server_binary", lambda backend: built.get(backend))
    return use


@pytest.fixture
def model_file(tmp_path):
    m = tmp_path / "model.gguf"
    m.write_bytes(b"gguf")
    return m


@pytest.fixture
def settings(model_file, tmp_path):
    (tmp_path / "model.bin").write_bytes(b"x")
    return Settings(setup_done=True, whisper_model_path=str(tmp_path), llm_model="gemma-4-e4b",
                    llm_model_path=str(model_file), llm_backend="vulkan")


@pytest.fixture
def runner(fake_llama):
    r = LocalFixRunner()
    yield r
    r.stop_server()


@pytest.fixture
def raw_file(tmp_path):
    raw = tmp_path / "s12 - متن خام.txt"
    raw.write_text("\n".join(LINES) + "\n", "utf-8")
    return raw


@pytest.fixture
def local(qtbot, runner, settings):
    v = LocalView(I18n("en"), settings, runner)
    qtbot.addWidget(v)
    return v


@pytest.fixture
def window(qtbot, settings, fake_llama, monkeypatch):
    monkeypatch.setattr(setup_view, "detect_system", lambda d: OK)
    w = MainWindow(I18n("en"), settings)
    qtbot.addWidget(w)
    yield w
    w.local_runner.stop_server()
    w.flow_view.llm_download.stop_and_wait()


def open_recent(w, raw_file):
    item = RecentItem(str(raw_file.with_name("s12.m4a")), str(raw_file), None, "t")
    add_recent(paths.recents_file(), item)
    w.home_view.recent_opened.emit(item)
    return item


# --- setup --------------------------------------------------------------------------
def test_setup_llm_checkbox_follows_recommendation(qtbot, monkeypatch):
    monkeypatch.setattr(setup_view, "find_existing_model", lambda dirs, model: None)
    monkeypatch.setattr(setup_view, "detect_system", lambda d: OK)
    runner = FakeSetupRunner()
    v = SetupView(I18n("en"), Settings(), runner)
    qtbot.addWidget(v)
    assert v.llm_box.isChecked() and v.llm_box.text() == "Also download the AI helper (recommended)"
    assert v.llm_weak.isHidden() and not v.llm_note.isHidden()
    with_llm = v.space_line.text()
    v.llm_box.setChecked(False)
    assert v.space_line.text() != with_llm          # the helper's size leaves the estimate
    v.llm_box.setChecked(True)
    v.start()
    assert runner.starts[-1][0].include_llm and not v.rows["llm"].isHidden()

    monkeypatch.setattr(setup_view, "detect_system", lambda d: WEAK)
    v.refresh()
    assert not v.llm_box.isChecked() and not v.llm_weak.isHidden()
    assert "may be slow" in v.llm_weak.text()
    v.start()
    assert not runner.starts[-1][0].include_llm and v.rows["llm"].isHidden()

    # A good computer short on space: unticked, so Start isn't blocked by the optional helper.
    monkeypatch.setattr(setup_view, "detect_system", lambda d: SystemInfo("linux", OK.gpu, 7 * 10**9))
    v.refresh()
    assert not v.llm_box.isChecked() and v.start_button.isEnabled()


def test_setup_disk_error_offers_skip_ai_helper(qtbot, monkeypatch):
    monkeypatch.setattr(setup_view, "find_existing_model", lambda dirs, model: None)
    monkeypatch.setattr(setup_view, "detect_system", lambda d: OK)
    runner = FakeSetupRunner()
    v = SetupView(I18n("en"), Settings(), runner)
    qtbot.addWidget(v)
    v.start()
    runner.last_error = SetupError("disk", needed=6 * 10**9, free=4 * 10**9, fits_without_llm=True)
    runner.failed.emit("disk")
    assert v.state() == "error" and not v.skip_llm_button.isHidden()
    assert v.skip_llm_button.text() == "Skip AI helper"
    qtbot.mouseClick(v.skip_llm_button, Qt.LeftButton)
    assert not runner.starts[-1][0].include_llm and not v.llm_box.isChecked() and v.state() == "downloading"

    runner.last_error = SetupError("disk", needed=6 * 10**9, free=10**8, fits_without_llm=False)
    runner.failed.emit("disk")
    assert v.skip_llm_button.isHidden()


@pytest.mark.parametrize("kind,item,offered", [("network", "llm", True), ("checksum", "llm", True),
                                               ("network", "whisper", False)])
def test_setup_download_error_on_ai_helper_offers_skip(qtbot, monkeypatch, kind, item, offered):
    monkeypatch.setattr(setup_view, "find_existing_model", lambda dirs, model: None)
    monkeypatch.setattr(setup_view, "detect_system", lambda d: OK)
    runner = FakeSetupRunner()
    v = SetupView(I18n("en"), Settings(), runner)
    qtbot.addWidget(v)
    v.start()
    runner.last_error = SetupError(kind, item=item)
    runner.failed.emit(kind)
    assert v.state() == "error" and not v.retry_button.isHidden()
    assert v.skip_llm_button.isHidden() is not offered
    if offered:
        qtbot.mouseClick(v.skip_llm_button, Qt.LeftButton)
        assert not runner.starts[-1][0].include_llm and v.state() == "downloading"


# --- the local fix panel ------------------------------------------------------------
def test_local_view_fixes_and_emits_review(qtbot, local, binaries, raw_file):
    binaries({"vulkan": "fix"})
    local.start(str(raw_file), [], "fa")
    assert local.state() == "loading" and local.title.text() == "Loading the AI helper…"
    with qtbot.waitSignal(local.review_ready, timeout=20000) as blocker:
        pass
    fixes = blocker.args[0]
    assert [f.proposed for f in fixes if f.reason == "fixed"] == ["این کتاب نقاشی داره"]
    assert local.runner.server_loaded()


def test_loading_bar_moves_and_shows_eta_second_time(qtbot, local, binaries, raw_file):
    binaries({"vulkan": "slow"})
    local.settings.llm_load_seconds = 60
    local.start(str(raw_file), [], "fa")
    qtbot.waitUntil(lambda: not local.eta_label.isHidden() and local.bar.value() > 0, timeout=10000)
    assert "left" in local.eta_label.text()
    with qtbot.waitSignal(local.review_ready, timeout=20000):
        pass
    # The real duration is remembered for next time.
    saved = load_settings(paths.settings_file()).llm_load_seconds
    assert saved is not None and 0 < saved < 60


def test_first_load_shows_no_time_left(qtbot, local, binaries, raw_file):
    binaries({"vulkan": "slow"})
    local.start(str(raw_file), [], "fa")
    qtbot.waitUntil(lambda: local.bar.value() > 0, timeout=10000)
    assert local.eta_label.isHidden()
    with qtbot.waitSignal(local.review_ready, timeout=20000):
        pass


def test_fixing_shows_parts(qtbot, local, binaries, raw_file):
    binaries({"vulkan": "ok"})
    local.start(str(raw_file), [], "fa")
    with qtbot.waitSignal(local.review_ready, timeout=20000):
        pass
    # A second fix reuses the loaded helper: straight to fixing, no loading.
    local.start(str(raw_file), [], "fa")
    assert local.state() == "fixing" and local.status.text() == "Fixing… part 1 of 1"
    with qtbot.waitSignal(local.review_ready, timeout=20000):
        pass


def test_fallback_note_shown(qtbot, local, binaries, raw_file):
    binaries({"vulkan": "crash", "cpu": "ok"})
    local.start(str(raw_file), [], "fa")
    with qtbot.waitSignal(local.review_ready, timeout=20000):
        pass
    assert not local.fallback_note.isHidden() and "processor" in local.fallback_note.text()


def test_memory_error_offers_export(qtbot, local, binaries, raw_file):
    binaries({"vulkan": "oom", "cpu": "ok"})
    local.start(str(raw_file), [], "fa")
    qtbot.waitUntil(lambda: local.state() == "error", timeout=20000)
    assert not local.export_button.isHidden() and local.retry_button.isHidden()
    assert local.export_button.text() == "Use ChatGPT / Claude / Gemini instead"
    with qtbot.waitSignal(local.export_instead):
        qtbot.mouseClick(local.export_button, Qt.LeftButton)


def test_other_errors_offer_try_again(qtbot, local, binaries, raw_file):
    binaries({"vulkan": "crash", "cpu": "crash"})
    local.start(str(raw_file), [], "fa")
    qtbot.waitUntil(lambda: local.state() == "error", timeout=20000)
    assert local.export_button.isHidden() and not local.retry_button.isHidden()
    binaries({"vulkan": "ok"})
    qtbot.mouseClick(local.retry_button, Qt.LeftButton)
    assert local.state() == "loading"
    with qtbot.waitSignal(local.review_ready, timeout=20000):
        pass


def test_cancel_while_loading_goes_back(qtbot, local, binaries, raw_file):
    binaries({"vulkan": "hang"})
    local.start(str(raw_file), [], "fa")
    qtbot.waitUntil(lambda: local.bar.value() > 0, timeout=10000)
    with qtbot.waitSignal(local.back):
        qtbot.mouseClick(local.cancel_button, Qt.LeftButton)
    assert not local.runner.is_running()
    local.runner.stop_server()
    assert not local.runner.server_loaded()


def test_runner_drops_results_of_a_stopped_job(qtbot, runner, binaries, settings):
    binaries({"vulkan": "ok"})
    got = []
    runner.finished.connect(got.append)
    with qtbot.waitSignal(runner.finished, timeout=20000):
        runner.start(LINES, [], settings)
    runner.start(LINES, [], settings)
    runner.stop_server()
    qtbot.wait(300)
    assert len(got) == 1 and not runner.server_loaded() and not runner.is_running()


# Two parts (15 lines each go to the helper at a time), a misheard word in each.
TWO_PARTS = ["این کتاب انقاشی داره"] + [f"خط شماره {i}" for i in range(2, 20)] + ["اون هم انقاشی داره"]


def test_gpu_crash_while_fixing_finishes_on_the_processor(qtbot, runner, binaries, settings, fake_llama,
                                                          tmp_path, monkeypatch):
    import json
    log = tmp_path / "starts.jsonl"
    monkeypatch.setenv("FAKE_LLAMA_LOG", str(log))
    binaries({"vulkan": "diefix", "cpu": "fix"})
    fallbacks = []
    runner.fallback.connect(lambda: fallbacks.append(1))
    with qtbot.waitSignal(runner.finished, timeout=30000) as blocker:
        runner.start(TWO_PARTS, [], settings)
    fixes = blocker.args[0]
    # Part 1 was answered on the graphics card (echoed); only part 2 went to the processor (fixed).
    assert [f.reason for f in fixes].count("missing") == 0
    assert (fixes[0].reason, fixes[-1].reason) == ("same", "fixed")
    assert fixes[-1].proposed == "اون هم نقاشی داره"
    assert fallbacks and runner.gpu_failed and not runner._server.gpu
    assert runner._server.binary == fake_llama("fix")

    # For the rest of the session the helper starts straight on the processor.
    runner.stop_server()
    with qtbot.waitSignal(runner.finished, timeout=30000):
        runner.start(TWO_PARTS, [], settings)
    assert runner._server.binary == fake_llama("fix") and not runner._server.gpu
    starts = [json.loads(l) for l in log.read_text("utf-8").splitlines()]
    assert ["-ngl" in a for a in starts] == [False, True, True]


def test_fallback_while_fixing_shows_loading_again(qtbot, local, binaries, raw_file):
    binaries({"vulkan": "ok"})
    local.start(str(raw_file), [], "fa")
    with qtbot.waitSignal(local.review_ready, timeout=20000):
        pass
    local._set_state("fixing")
    local.bar.setValue(50)
    local._on_fallback()
    assert local.state() == "loading" and local.bar.value() == 0 and not local.fallback_note.isHidden()


# --- the window -----------------------------------------------------------------------
def test_local_button_opens_loading_then_review(qtbot, window, binaries, raw_file):
    binaries({"vulkan": "fix"})
    w = window
    open_recent(w, raw_file)
    assert w.flow_view.local_button.isEnabled()
    assert "check each change" in w.flow_view.local_button.text()
    w.flow_view.local_button.click()
    assert w.current_page() == "local" and w.local_view.state() == "loading"
    assert w.busy()
    qtbot.waitUntil(lambda: w.current_page() == "review", timeout=20000)
    assert not w.review_view.local_banner.isHidden()
    assert w.review_view.fixes[1].proposed == "این کتاب نقاشی داره"
    w.review_view.save_button.click()
    assert raw_file.with_name("s12 - متن اصلاح‌شده.txt").read_text("utf-8").splitlines()[1] == "این کتاب نقاشی داره"
    w.review_view.back.emit()
    assert w.current_page() == "flow"


def test_memory_error_export_instead_opens_export(qtbot, window, binaries, raw_file):
    binaries({"vulkan": "oom"})
    w = window
    open_recent(w, raw_file)
    w.flow_view.local_button.click()
    qtbot.waitUntil(lambda: w.local_view.state() == "error", timeout=20000)
    w.local_view.export_button.click()
    assert w.current_page() == "export" and w.export_view.lines == LINES


def test_server_stopped_before_new_transcription(qtbot, window, binaries, raw_file, monkeypatch, llama_alive):
    binaries({"vulkan": "ok"})
    w = window
    open_recent(w, raw_file)
    w.flow_view.local_button.click()
    qtbot.waitUntil(lambda: w.current_page() == "review", timeout=20000)
    assert w.local_runner.server_loaded()
    pid = w.local_runner._server.pid
    seen = []
    monkeypatch.setattr(w.transcriber, "start",
                        lambda job: seen.append((llama_alive(pid), w.local_runner.server_loaded())))
    audio = raw_file.with_name("next.m4a")
    audio.write_bytes(b"x")
    w.home_view.handle_files([str(audio)])
    w.flow_view.skip_button.click()
    assert seen == [(False, False)]


@pytest.fixture
def chat_in_flight(qtbot, window, binaries, raw_file, tmp_path, monkeypatch):
    """The window fixing with a helper that is answering (holding) its first chat request; its pid."""
    chats = tmp_path / "chats.txt"
    monkeypatch.setenv("FAKE_LLAMA_CHATS", str(chats))
    binaries({"vulkan": "holdchat"})
    open_recent(window, raw_file)
    window.flow_view.local_button.click()
    qtbot.waitUntil(lambda: window.local_view.state() == "fixing" and chats.exists(), timeout=20000)
    assert window.local_runner.is_running() and window.busy()
    return window.local_runner._server.pid


def fix_threads_running(r) -> bool:
    return any(t is not None and t.isRunning() for t in [r._thread, *r._winding_down])


def test_new_transcription_while_answering_stops_helper_first(qtbot, window, raw_file, chat_in_flight,
                                                              monkeypatch, llama_alive):
    import time
    w, pid = window, chat_in_flight
    seen = []
    monkeypatch.setattr(w.transcriber, "start",
                        lambda job: seen.append((llama_alive(pid), fix_threads_running(w.local_runner))))
    audio = raw_file.with_name("next.m4a")
    audio.write_bytes(b"x")
    t0 = time.monotonic()
    w.home_view.handle_files([str(audio)])
    w.flow_view.skip_button.click()
    assert seen == [(False, False)] and time.monotonic() - t0 < 10
    assert not w.local_runner.server_loaded() and not list(llm_server._servers)


def test_close_while_answering_stops_everything(qtbot, window, chat_in_flight, monkeypatch, llama_alive):
    import time
    w, pid = window, chat_in_flight
    w.show()
    monkeypatch.setattr(w, "confirm_quit", lambda: True)
    t0 = time.monotonic()
    w.close()
    assert time.monotonic() - t0 < 10
    assert not llama_alive(pid) and not fix_threads_running(w.local_runner)
    assert not w.local_runner.server_loaded() and not list(llm_server._servers)


def test_retry_after_failure_also_stops_server(qtbot, settings):
    calls = []
    v = FlowView(I18n("en"), settings, FakeTranscriber(), before_transcribe=lambda: calls.append("stop"))
    qtbot.addWidget(v)
    audio = Path(settings.whisper_model_path) / "a.m4a"
    audio.write_bytes(b"x")
    v.begin(str(audio))
    v.skip_button.click()
    v.runner.failed.emit("unknown", "x")
    v.problem_button.click()
    assert calls == ["stop", "stop"] and len(v.runner.jobs) == 2


def test_close_stops_server(qtbot, window, binaries, raw_file, llama_alive):
    binaries({"vulkan": "ok"})
    w = window
    w.show()
    open_recent(w, raw_file)
    w.flow_view.local_button.click()
    qtbot.waitUntil(lambda: w.current_page() == "review", timeout=20000)
    pid = w.local_runner._server.pid
    assert llama_alive(pid) and not w.busy()
    w.close()
    assert not llama_alive(pid) and not w.local_runner.server_loaded()


def test_close_while_loading_stops_everything(qtbot, window, binaries, raw_file, monkeypatch):
    binaries({"vulkan": "hang"})
    w = window
    w.show()
    open_recent(w, raw_file)
    w.flow_view.local_button.click()
    qtbot.waitUntil(lambda: w.local_view.bar.value() > 0, timeout=10000)
    assert w.busy()
    monkeypatch.setattr(w, "confirm_quit", lambda: True)
    w.close()
    assert not w.local_runner.is_running() and not w.local_runner.server_loaded()
    assert not list(llm_server._servers)


# --- download later ---------------------------------------------------------------------
def test_download_then_fix_when_missing(qtbot, settings, raw_file, monkeypatch, model_file):
    monkeypatch.setattr(flow_view, "detect_system", lambda d: OK)
    picked = []

    def fake_llm_setup(model_key, backend, s, on_progress, cancel, **kw):
        picked.append((model_key, backend))
        on_progress(SetupProgress("llm", 1, 2, 1, 2, 1e6, 3))
        return dataclasses.replace(s, llm_model=model_key, llm_backend=backend, llm_model_path=str(model_file))
    monkeypatch.setattr(setup_runner, "run_llm_setup", fake_llm_setup)
    settings.llm_model_path = None
    v = FlowView(I18n("en"), settings, FakeTranscriber())
    qtbot.addWidget(v)
    v.show()
    v.open_result(RecentItem(str(raw_file.with_name("s12.m4a")), str(raw_file), None, "t"), from_recents=True)
    assert v.local_button.text().startswith("Download the AI helper (4.8 GB) and fix")
    with qtbot.waitSignal(v.local_requested, timeout=10000) as blocker:
        v.local_button.click()
        assert not v.local_bar.isHidden() and not v.local_button.isEnabled()
    assert blocker.args == [str(raw_file), [], "fa"]
    assert picked == [("gemma-4-e4b", "vulkan")]
    assert settings.llm_model_path == str(model_file) and v.local_bar.isHidden()
    assert load_settings(paths.settings_file()).llm_model_path == str(model_file)
    assert v.local_button.text().startswith("Fix it here (private)")
    v.llm_download.stop_and_wait()


def test_download_failure_lets_you_try_again(qtbot, settings, raw_file, monkeypatch):
    monkeypatch.setattr(flow_view, "detect_system", lambda d: OK)

    def failing(*a, **kw):
        raise SetupError("network")
    monkeypatch.setattr(setup_runner, "run_llm_setup", failing)
    settings.llm_model_path = None
    v = FlowView(I18n("en"), settings, FakeTranscriber())
    qtbot.addWidget(v)
    v.open_result(RecentItem(str(raw_file.with_name("s12.m4a")), str(raw_file), None, "t"), from_recents=True)
    v.local_button.click()
    qtbot.waitUntil(lambda: v.local_button.isEnabled(), timeout=10000)
    assert not v.local_problem.isHidden() and v.local_bar.isHidden()
    v.llm_download.stop_and_wait()


@pytest.mark.parametrize("info,warned", [(WEAK, True), (OK, False)])
def test_download_later_warns_when_not_recommended(qtbot, settings, raw_file, monkeypatch, info, warned):
    monkeypatch.setattr(flow_view, "detect_system", lambda d: info)
    settings.llm_model_path = None
    v = FlowView(I18n("en"), settings, FakeTranscriber())
    qtbot.addWidget(v)
    v.open_result(RecentItem(str(raw_file.with_name("s12.m4a")), str(raw_file), None, "t"), from_recents=True)
    assert v.local_button.text().startswith("Download the AI helper")
    assert v.local_weak.isHidden() is not warned
    assert "may be slow" in v.local_weak.text()
    from booktranscriber.gui.widgets import PRIMARY       # the online route stays the recommended one
    assert v.export_button.styleSheet() == PRIMARY and v.local_button.styleSheet() != PRIMARY


def test_no_slowness_warning_once_downloaded(qtbot, settings, raw_file, monkeypatch):
    monkeypatch.setattr(flow_view, "detect_system", lambda d: WEAK)
    v = FlowView(I18n("en"), settings, FakeTranscriber())
    qtbot.addWidget(v)
    v.open_result(RecentItem(str(raw_file.with_name("s12.m4a")), str(raw_file), None, "t"), from_recents=True)
    assert v.local_button.text().startswith("Fix it here") and v.local_weak.isHidden()


# --- review -------------------------------------------------------------------------------
def test_review_banner_for_local_route(qtbot, raw_file):
    v = ReviewView(I18n("en"))
    qtbot.addWidget(v)
    fixes = [LineFix(1, "a", "b", True, "fixed")]
    v.load(str(raw_file), ["a"], fixes, "fa", local=True)
    assert not v.local_banner.isHidden()
    assert v.local_banner.text() == "Made by the AI helper on your computer. Check each change."
    v.load(str(raw_file), ["a"], fixes, "fa")
    assert v.local_banner.isHidden()


# --- failures while fixing, and starting again while a cancelled job winds down ---------
def test_no_answers_at_all_is_an_error_not_an_empty_review(qtbot, local, binaries, raw_file):
    binaries({"vulkan": "http500"})
    got = []
    local.review_ready.connect(got.append)
    local.start(str(raw_file), [], "fa")
    qtbot.waitUntil(lambda: local.state() == "error", timeout=20000)
    assert not local.retry_button.isHidden() and got == []


@pytest.fixture
def slow_fix(runner, monkeypatch):
    """fix_transcript that holds each part until released; released at teardown, before the runner stops."""
    from booktranscriber.fixexport import apply_answer
    from booktranscriber.gui import runners
    release, calls = __import__("threading").Event(), []

    def fake(lines, names, port, on_progress, cancel, client=None):
        calls.append(port)
        release.wait()
        return apply_answer(lines, {2: "این کتاب نقاشی داره"})
    monkeypatch.setattr(runners, "fix_transcript", fake)
    yield release, calls
    release.set()


def test_starting_again_while_cancelled_part_finishes_does_not_freeze(qtbot, runner, binaries, settings, slow_fix):
    import time
    release, calls = slow_fix
    binaries({"vulkan": "ok"})
    got = []
    runner.finished.connect(got.append)
    runner.start(LINES, [], settings)
    qtbot.waitUntil(lambda: len(calls) == 1, timeout=20000)
    runner.cancel()
    t0 = time.monotonic()
    runner.start(LINES, [], settings)
    assert time.monotonic() - t0 < 0.5
    qtbot.waitUntil(lambda: len(calls) == 2, timeout=5000)
    assert calls[0] == calls[1]          # the same loaded helper, not a second one
    release.set()
    qtbot.waitUntil(lambda: bool(got) and not runner.is_running(), timeout=5000)
    qtbot.wait(200)
    assert len(got) == 1 and runner.server_loaded()


def test_download_shows_words_and_can_be_cancelled(qtbot, settings, raw_file, monkeypatch, request):
    import threading
    monkeypatch.setattr(flow_view, "detect_system", lambda d: OK)
    started = threading.Event()

    def waits_for_cancel(model_key, backend, s, on_progress, cancel, **kw):
        on_progress(SetupProgress("llm", 1_200_000_000, 4_800_000_000, 1_200_000_000, 4_800_000_000, 4e6, 900))
        started.set()
        cancel.wait(10)
        raise SetupError("cancelled")
    monkeypatch.setattr(setup_runner, "run_llm_setup", waits_for_cancel)
    settings.llm_model_path = None
    v = FlowView(I18n("en"), settings, FakeTranscriber())
    qtbot.addWidget(v)
    v.show()
    request.addfinalizer(v.llm_download.stop_and_wait)    # never leave the download thread running
    v.open_result(RecentItem(str(raw_file.with_name("s12.m4a")), str(raw_file), None, "t"), from_recents=True)
    assert v.local_status.isHidden() and v.local_cancel_button.isHidden()
    got = []
    v.local_requested.connect(lambda *a: got.append(a))
    v.local_button.click()
    qtbot.waitUntil(lambda: "1.2 GB of 4.8 GB" in v.local_status.text(), timeout=5000)
    assert v.local_status.text().startswith("Downloading the AI helper…")
    assert "about 15 min left" in v.local_status.text()
    assert not v.local_status.isHidden() and not v.local_cancel_button.isHidden()
    v.local_cancel_button.click()
    qtbot.waitUntil(lambda: not v.llm_download.is_running() and v.local_button.isEnabled(), timeout=5000)
    assert v.local_status.isHidden() and v.local_bar.isHidden() and v.local_cancel_button.isHidden()
    assert v.local_problem.isHidden() and got == []
    assert v.local_button.text().startswith("Download the AI helper")


def test_download_says_when_it_is_waiting_to_retry(qtbot, settings, raw_file, monkeypatch, request):
    import threading
    monkeypatch.setattr(flow_view, "detect_system", lambda d: OK)
    monkeypatch.setattr(setup_runner, "RETRY_DELAY", 5.0)

    def offline(model_key, backend, s, on_progress, cancel, **kw):
        on_progress(SetupProgress("llm", 1_200_000_000, 4_800_000_000, 1_200_000_000, 4_800_000_000, 0.0, None, 2))
        cancel.wait(10)
        raise SetupError("cancelled")
    monkeypatch.setattr(setup_runner, "run_llm_setup", offline)
    settings.llm_model_path = None
    v = FlowView(I18n("en"), settings, FakeTranscriber())
    qtbot.addWidget(v)
    v.show()
    request.addfinalizer(v.llm_download.stop_and_wait)
    v.open_result(RecentItem(str(raw_file.with_name("s12.m4a")), str(raw_file), None, "t"), from_recents=True)
    v.local_button.click()
    qtbot.waitUntil(lambda: "Trying again" in v.local_status.text(), timeout=5000)
    assert "No internet connection. Trying again in 5 seconds (2 of 30)…" in v.local_status.text()
    assert v.local_problem.isHidden()
    v.local_cancel_button.click()
    qtbot.waitUntil(lambda: not v.llm_download.is_running(), timeout=5000)


def test_stale_server_reaped_before_transcription(qtbot, window, raw_file, monkeypatch):
    from booktranscriber.gui import main_window
    order = []
    monkeypatch.setattr(main_window, "reap_stale", lambda: order.append("reap") or False)
    monkeypatch.setattr(window.transcriber, "start", lambda job: order.append("start"))
    audio = raw_file.with_name("next.m4a")
    audio.write_bytes(b"x")
    window.home_view.handle_files([str(audio)])
    window.flow_view.skip_button.click()
    assert order == ["reap", "start"]


def test_late_signals_from_a_replaced_thread_are_ignored(qtbot):
    """Handlers are bound to their thread at connect time (no QObject.sender(), which can crash)."""
    r = LocalFixRunner()
    old, current = object(), object()
    r._token, r._live = current, True
    seen = []
    for name in ("load_progress", "fallback", "fix_progress", "finished", "failed"):
        getattr(r, name).connect(lambda *a, n=name: seen.append(n))
    r._on_load_progress(old, 0.5, None)
    r._on_fallback(old)
    r._on_fix_progress(old, 1, 2)
    r._on_done(old, [])
    r._on_error(old, "model")
    assert seen == [] and r._live
    r._on_fix_progress(current, 1, 2)
    r._on_done(current, [])
    assert seen == ["fix_progress", "finished"] and not r._live
