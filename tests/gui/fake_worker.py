"""Stand-in for the worker process in GUI runner tests: prints scripted events."""
import json
import sys
import time

mode = sys.argv[1]
out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else ""


def emit(**e):
    print(json.dumps(e, ensure_ascii=False), flush=True)


if mode == "ok":
    emit(type="loaded", backend="cpu/int8")
    print("some library noise", flush=True)
    emit(type="duration", seconds=4.0)
    emit(type="segment", start=0.0, end=2.0, text="سلام")
    emit(type="progress", done=2.0, total=4.0, eta=1.0)
    emit(type="segment", start=2.0, end=4.0, text="دنیا")
    emit(type="done", out=out, segments=2)
elif mode == "error":
    emit(type="error", kind="bad_audio", message="no audio stream")
    sys.exit(1)
elif mode == "error_then_linger":
    emit(type="error", kind="model", message="cublas")
    time.sleep(1.0)     # exits only after the GUI may already have started a retry
    sys.exit(1)
elif mode == "crash":
    print("Segmentation fault in libcudnn", file=sys.stderr, flush=True)
    sys.exit(139)
elif mode == "slow":
    open(out + ".part", "w").write("partial")
    emit(type="loaded", backend="cpu/int8")
    time.sleep(60)
