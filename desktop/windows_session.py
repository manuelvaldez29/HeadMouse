"""Avisos nativos de sesión/energía y F8 global cuando Windows lo concede."""
import sys
from PySide6.QtCore import QAbstractNativeEventFilter


def desktop_unlocked():
    if sys.platform!="win32":return True
    import ctypes
    from ctypes import wintypes
    user=ctypes.WinDLL("user32",use_last_error=True)
    user.OpenInputDesktop.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    user.OpenInputDesktop.restype=wintypes.HANDLE
    user.GetUserObjectInformationW.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    user.CloseDesktop.argtypes=[wintypes.HANDLE]
    handle=user.OpenInputDesktop(0,False,0x0001)
    if not handle:return False
    try:
        name=ctypes.create_unicode_buffer(256);needed=wintypes.DWORD()
        return bool(user.GetUserObjectInformationW(handle,2,name,ctypes.sizeof(name),ctypes.byref(needed)) and name.value.lower()=="default")
    finally:user.CloseDesktop(handle)


class WindowsSession(QAbstractNativeEventFilter):
    HOTKEY=0x484D
    def __init__(self,window,on_stop,on_session):
        super().__init__();self.window=window;self.on_stop=on_stop;self.on_session=on_session
        self.hotkey=False;self.registered=False;self.handle=None
        if sys.platform!="win32":return
        import ctypes
        from ctypes import wintypes
        self.user=ctypes.WinDLL("user32",use_last_error=True)
        self.wts=ctypes.WinDLL("wtsapi32",use_last_error=True)
        self.user.RegisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int,wintypes.UINT,wintypes.UINT]
        self.user.UnregisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int]
        self.wts.WTSRegisterSessionNotification.argtypes=[wintypes.HWND,wintypes.DWORD]
        self.wts.WTSUnRegisterSessionNotification.argtypes=[wintypes.HWND]
        self.handle=int(window.winId())
        self.hotkey=bool(self.user.RegisterHotKey(self.handle,self.HOTKEY,0x4000,0x77))
        self.registered=bool(self.wts.WTSRegisterSessionNotification(self.handle,0))

    def dispatch(self,message,wparam):
        if message==0x0312 and wparam==self.HOTKEY:self.on_stop();return True
        if message==0x02B1:
            if wparam in (2,4,6,7):self.on_session(False)
            elif wparam in (1,3,5,8):self.on_session(True)
        elif message==0x0218:
            if wparam in (0,4):self.on_session(False)
            elif wparam in (7,18):self.on_session(True)
        elif message in (0x0011,0x0016):self.on_session(False)
        return False

    def nativeEventFilter(self,event_type,message):
        if sys.platform=="win32":
            import ctypes
            from ctypes import wintypes
            msg=wintypes.MSG.from_address(int(message))
            return self.dispatch(msg.message,msg.wParam),0
        return False,0

    def close(self):
        if self.handle:
            if self.hotkey:self.user.UnregisterHotKey(self.handle,self.HOTKEY)
            if self.registered:self.wts.WTSUnRegisterSessionNotification(self.handle)
            self.handle=None
