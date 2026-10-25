# PyInstaller spec for Writing Parrot: one folder, windowed.
#   pyinstaller packaging/writing_parrot.spec --noconfirm      ->  dist/WritingParrot/WritingParrot.exe
# On macOS the folder is also wrapped as dist/WritingParrot.app.
# The CUDA wheels (nvidia-*) are never bundled: setup downloads them into the data folder.
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(SPECPATH)
MAC = sys.platform == "darwin"
sys.path.insert(0, ROOT)
from booktranscriber import __version__  # noqa: E402

datas = [(os.path.join(ROOT, "booktranscriber", "assets"), os.path.join("booktranscriber", "assets"))]
binaries = []
hiddenimports = collect_submodules("booktranscriber") + ["PySide6.QtSvg"]
# faster_whisper carries the VAD model in assets/; onnxruntime runs it.
for pkg in ("faster_whisper", "ctranslate2", "av", "onnxruntime", "tokenizers", "huggingface_hub"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Qt modules the app never imports (the build machine may have PySide6_Addons installed).
QT_UNUSED = [f"PySide6.{m}" for m in (
    "Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender", "QtBluetooth",
    "QtCharts", "QtDataVisualization", "QtGraphs", "QtHelp", "QtLocation", "QtMultimedia",
    "QtMultimediaWidgets", "QtNetworkAuth", "QtNfc", "QtOpenGL", "QtOpenGLWidgets", "QtPdf",
    "QtPdfWidgets", "QtPositioning", "QtQml", "QtQuick", "QtQuick3D", "QtQuickControls2", "QtQuickWidgets",
    "QtRemoteObjects", "QtScxml", "QtSensors", "QtSerialBus", "QtSerialPort", "QtSpatialAudio", "QtSql",
    "QtStateMachine", "QtTest", "QtTextToSpeech", "QtWebChannel", "QtWebEngineCore", "QtWebEngineQuick",
    "QtWebEngineWidgets", "QtWebSockets", "QtWebView", "QtDesigner", "QtUiTools", "QtAxContainer",
)]

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["nvidia", "tkinter", "_tkinter", "pytest", "_pytest", "pytestqt"] + QT_UNUSED,
    noarchive=False,
)


def _is_cuda_wheel(dest, src):
    parts = os.path.normpath(src).split(os.sep)
    return dest.replace("\\", "/").startswith("nvidia/") or ("site-packages" in parts and "nvidia" in parts)


a.binaries = [e for e in a.binaries if not _is_cuda_wheel(e[0], e[1])]
a.datas = [e for e in a.datas if not _is_cuda_wheel(e[0], e[1])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WritingParrot",
    icon=os.path.join(ROOT, "booktranscriber", "assets", "icon.icns" if MAC else "icon.ico"),
    console=False,
    upx=False,          # UPX-packed files trip antivirus heuristics
    debug=False,
    strip=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="WritingParrot",
    upx=False,
    strip=False,
)

if MAC:
    app = BUNDLE(
        coll,
        name="WritingParrot.app",
        icon=os.path.join(ROOT, "booktranscriber", "assets", "icon.icns"),
        bundle_identifier="io.github.javadtavakoli.writingparrot",
        version=__version__,
        info_plist={
            "CFBundleDisplayName": "Writing Parrot",
            "CFBundleName": "Writing Parrot",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
