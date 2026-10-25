## Writing Parrot {{VERSION}}

Turn long recordings into Persian (or any language) text on your own computer. Nothing is uploaded.

On first launch the app checks your computer and downloads what it needs (the speech model and, if you have an NVIDIA graphics card, support for it), with live progress.

**Windows 10/11**

1. Download `WritingParrot-Setup-{{VERSION}}.exe` below and double-click it. No administrator rights are needed.
2. Windows may warn that it "protected your PC", because the app isn't signed yet. Click **More info**, then **Run anyway**.

![Click More info, then Run anyway](https://raw.githubusercontent.com/javadtavakoli/book-transcriber/main/packaging/smartscreen.png)

Uninstall from Windows Settings → Apps. It asks whether to delete the downloads too; the default keeps them for a later reinstall.

**Ubuntu 22.04 or newer**

1. Download `writing-parrot_{{VERSION}}_amd64.deb` below.
2. In a terminal, in the folder you downloaded it to, run `sudo apt install ./writing-parrot_{{VERSION}}_amd64.deb` (or double-click the file to install it with App Center).
3. Open **Writing Parrot** from your apps.

Uninstall with `sudo apt remove writing-parrot`. Your downloads stay in `~/.local/share/WritingParrot`; delete that folder to free the space.

**macOS 12 or newer, Apple Silicon (M1 and later)**

1. Download `WritingParrot-{{VERSION}}-macos-arm64.dmg` below, open it, and drag **Writing Parrot** into **Applications**.
2. Open it. The app isn't signed by Apple yet, so the first time macOS refuses: click **Done**.
3. Open **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to Writing Parrot. Confirm with your password. After this it opens normally.

On a Mac speech is recognised on the processor, which is much slower than on an NVIDIA graphics card. Uninstall by moving the app to the Trash; your downloads are in `~/Library/Application Support/WritingParrot`.

`SHA256SUMS.txt` holds the checksums of all three downloads.

---

<div dir="rtl">

## طوطی‌نویس {{VERSION}}

ضبط‌های طولانی را روی کامپیوتر خودتان به متن فارسی (یا هر زبان دیگری) تبدیل کنید. هیچ چیزی جایی فرستاده نمی‌شود.

برنامه بار اول کامپیوترتان را بررسی می‌کند و چیزهایی را که لازم دارد (مدل گفتار و اگر کارت گرافیک NVIDIA دارید، پشتیبانی آن) دانلود می‌کند و پیشرفت کار را نشان می‌دهد.

**ویندوز ۱۰ و ۱۱**

۱. فایل `WritingParrot-Setup-{{VERSION}}.exe` را از پایین همین صفحه دانلود کنید و روی آن دوبار کلیک کنید. دسترسی مدیر سیستم لازم نیست.

۲. ممکن است ویندوز هشدار بدهد که «از کامپیوتر شما محافظت کرد»، چون برنامه هنوز امضای دیجیتال ندارد. اول روی **More info** و بعد روی **Run anyway** کلیک کنید.

برای حذف برنامه به Settings → Apps در ویندوز بروید. می‌پرسد که فایل‌های دانلودشده هم پاک شوند یا نه؛ پیش‌فرض این است که بمانند تا اگر دوباره نصبش کردید، لازم نباشد از نو دانلودشان کنید.

**اوبونتو ۲۲.۰۴ یا جدیدتر**

۱. فایل `writing-parrot_{{VERSION}}_amd64.deb` را از پایین همین صفحه دانلود کنید.

۲. در ترمینال، در پوشه‌ای که فایل را دانلود کرده‌اید، دستور `sudo apt install ./writing-parrot_{{VERSION}}_amd64.deb` را اجرا کنید (یا روی فایل دوبار کلیک کنید تا با App Center نصب شود).

۳. **Writing Parrot** را از فهرست برنامه‌ها باز کنید.

برای حذف برنامه دستور `sudo apt remove writing-parrot` را اجرا کنید. فایل‌های دانلودشده در `~/.local/share/WritingParrot` می‌مانند؛ برای آزاد کردن فضا آن پوشه را پاک کنید.

**مک با macOS 12 یا جدیدتر و تراشهٔ Apple Silicon (M1 و بعد از آن)**

۱. فایل `WritingParrot-{{VERSION}}-macos-arm64.dmg` را از پایین همین صفحه دانلود کنید، بازش کنید و **Writing Parrot** را به پوشهٔ **Applications** بکشید.

۲. برنامه را باز کنید. برنامه هنوز امضای اپل را ندارد، پس بار اول مک اجازه نمی‌دهد: روی **Done** کلیک کنید.

۳. به **System Settings → Privacy & Security** بروید، پایین بیایید و کنار Writing Parrot روی **Open Anyway** کلیک کنید و رمز عبورتان را وارد کنید. از این به بعد برنامه عادی باز می‌شود.

روی مک تشخیص گفتار با پردازنده انجام می‌شود که خیلی کندتر از کارت گرافیک NVIDIA است. برای حذف، برنامه را به سطل زباله بیندازید؛ فایل‌های دانلودشده در `~/Library/Application Support/WritingParrot` هستند.

</div>
