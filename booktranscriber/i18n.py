"""User-visible text in English and Persian, plus number/size/time formatting per language.

Every key must exist in both languages (tests enforce it). Add strings here in the same
change that adds the widget showing them.
"""
import logging

from PySide6.QtCore import QObject, Signal

LANGUAGES = ("en", "fa")

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app.title": "Book Transcriber",
        "lang.switch": "فا",

        "setup.welcome.title": "Welcome!",
        "setup.welcome.body": "Before your first transcript, the app needs to download a few things. "
                              "This happens only once.",
        "setup.check.gpu_ok": "Your computer: works well ({gpu} found)",
        "setup.check.no_gpu": "Your computer: works, but transcribing will be slower (no NVIDIA graphics card found)",
        "setup.check.time": "About {time} on a normal connection",
        "setup.check.space": "Needs {needed} free space (you have {free})",
        "setup.check.space_low": "Needs {needed} free space, but this computer only has {free} free",
        "setup.reuse_existing": "Use the speech model already on this computer (saves {size})",
        "setup.start": "Start download",
        "setup.downloading.title": "Getting ready…",
        "setup.resume_note": "You can keep using your computer. If the internet drops, it will continue where it stopped.",
        "setup.overall": "Overall",
        "setup.overall_status": "{pct}% · {time} left",
        "setup.overall_status_noeta": "{pct}%",
        "setup.item.check": "Checking your computer",
        "setup.item.gpu": "Graphics card support",
        "setup.item.whisper": "Speech-to-text model",
        "setup.item.test": "Quick test",
        "setup.item.done": "done",
        "setup.item.waiting": "waiting",
        "setup.item.waiting_size": "waiting · {size}",
        "setup.item.bytes": "{done} / {total}",
        "setup.item.testing": "testing…",
        "setup.pause": "Pause",
        "setup.continue": "Continue",
        "setup.ready.title": "All set!",
        "setup.ready.body": "Everything is downloaded and tested. From now on the app works without internet.",
        "setup.ready.go": "Transcribe my first recording →",

        "error.network.title": "The internet connection was lost",
        "error.network.body": "Don't worry, nothing is lost. {done} is already saved. "
                              "Check your Wi-Fi, then press Try again.",
        "error.disk.title": "Not enough space",
        "error.disk.body": "The app needs {needed} but this computer has {free} free. "
                           "Delete some files, then press Check again.",
        "error.checksum.title": "A file arrived damaged",
        "error.checksum.body": "It will be downloaded again. Press Try again.",
        "error.gpu.title": "The graphics card couldn't be used",
        "error.gpu.body": "The app can still work without it, just slower.",
        "error.test.title": "Something went wrong during the test",
        "error.test.body": "Press Try again. If it keeps happening, the details can help someone fix it.",
        "error.try_again": "Try again",
        "error.check_again": "Check again",
        "error.use_cpu": "Continue without graphics card",
        "error.details": "Show details",

        "settings.menu": "Settings",
        "settings.repair": "Check / repair setup",
        "confirm.quit_busy": "The app is still working. Stop and quit?",
        "confirm.yes_quit": "Stop and quit",
        "confirm.keep_working": "Keep working",
    },
    "fa": {
        "app.title": "کتاب‌نویس",
        "lang.switch": "EN",

        "setup.welcome.title": "خوش آمدید!",
        "setup.welcome.body": "پیش از اولین متن، برنامه باید چند چیز را دانلود کند. "
                              "این کار فقط یک بار انجام می‌شود.",
        "setup.check.gpu_ok": "رایانهٔ شما: به‌خوبی کار می‌کند (کارت گرافیک {gpu} پیدا شد)",
        "setup.check.no_gpu": "رایانهٔ شما: کار می‌کند، ولی تبدیل به متن کندتر است (کارت گرافیک انویدیا پیدا نشد)",
        "setup.check.time": "حدود {time} با اینترنت معمولی",
        "setup.check.space": "به {needed} فضای خالی نیاز دارد (شما {free} دارید)",
        "setup.check.space_low": "به {needed} فضای خالی نیاز دارد، ولی این رایانه فقط {free} فضای خالی دارد",
        "setup.reuse_existing": "از مدل گفتاری که روی این رایانه هست استفاده شود ({size} صرفه‌جویی)",
        "setup.start": "شروع دانلود",
        "setup.downloading.title": "در حال آماده‌سازی…",
        "setup.resume_note": "می‌توانید با رایانه کار کنید. اگر اینترنت قطع شود، از همان‌جا ادامه می‌دهد.",
        "setup.overall": "پیشرفت کل",
        "setup.overall_status": "{pct}٪ · {time} مانده",
        "setup.overall_status_noeta": "{pct}٪",
        "setup.item.check": "بررسی رایانه",
        "setup.item.gpu": "پشتیبانی کارت گرافیک",
        "setup.item.whisper": "مدل تبدیل گفتار به متن",
        "setup.item.test": "آزمایش کوتاه",
        "setup.item.done": "انجام شد",
        "setup.item.waiting": "در انتظار",
        "setup.item.waiting_size": "در انتظار · {size}",
        "setup.item.bytes": "{done} از {total}",
        "setup.item.testing": "در حال آزمایش…",
        "setup.pause": "توقف",
        "setup.continue": "ادامه",
        "setup.ready.title": "همه‌چیز آماده است!",
        "setup.ready.body": "همه‌چیز دانلود و آزمایش شد. از این به بعد برنامه بدون اینترنت کار می‌کند.",
        "setup.ready.go": "← اولین ضبطم را به متن تبدیل کن",

        "error.network.title": "اتصال اینترنت قطع شد",
        "error.network.body": "نگران نباشید، چیزی از دست نرفته. {done} ذخیره شده است. "
                              "وای‌فای را بررسی کنید و «دوباره امتحان کن» را بزنید.",
        "error.disk.title": "فضای کافی نیست",
        "error.disk.body": "برنامه به {needed} نیاز دارد ولی این رایانه {free} فضای خالی دارد. "
                           "چند فایل را پاک کنید و «دوباره بررسی کن» را بزنید.",
        "error.checksum.title": "یک فایل خراب رسید",
        "error.checksum.body": "دوباره دانلود می‌شود. «دوباره امتحان کن» را بزنید.",
        "error.gpu.title": "از کارت گرافیک نمی‌شد استفاده کرد",
        "error.gpu.body": "برنامه بدون آن هم کار می‌کند، فقط کندتر.",
        "error.test.title": "در آزمایش مشکلی پیش آمد",
        "error.test.body": "«دوباره امتحان کن» را بزنید. اگر باز تکرار شد، جزئیات به رفع مشکل کمک می‌کند.",
        "error.try_again": "دوباره امتحان کن",
        "error.check_again": "دوباره بررسی کن",
        "error.use_cpu": "ادامه بدون کارت گرافیک",
        "error.details": "نمایش جزئیات",

        "settings.menu": "تنظیمات",
        "settings.repair": "بررسی / تعمیر نصب",
        "confirm.quit_busy": "برنامه هنوز در حال کار است. متوقف شود و بسته شود؟",
        "confirm.yes_quit": "توقف و خروج",
        "confirm.keep_working": "ادامهٔ کار",
    },
}

