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

        "home.drop_title": "Drop your recording here",
        "home.or": "or",
        "home.choose": "Choose a file…",
        "home.recent": "Recent transcripts",
        "home.err.many": "Please drop one recording at a time.",
        "home.err.folder": "That's a folder. Please drop a single recording.",
        "home.err.not_audio": "That doesn't look like a recording. Please choose an audio file (for example .m4a, .mp3 or .wav).",
        "home.err.missing": "That file can't be found. Was it moved or deleted?",

        "flow.home": "← Back to start",
        "flow.names.title": "Any names in this recording?",
        "flow.names.hint": "Book titles, authors, characters, places. One per line. This helps spell them right. You can skip this.",
        "flow.names.load": "Load a saved list…",
        "flow.names.import": "Import from file…",
        "flow.names.save": "Save this list as:",
        "flow.names.save_placeholder": "for example: Chasing Homer",
        "flow.skip": "Skip",
        "flow.continue": "Continue",
        "flow.advanced": "Advanced",
        "flow.adv.language": "Language of the recording",
        "flow.adv.model": "Speech model",
        "flow.adv.timestamps": "Add the time at the start of each line",
        "flow.adv.device": "Run on",
        "device.auto": "Automatic",
        "device.cuda": "Graphics card",
        "device.cpu": "Processor only (slower)",
        "flow.loading": "Starting… this can take a minute.",
        "flow.transcribing": "Turning speech into text…",
        "flow.eta": "{time} left",
        "flow.cancel": "Cancel",
        "flow.confirm_cancel": "Stop transcribing? What's done so far will be discarded.",
        "flow.confirm_cancel_yes": "Stop",
        "flow.confirm_cancel_no": "Keep going",
        "flow.no_speech": "No speech was found in this recording.",
        "flow.another_file": "Choose another file",
        "flow.err.bad_audio": "This file can't be played as audio. Please choose a recording (for example .m4a, .mp3 or .wav).",
        "flow.err.not_found": "The recording can't be found anymore. Was it moved or deleted?",
        "flow.err.model": "The transcriber couldn't start on the graphics card.",
        "flow.err.write": "The text couldn't be saved next to the recording.",
        "flow.err.unknown": "Something went wrong while transcribing.",
        "flow.try_cpu": "Try without graphics card",
        "flow.choose_location": "Choose where to save",
        "flow.try_again": "Try again",
        "flow.details": "Show details",
        "result.title": "Your transcript is ready",
        "result.saved_at": "Saved as: {path}",
        "result.open_folder": "Open folder",

        "result.choose": "Fix mistakes? Choose one:",
        "result.local": "Fix it here (private)",
        "result.local_soon": "Coming in the next version",
        "result.export": "Prepare for ChatGPT / Claude / Gemini",
        "result.export_hint": "Free and best for Persian. You paste the text into the AI yourself.",
        "result.just_save": "Keep the text as it is",

        "export.back": "← Back",
        "export.title": "Fix it with ChatGPT, Claude or Gemini",
        "export.howto": "1. Open ChatGPT, Claude or Gemini in your web browser.\n"
                        "2. Press Copy for part 1, paste it into the chat and send it.\n"
                        "3. Copy the AI's whole answer and paste it into the box at the bottom.\n"
                        "Repeat for every part, then press Check the answers.",
        "export.names": "Names (one per line), so the AI spells them right:",
        "export.part": "Part {i} of {n}",
        "export.copy": "Copy",
        "export.copied": "Copied ✓",
        "export.save_all": "Save all parts…",
        "export.paste_label": "Paste the AI's answers here (all parts together is fine):",
        "export.check": "Check the answers",
        "export.nothing": "No numbered lines were found in what you pasted. Paste the AI's answer exactly as it came, including the [1], [2]… numbers.",

        "review.back": "← Back to answers",
        "review.title": "Check the corrections",
        "review.summary": "{fixed} lines fixed · {kept} kept as they were · {missing} not answered yet",
        "review.col_n": "#",
        "review.col_original": "Original",
        "review.col_corrected": "Corrected",
        "review.col_use": "Use fix",
        "review.only_changed": "Show only changed lines",
        "review.too_different": "The AI changed this line too much, so the original is kept. Tick it to use the AI's version anyway.",
        "review.save": "Save",
        "review.copy": "Copy",
        "review.saved": "Saved as: {path}",
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

        "home.drop_title": "فایل ضبط‌شده را اینجا رها کنید",
        "home.or": "یا",
        "home.choose": "انتخاب فایل…",
        "home.recent": "متن‌های اخیر",
        "home.err.many": "لطفاً هر بار فقط یک فایل ضبط‌شده رها کنید.",
        "home.err.folder": "این یک پوشه است. لطفاً یک فایل ضبط‌شده رها کنید.",
        "home.err.not_audio": "این شبیه فایل صوتی نیست. لطفاً یک فایل صوتی انتخاب کنید (مثلاً ‎.m4a، ‎.mp3 یا ‎.wav).",
        "home.err.missing": "این فایل پیدا نمی‌شود. جابه‌جا یا پاک شده است؟",

        "flow.home": "بازگشت به شروع →",
        "flow.names.title": "در این ضبط اسم خاصی هست؟",
        "flow.names.hint": "نام کتاب‌ها، نویسنده‌ها، شخصیت‌ها و مکان‌ها؛ هر کدام در یک خط. این کار به درست نوشتن آن‌ها کمک می‌کند. می‌توانید رد شوید.",
        "flow.names.load": "بارگذاری فهرست ذخیره‌شده…",
        "flow.names.import": "وارد کردن از فایل…",
        "flow.names.save": "این فهرست ذخیره شود با نام:",
        "flow.names.save_placeholder": "مثلاً: تعقیب هومر",
        "flow.skip": "رد شدن",
        "flow.continue": "ادامه",
        "flow.advanced": "پیشرفته",
        "flow.adv.language": "زبان ضبط",
        "flow.adv.model": "مدل گفتاری",
        "flow.adv.timestamps": "زمان در ابتدای هر خط نوشته شود",
        "flow.adv.device": "اجرا روی",
        "device.auto": "خودکار",
        "device.cuda": "کارت گرافیک",
        "device.cpu": "فقط پردازنده (کندتر)",
        "flow.loading": "در حال شروع… ممکن است یک دقیقه طول بکشد.",
        "flow.transcribing": "در حال تبدیل گفتار به متن…",
        "flow.eta": "{time} مانده",
        "flow.cancel": "لغو",
        "flow.confirm_cancel": "تبدیل متوقف شود؟ آنچه تا اینجا انجام شده کنار گذاشته می‌شود.",
        "flow.confirm_cancel_yes": "توقف",
        "flow.confirm_cancel_no": "ادامه بده",
        "flow.no_speech": "در این ضبط گفتاری پیدا نشد.",
        "flow.another_file": "انتخاب فایل دیگر",
        "flow.err.bad_audio": "این فایل به‌عنوان صدا پخش نمی‌شود. لطفاً یک فایل ضبط‌شده انتخاب کنید (مثلاً ‎.m4a، ‎.mp3 یا ‎.wav).",
        "flow.err.not_found": "فایل ضبط‌شده دیگر پیدا نمی‌شود. جابه‌جا یا پاک شده است؟",
        "flow.err.model": "تبدیل‌کننده نتوانست روی کارت گرافیک شروع کند.",
        "flow.err.write": "متن کنار فایل ضبط‌شده ذخیره نشد.",
        "flow.err.unknown": "هنگام تبدیل به متن مشکلی پیش آمد.",
        "flow.try_cpu": "امتحان بدون کارت گرافیک",
        "flow.choose_location": "انتخاب محل ذخیره",
        "flow.try_again": "دوباره امتحان کن",
        "flow.details": "نمایش جزئیات",
        "result.title": "متن شما آماده است",
        "result.saved_at": "ذخیره شد در: {path}",
        "result.open_folder": "باز کردن پوشه",

        "result.choose": "اشتباه‌ها اصلاح شوند؟ یکی را انتخاب کنید:",
        "result.local": "اصلاح همین‌جا (خصوصی)",
        "result.local_soon": "در نسخهٔ بعدی",
        "result.export": "آماده‌سازی برای ChatGPT / Claude / Gemini",
        "result.export_hint": "رایگان و بهترین برای فارسی. متن را خودتان در هوش مصنوعی می‌گذارید.",
        "result.just_save": "متن همین‌طور بماند",

        "export.back": "بازگشت →",
        "export.title": "اصلاح با ChatGPT، Claude یا Gemini",
        "export.howto": "۱. ChatGPT، Claude یا Gemini را در مرورگر باز کنید.\n"
                        "۲. برای بخش ۱ «کپی» را بزنید، در گفتگو بچسبانید و بفرستید.\n"
                        "۳. کل پاسخ هوش مصنوعی را کپی کنید و در کادر پایین بچسبانید.\n"
                        "این کار را برای همهٔ بخش‌ها تکرار کنید و بعد «بررسی پاسخ‌ها» را بزنید.",
        "export.names": "نام‌ها (هر کدام در یک خط) تا هوش مصنوعی درست بنویسد:",
        "export.part": "بخش {i} از {n}",
        "export.copy": "کپی",
        "export.copied": "کپی شد ✓",
        "export.save_all": "ذخیرهٔ همهٔ بخش‌ها…",
        "export.paste_label": "پاسخ‌های هوش مصنوعی را اینجا بچسبانید (همهٔ بخش‌ها با هم هم اشکالی ندارد):",
        "export.check": "بررسی پاسخ‌ها",
        "export.nothing": "در متنی که چسباندید خط شماره‌داری پیدا نشد. پاسخ هوش مصنوعی را همان‌طور که آمده، با شماره‌های [1]، [2]… بچسبانید.",

        "review.back": "بازگشت به پاسخ‌ها →",
        "review.title": "بررسی اصلاح‌ها",
        "review.summary": "{fixed} خط اصلاح شد · {kept} خط دست‌نخورده ماند · {missing} خط هنوز پاسخ ندارد",
        "review.col_n": "#",
        "review.col_original": "متن اصلی",
        "review.col_corrected": "اصلاح‌شده",
        "review.col_use": "استفاده",
        "review.only_changed": "فقط خط‌های تغییرکرده نشان داده شوند",
        "review.too_different": "هوش مصنوعی این خط را بیش از حد تغییر داده، برای همین متن اصلی نگه داشته شد. اگر باز هم نسخهٔ هوش مصنوعی را می‌خواهید، تیک بزنید.",
        "review.save": "ذخیره",
        "review.copy": "کپی",
        "review.saved": "ذخیره شد در: {path}",
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
