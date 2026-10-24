"""PyInstaller entry point: the GUI by default, `--worker ...` for the transcription child."""
import multiprocessing
import sys

from booktranscriber.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