_FA_DIGITS = str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫")
_log = logging.getLogger(__name__)


def initial_language(saved: str | None, locale_name: str) -> str:
    if saved in LANGUAGES:
        return saved
    return "fa" if locale_name.startswith("fa") else "en"


def fmt_number(n, lang: str) -> str:
    s = str(n)
    return s.translate(_FA_DIGITS) if lang == "fa" else s


def fmt_bytes(n: int, lang: str) -> str:
    if n >= 1_000_000_000:
        value, unit = f"{n / 1e9:.1f}", ("گیگابایت" if lang == "fa" else "GB")
    else:
        value, unit = f"{round(n / 1e6)}", ("مگابایت" if lang == "fa" else "MB")
    return f"{fmt_number(value, lang)} {unit}"


def fmt_duration(seconds: float, lang: str) -> str:
    minutes = round(seconds / 60)
    if seconds < 60 or minutes < 1:
        return "کمتر از یک دقیقه" if lang == "fa" else "less than a minute"
    h, m = divmod(minutes, 60)
    if lang == "fa":
        parts = ([f"{fmt_number(h, lang)} ساعت"] if h else []) + ([f"{fmt_number(m, lang)} دقیقه"] if m else [])
        return "حدود " + " و ".join(parts)
    parts = ([f"{h} h"] if h else []) + ([f"{m} min"] if m else [])
    return "about " + " ".join(parts)


class I18n(QObject):
    language_changed = Signal(str)

    def __init__(self, language: str = "en"):
        super().__init__()
        self.language = language if language in LANGUAGES else "en"
        self._missing: set[str] = set()

    def tr(self, key: str, **kw) -> str:
        text = STRINGS[self.language].get(key)
        if text is None:
            if key not in self._missing:
                self._missing.add(key)
                _log.warning("missing translation key %s", key)
            return key
        return text.format(**kw) if kw else text

    def set_language(self, lang: str) -> None:
        if lang in LANGUAGES and lang != self.language:
            self.language = lang
            self.language_changed.emit(lang)

    def is_rtl(self) -> bool:
        return self.language == "fa"
