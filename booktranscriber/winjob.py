"""Win32 Job Objects and process handles, so llama-server can never outlive the app on Windows.

A job made with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE ends every process in it when its last handle
closes, and Windows closes the app's handles even when the app crashes. Everything here is a
harmless no-op (None/False) on other systems.
"""
import ctypes
import sys
from ctypes import wintypes

PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
ERROR_ACCESS_DENIED = 5
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9    # the JOBOBJECTINFOCLASS value
_DWORD = ctypes.c_uint32    # wintypes.DWORD is 8 bytes off Windows; this keeps the layout checkable anywhere


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", _DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", _DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", _DWORD),
                ("SchedulingClass", _DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


WINDOWS = sys.platform == "win32"
if WINDOWS:
    _k = ctypes.WinDLL("kernel32", use_last_error=True)

    def _fn(name, restype, *argtypes):
        f = getattr(_k, name)
        f.restype, f.argtypes = restype, list(argtypes)    # explicit, so 64-bit handles aren't truncated
        return f

    _CreateJobObjectW = _fn("CreateJobObjectW", wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCWSTR)
    _SetInformationJobObject = _fn("SetInformationJobObject", wintypes.BOOL, wintypes.HANDLE, ctypes.c_int,
                                   wintypes.LPVOID, wintypes.DWORD)
    _AssignProcessToJobObject = _fn("AssignProcessToJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.HANDLE)
    _TerminateJobObject = _fn("TerminateJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.UINT)
    _OpenProcess = _fn("OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _QueryFullProcessImageNameW = _fn("QueryFullProcessImageNameW", wintypes.BOOL, wintypes.HANDLE,
                                      wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    _GetExitCodeProcess = _fn("GetExitCodeProcess", wintypes.BOOL, wintypes.HANDLE,
                              ctypes.POINTER(wintypes.DWORD))
    _TerminateProcess = _fn("TerminateProcess", wintypes.BOOL, wintypes.HANDLE, wintypes.UINT)
    _CloseHandle = _fn("CloseHandle", wintypes.BOOL, wintypes.HANDLE)


def create_kill_on_close_job() -> int | None:
    """A new job that kills everything in it when its handle closes; None if that fails or off Windows."""
    if not WINDOWS:
        return None
    job = _CreateJobObjectW(None, None)
    if not job:
        return None
    info = _ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                    ctypes.sizeof(info)):
        _CloseHandle(job)
        return None
    return job


def assign(job: int, pid: int) -> bool:
    """Put the process in the job; the children it starts from then on join it too."""
    if not WINDOWS:
        return False
    handle = _OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(_AssignProcessToJobObject(job, handle))
    finally:
        _CloseHandle(handle)


def terminate_tree(job: int) -> None:
    """End every process in the job."""
    if WINDOWS:
        _TerminateJobObject(job, 1)


def close(job: int) -> None:
    """Close the job's handle (which also ends whatever is still in it)."""
    if WINDOWS:
        _CloseHandle(job)


def image_path(pid: int) -> str | None:
    """The full path of the executable the process runs, or None."""
    if not WINDOWS:
        return None
    handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not _QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value
    finally:
        _CloseHandle(handle)


def alive(pid: int) -> bool:
    """Whether the process is still running (one that exited is not, even while a handle keeps it known)."""
    if not WINDOWS:
        return False
    handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED    # it exists, it just isn't ours
    try:
        code = wintypes.DWORD()
        return bool(_GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        _CloseHandle(handle)


def kill(pid: int) -> None:
    if not WINDOWS:
        return
    handle = _OpenProcess(PROCESS_TERMINATE, False, pid)
    if handle:
        try:
            _TerminateProcess(handle, 1)
        finally:
            _CloseHandle(handle)
