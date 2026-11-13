"""Camera ownership and startup errors for cooperating HeadMouse processes."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import sys


class CameraStartupError(RuntimeError):
    def __init__(self, category, message):
        super().__init__(message)
        self.category = category


@contextmanager
def camera_session():
    if sys.platform != "win32":
        yield
        return

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateMutexW(None, False, r"Local\HeadMouse.CameraSession")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        status = kernel.WaitForSingleObject(handle, 0)
        if status == 258:  # WAIT_TIMEOUT
            raise CameraStartupError("busy", "Cámara ocupada por otra instancia de HeadMouse. "
                                     "Cerrá su diagnóstico o detené su cámara y volvé a intentar.")
        acquired = status in (0, 128)  # WAIT_OBJECT_0 or WAIT_ABANDONED
        if not acquired:
            raise ctypes.WinError(ctypes.get_last_error())
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)
