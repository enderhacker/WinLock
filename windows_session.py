"""Windows session notifications and a thread-scoped system sleep request."""

import ctypes as ct
from ctypes import wintypes as wt


class WindowsSession:
    _WM_WTSSESSION_CHANGE = 0x02B1
    _WTS_SESSION_LOCK = 7
    _WTS_SESSION_UNLOCK = 8
    _ES_CONTINUOUS = 0x80000000
    _ES_SYSTEM_REQUIRED = 0x00000001

    def __init__(self, hwnd):
        # Keep the callback alive until the window is destroyed or unsubscribed.
        self._hwnd = hwnd
        self._events = []
        self._registered = False
        self._subclassed = False
        self._user32 = ct.WinDLL("user32", use_last_error=True)
        self._kernel32 = ct.WinDLL("kernel32", use_last_error=True)
        self._wts = ct.WinDLL("wtsapi32", use_last_error=True)
        self._comctl = ct.WinDLL("comctl32", use_last_error=True)
        subclass_proc = ct.WINFUNCTYPE(
            wt.LPARAM, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.WPARAM, wt.WPARAM
        )

        self._comctl.SetWindowSubclass.argtypes = (wt.HWND, subclass_proc, wt.WPARAM, wt.WPARAM)
        self._comctl.SetWindowSubclass.restype = wt.BOOL
        self._comctl.RemoveWindowSubclass.argtypes = (wt.HWND, subclass_proc, wt.WPARAM)
        self._comctl.RemoveWindowSubclass.restype = wt.BOOL
        self._comctl.DefSubclassProc.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
        self._comctl.DefSubclassProc.restype = wt.LPARAM
        self._wts.WTSRegisterSessionNotification.argtypes = (wt.HWND, wt.DWORD)
        self._wts.WTSRegisterSessionNotification.restype = wt.BOOL
        self._wts.WTSUnRegisterSessionNotification.argtypes = (wt.HWND,)
        self._wts.WTSUnRegisterSessionNotification.restype = wt.BOOL
        self._user32.LockWorkStation.argtypes = ()
        self._user32.LockWorkStation.restype = wt.BOOL
        self._kernel32.SetThreadExecutionState.argtypes = (wt.DWORD,)
        self._kernel32.SetThreadExecutionState.restype = wt.DWORD

        self._callback = subclass_proc(self._on_message)

    def subscribe(self):
        if self._registered:
            return
        if not self._subclassed:
            if not self._comctl.SetWindowSubclass(self._hwnd, self._callback, 1, 0):
                raise OSError("No se pudo preparar la recepción de eventos de Windows.")
            self._subclassed = True
        if not self._wts.WTSRegisterSessionNotification(self._hwnd, 0):
            error = ct.WinError(ct.get_last_error())
            try:
                self.close()
            finally:
                raise error
        self._registered = True

    def _on_message(self, hwnd, message, wparam, lparam, _subclass_id, _ref_data):
        if message == self._WM_WTSSESSION_CHANGE:
            if wparam == self._WTS_SESSION_LOCK:
                self._events.append("lock")
            elif wparam == self._WTS_SESSION_UNLOCK:
                self._events.append("unlock")
        return self._comctl.DefSubclassProc(hwnd, message, wparam, lparam)

    def take_events(self):
        events, self._events = self._events, []
        return events

    def set_awake(self, enabled):
        flags = self._ES_CONTINUOUS | (self._ES_SYSTEM_REQUIRED if enabled else 0)
        if not self._kernel32.SetThreadExecutionState(flags):
            raise OSError("Windows no pudo cambiar la solicitud de energía.")

    def lock(self):
        if not self._user32.LockWorkStation():
            raise ct.WinError(ct.get_last_error())

    def close(self):
        try:
            if self._registered:
                if not self._wts.WTSUnRegisterSessionNotification(self._hwnd):
                    raise ct.WinError(ct.get_last_error())
                self._registered = False
        finally:
            if self._subclassed:
                if not self._comctl.RemoveWindowSubclass(self._hwnd, self._callback, 1):
                    raise OSError("No se pudo retirar el receptor de eventos de Windows.")
                self._subclassed = False
