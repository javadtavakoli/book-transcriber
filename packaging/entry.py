"""PyInstaller entry point: the GUI by default, `--worker ...` for the transcription child."""
import multiprocessing
import os
import sys

if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
    # The bootloader points LD_LIBRARY_PATH at the bundle. This process has already read it; give programs
    # started from here (the AI helper, xdg-open) the user's own value, or they'd load the bundle's libraries.
    # A worker child is this same executable, and its bootloader sets the bundle path again.
    if "LD_LIBRARY_PATH_ORIG" in os.environ:
        os.environ["LD_LIBRARY_PATH"] = os.environ.pop("LD_LIBRARY_PATH_ORIG")
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)

from booktranscriber.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
