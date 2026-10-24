from booktranscriber import __version__, paths, updates
from booktranscriber.gui import about_dialog
from booktranscriber.gui.main_window import MainWindow
from booktranscriber.i18n import I18n
from booktranscriber.settings import Settings, load_settings


def make(qtbot, settings=None, lang="en"):
    w = MainWindow(I18n(lang), settings or Settings())
    qtbot.addWidget(w)
    return w


def test_about_shows_version(qtbot, monkeypatch):
    shown = []
    monkeypatch.setattr(about_dialog, "run_dialog", lambda d: shown.append(d.windowTitle() + "\n" + d.text.text()
                                                                           + "\n" + "".join(c.text() for c in d.findChildren(type(d.text)))))
    w = make(qtbot)
    w.about_action.trigger()
    assert __version__ in shown[0] and "Writing Parrot" in shown[0] and "MIT" in shown[0]
    assert about_dialog.GITHUB_PAGE in shown[0]


def test_about_in_persian_uses_the_persian_name(qtbot, monkeypatch):
    shown = []
    monkeypatch.setattr(about_dialog, "run_dialog",
                        lambda d: shown.append("".join(c.text() for c in d.findChildren(type(d.text)))))
    make(qtbot, lang="fa").about_action.trigger()
    assert "طوطی‌نویس" in shown[0]


def test_update_notice_shown_when_newer(qtbot, monkeypatch):
    monkeypatch.setattr(updates, "check_latest", lambda *a, **k: "v99.0.0")
    w = make(qtbot)
    w.show()
    assert not w.update_label.isVisible()
    w.check_for_updates()
    qtbot.waitUntil(w.update_label.isVisible, timeout=3000)
    assert updates.RELEASES_PAGE in w.update_label.text()
    assert load_settings(paths.settings_file()).last_update_check == w.settings.last_update_check is not None


def test_notice_link_opens_the_releases_page(qtbot, monkeypatch):
    opened = []
    monkeypatch.setattr(about_dialog, "open_url", opened.append)
    monkeypatch.setattr(updates, "check_latest", lambda *a, **k: "v99.0.0")
    w = make(qtbot)      # built after the patch, so its label is wired to the hook
    w.show()
    w.check_for_updates()
    qtbot.waitUntil(w.update_label.isVisible, timeout=3000)
    w.update_label.linkActivated.emit(updates.RELEASES_PAGE)
    assert opened == [updates.RELEASES_PAGE]


def test_no_notice_offline(qtbot):
    w = make(qtbot)
    w.show()
    w.check_for_updates()
    qtbot.waitUntil(lambda: not w.update_thread.isRunning(), timeout=3000)
    qtbot.wait(50)
    assert not w.update_label.isVisible()


def test_no_notice_when_not_newer(qtbot, monkeypatch):
    monkeypatch.setattr(updates, "check_latest", lambda *a, **k: f"v{__version__}")
    w = make(qtbot)
    w.show()
    w.check_for_updates()
    qtbot.waitUntil(lambda: not w.update_thread.isRunning(), timeout=3000)
    qtbot.wait(50)
    assert not w.update_label.isVisible()


def test_no_check_when_not_due(qtbot, monkeypatch):
    import time
    calls = []
    monkeypatch.setattr(updates, "check_latest", lambda *a, **k: calls.append(1))
    w = make(qtbot, Settings(last_update_check=time.time() - 60))
    w.check_for_updates()
    assert w.update_thread is None and calls == []
