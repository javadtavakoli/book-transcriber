"""`python -m booktranscriber` opens the GUI; `--worker ...` runs the transcription worker
(the same entry point works inside a frozen app, where `-m` isn't available).
`--smoke [--smoke-out FILE]` is a build self-check: it builds the window and exits."""
import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        from .worker import main as worker_main
        return worker_main(sys.argv[2:])
    if "--smoke" in sys.argv[1:]:
        from .gui.app import smoke
        args = sys.argv[1:]
        out = args[args.index("--smoke-out") + 1] if "--smoke-out" in args[:-1] else None
        return smoke(out)
    from .gui.app import main as gui_main
    return gui_main(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
