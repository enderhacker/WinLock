LOCAL_VERSION = "v1.0"

import os
import sys
import threading
import time
import traceback

LOG_FOLDER_NAME = "WinLock"
LOG_FILE_NAME = f"logs-{time.strftime('%d_%m_%Y-%H_%M_%S')}-{os.getpid()}.txt"


def get_app_data_dir():
    """Obtiene la carpeta de datos de WinLock."""
    try:
        app_data_path = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(app_data_path, LOG_FOLDER_NAME)
    except Exception:
        return os.path.abspath(".")


LOG_DIRECTORY = get_app_data_dir()
LOG_FILE_PATH = os.path.join(LOG_DIRECTORY, LOG_FILE_NAME)
UPDATER_LOG_PATH = os.path.join(LOG_DIRECTORY, "updater.log")
RESTORE_STATE_PATH = os.path.join(LOG_DIRECTORY, "restore_state.json")
_log_lock = threading.Lock()


def write_log(message, *, level="INFO", error=None):
    """Escribe un mensaje con contexto y, si se indica, la traza de la excepción."""
    entry = message
    try:
        now = time.time()
        ms = int((now % 1) * 1000)
        timestamp = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))},{ms:03d}"
        entry = (
            f"[{timestamp}] [{level}] [PID {os.getpid()}:{threading.current_thread().name}] "
            f"- {message}\n"
        )
        if error is not None:
            entry += "".join(traceback.format_exception(type(error), error, error.__traceback__))
        with _log_lock:
            with open(LOG_FILE_PATH, "a", encoding="utf-8", errors="backslashreplace") as log_file:
                log_file.write(entry)
    except Exception as log_error:
        try:
            if sys.stderr is not None:
                print(f"Error al escribir en el log: {log_error}\n{entry}", file=sys.stderr)
        except Exception:
            pass


def _log_uncaught_exception(exc_type, exc_value, exc_traceback):
    if not issubclass(exc_type, KeyboardInterrupt):
        write_log("Excepción no controlada en el hilo principal.", level="ERROR", error=exc_value)
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def _log_thread_exception(args):
    if not issubclass(args.exc_type, SystemExit):
        write_log("Excepción no controlada en un hilo de trabajo.", level="ERROR", error=args.exc_value)
    threading.__excepthook__(args)


try:
    os.makedirs(LOG_DIRECTORY, exist_ok=True)
except OSError as e:
    print(f"No se pudo crear la carpeta de logs {LOG_DIRECTORY}: {e}", file=sys.stderr)

if __name__ == "__main__":
    sys.excepthook = _log_uncaught_exception
    threading.excepthook = _log_thread_exception
    write_log(f"Iniciando WinLock {LOCAL_VERSION} (Python {sys.version.split()[0]}).")

try:
    import ctypes
    import ctypes.wintypes
    import hashlib
    import json
    import ssl
    import subprocess
    import tkinter as tk
    from tkinter import messagebox, ttk
    import urllib.request
    import winreg
except ImportError as e:
    write_log("Faltan bibliotecas necesarias para iniciar WinLock.", level="ERROR", error=e)
    print(f"Faltan bibliotecas necesarias: {e}", file=sys.stderr)
    sys.exit(1)


class LoggedTk(tk.Tk):
    def report_callback_exception(self, exc_type, exc_value, exc_traceback):
        write_log("Error en un callback de Tkinter.", level="ERROR", error=exc_value)
        super().report_callback_exception(exc_type, exc_value, exc_traceback)


# Windows DPI Awareness para mapeo exacto de píxeles en multi-monitor
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception as e:
        write_log("No se pudo configurar la compatibilidad DPI de Windows.", level="WARNING", error=e)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
try:
    powrprof = ctypes.WinDLL("powrprof", use_last_error=True)
except Exception as e:
    powrprof = None
    write_log("La biblioteca de ajustes de energía no está disponible.", level="WARNING", error=e)

LRESULT = ctypes.c_ssize_t
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

HOOKPROC = ctypes.WINFUNCTYPE(
    LRESULT, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
)
WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
)
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.BOOL,
    ctypes.wintypes.HMONITOR,
    ctypes.wintypes.HDC,
    ctypes.POINTER(ctypes.wintypes.RECT),
    ctypes.wintypes.LPARAM,
)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, guid_str):
        parts = guid_str.strip().strip("{}").split("-")
        d4 = bytes.fromhex(parts[3] + parts[4])
        return cls(
            int(parts[0], 16),
            int(parts[1], 16),
            int(parts[2], 16),
            (ctypes.c_ubyte * 8)(*d4),
        )

    def to_string(self):
        d4 = bytes(self.Data4)
        return (
            f"{self.Data1:08x}-{self.Data2:04x}-{self.Data3:04x}-"
            f"{d4[:2].hex()}-{d4[2:].hex()}"
        )


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("hCursor", ctypes.wintypes.HANDLE),
        ("ptScreenPos", ctypes.wintypes.POINT),
    ]


# Firmas explícitas de Win32 API (seguras en 32-bit y 64-bit)
_set_window_long_ptr = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
_set_window_long_ptr.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
_set_window_long_ptr.restype = ctypes.c_void_p

user32.CallWindowProcW.argtypes = [
    ctypes.c_void_p,
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
user32.CallWindowProcW.restype = LRESULT

user32.GetKeyboardLayout.argtypes = [ctypes.wintypes.DWORD]
user32.GetKeyboardLayout.restype = ctypes.wintypes.HKL

user32.GetKeyState.argtypes = [ctypes.c_int]
user32.GetKeyState.restype = ctypes.c_short

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

user32.ToUnicodeEx.argtypes = [
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_ubyte),
    ctypes.c_wchar_p,
    ctypes.c_int,
    ctypes.c_uint,
    ctypes.wintypes.HKL,
]
user32.ToUnicodeEx.restype = ctypes.c_int

user32.SetWindowPos.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]
user32.SetWindowPos.restype = ctypes.wintypes.BOOL

user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
user32.SetForegroundWindow.restype = ctypes.wintypes.BOOL

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = ctypes.wintypes.HWND

user32.GetWindowThreadProcessId.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.POINTER(ctypes.wintypes.DWORD),
]
user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD

user32.GetParent.argtypes = [ctypes.wintypes.HWND]
user32.GetParent.restype = ctypes.wintypes.HWND

user32.GetAncestor.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint]
user32.GetAncestor.restype = ctypes.wintypes.HWND

user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.wintypes.LPARAM]
user32.EnumWindows.restype = ctypes.wintypes.BOOL

user32.EnumDisplayMonitors.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    MONITORENUMPROC,
    ctypes.wintypes.LPARAM,
]
user32.EnumDisplayMonitors.restype = ctypes.wintypes.BOOL

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

user32.GetClassNameW.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.wintypes.LPWSTR,
    ctypes.c_int,
]
user32.GetClassNameW.restype = ctypes.c_int

user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = ctypes.wintypes.BOOL

user32.EnableWindow.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.BOOL]
user32.EnableWindow.restype = ctypes.wintypes.BOOL

user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
user32.IsWindowVisible.restype = ctypes.wintypes.BOOL

user32.ShowCursor.argtypes = [ctypes.wintypes.BOOL]
user32.ShowCursor.restype = ctypes.c_int

user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
user32.GetCursorInfo.restype = ctypes.wintypes.BOOL

user32.ClipCursor.argtypes = [ctypes.POINTER(ctypes.wintypes.RECT)]
user32.ClipCursor.restype = ctypes.wintypes.BOOL

user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = ctypes.wintypes.BOOL

user32.ShutdownBlockReasonCreate.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.wintypes.LPCWSTR,
]
user32.ShutdownBlockReasonCreate.restype = ctypes.wintypes.BOOL

user32.ShutdownBlockReasonDestroy.argtypes = [ctypes.wintypes.HWND]
user32.ShutdownBlockReasonDestroy.restype = ctypes.wintypes.BOOL

user32.SendMessageTimeoutW.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPCWSTR,
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_size_t),
]
user32.SendMessageTimeoutW.restype = LRESULT

user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    HOOKPROC,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = ctypes.wintypes.HANDLE

user32.UnhookWindowsHookEx.argtypes = [ctypes.wintypes.HANDLE]
user32.UnhookWindowsHookEx.restype = ctypes.wintypes.BOOL

user32.CallNextHookEx.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
user32.CallNextHookEx.restype = LRESULT

user32.PeekMessageW.argtypes = [
    ctypes.POINTER(ctypes.wintypes.MSG),
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.c_uint,
]
user32.PeekMessageW.restype = ctypes.wintypes.BOOL

user32.GetMessageW.argtypes = [
    ctypes.POINTER(ctypes.wintypes.MSG),
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.c_uint,
]
user32.GetMessageW.restype = ctypes.c_int

user32.TranslateMessage.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
user32.TranslateMessage.restype = ctypes.wintypes.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.PostThreadMessageW.argtypes = [
    ctypes.wintypes.DWORD,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
user32.PostThreadMessageW.restype = ctypes.wintypes.BOOL

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD

kernel32.GetModuleFileNameW.argtypes = [
    ctypes.wintypes.HMODULE,
    ctypes.wintypes.LPWSTR,
    ctypes.wintypes.DWORD,
]
kernel32.GetModuleFileNameW.restype = ctypes.wintypes.DWORD

kernel32.CreateMutexW.argtypes = [
    ctypes.c_void_p,
    ctypes.wintypes.BOOL,
    ctypes.wintypes.LPCWSTR,
]
kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE

kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
kernel32.CloseHandle.restype = ctypes.wintypes.BOOL

kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
kernel32.SetThreadExecutionState.restype = ctypes.c_uint

kernel32.SetProcessShutdownParameters.argtypes = [
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD,
]
kernel32.SetProcessShutdownParameters.restype = ctypes.wintypes.BOOL

kernel32.LocalFree.argtypes = [ctypes.c_void_p]
kernel32.LocalFree.restype = ctypes.c_void_p

kernel32.GetTempPathW.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.LPWSTR]
kernel32.GetTempPathW.restype = ctypes.wintypes.DWORD

kernel32.GetDiskFreeSpaceExW.argtypes = [
    ctypes.wintypes.LPCWSTR,
    ctypes.POINTER(ctypes.c_ulonglong),
    ctypes.POINTER(ctypes.c_ulonglong),
    ctypes.POINTER(ctypes.c_ulonglong),
]
kernel32.GetDiskFreeSpaceExW.restype = ctypes.wintypes.BOOL

kernel32.CreateToolhelp32Snapshot.argtypes = [
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD,
]
kernel32.CreateToolhelp32Snapshot.restype = ctypes.wintypes.HANDLE

kernel32.Process32FirstW.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(PROCESSENTRY32W),
]
kernel32.Process32FirstW.restype = ctypes.wintypes.BOOL

kernel32.Process32NextW.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(PROCESSENTRY32W),
]
kernel32.Process32NextW.restype = ctypes.wintypes.BOOL

kernel32.OpenProcess.argtypes = [
    ctypes.wintypes.DWORD,
    ctypes.wintypes.BOOL,
    ctypes.wintypes.DWORD,
]
kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE

kernel32.TerminateProcess.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_uint]
kernel32.TerminateProcess.restype = ctypes.wintypes.BOOL

kernel32.GetProcessTimes.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(ctypes.wintypes.FILETIME),
    ctypes.POINTER(ctypes.wintypes.FILETIME),
    ctypes.POINTER(ctypes.wintypes.FILETIME),
    ctypes.POINTER(ctypes.wintypes.FILETIME),
]
kernel32.GetProcessTimes.restype = ctypes.wintypes.BOOL

kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.LPWSTR,
    ctypes.POINTER(ctypes.wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = ctypes.wintypes.BOOL

advapi32.AbortSystemShutdownW.argtypes = [ctypes.wintypes.LPCWSTR]
advapi32.AbortSystemShutdownW.restype = ctypes.wintypes.BOOL

shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = ctypes.wintypes.BOOL

shell32.ShellExecuteW.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.wintypes.LPCWSTR,
    ctypes.wintypes.LPCWSTR,
    ctypes.wintypes.LPCWSTR,
    ctypes.wintypes.LPCWSTR,
    ctypes.c_int,
]
shell32.ShellExecuteW.restype = ctypes.c_size_t

if powrprof is not None:
    powrprof.PowerGetActiveScheme.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(GUID)),
    ]
    powrprof.PowerGetActiveScheme.restype = ctypes.wintypes.DWORD

    powrprof.PowerReadACValueIndex.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(GUID),
        ctypes.POINTER(GUID),
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    powrprof.PowerReadACValueIndex.restype = ctypes.wintypes.DWORD

    powrprof.PowerReadDCValueIndex.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(GUID),
        ctypes.POINTER(GUID),
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    powrprof.PowerReadDCValueIndex.restype = ctypes.wintypes.DWORD

    powrprof.PowerWriteACValueIndex.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(GUID),
        ctypes.POINTER(GUID),
        ctypes.POINTER(GUID),
        ctypes.wintypes.DWORD,
    ]
    powrprof.PowerWriteACValueIndex.restype = ctypes.wintypes.DWORD

    powrprof.PowerWriteDCValueIndex.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(GUID),
        ctypes.POINTER(GUID),
        ctypes.POINTER(GUID),
        ctypes.wintypes.DWORD,
    ]
    powrprof.PowerWriteDCValueIndex.restype = ctypes.wintypes.DWORD

    powrprof.PowerSetActiveScheme.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(GUID),
    ]
    powrprof.PowerSetActiveScheme.restype = ctypes.wintypes.DWORD

HWND_TOPMOST = ctypes.wintypes.HWND(-1)
HWND_BROADCAST = ctypes.wintypes.HWND(0xFFFF)
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOW = 5
GA_ROOT = 2
GWLP_WNDPROC = -4
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_SETTINGCHANGE = 0x001A
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_SYSCOMMAND = 0x0112
SMTO_ABORTIFHUNG = 0x0002
ERROR_ALREADY_EXISTS = 183
CURSOR_SHOWING = 0x00000001

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
LLKHF_EXTENDED = 0x01

VK_BACK = 0x08
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_CAPITAL = 0x14
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

BLOCKED_VK_CODES = {
    0x09,  # TAB
    0x13,  # PAUSE
    0x21, 0x22, 0x23, 0x24,  # PGUP, PGDN, END, HOME
    0x25, 0x26, 0x27, 0x28,  # ARROWS
    0x2C, 0x2D, 0x2E,        # PRINTSCREEN, INSERT, DELETE
    0x5B, 0x5C, 0x5D, 0x5F,  # LWIN, RWIN, APPS, SLEEP
    0x90, 0x91,              # NUMLOCK, SCROLLLOCK
    *range(0x70, 0x88),      # F1-F24
    *range(0xA6, 0xB8),      # Browser/Media/Volume/Launch keys
}

NUMPAD_VK_CHARS = {
    0x60: "0", 0x61: "1", 0x62: "2", 0x63: "3", 0x64: "4",
    0x65: "5", 0x66: "6", 0x67: "7", 0x68: "8", 0x69: "9",
    0x6A: "*", 0x6B: "+", 0x6D: "-", 0x6E: ".", 0x6F: "/",
}

BLOCKED_SYSCOMMANDS = {
    0xF010,  # SC_MOVE
    0xF000,  # SC_SIZE
    0xF020,  # SC_MINIMIZE
    0xF060,  # SC_CLOSE
    0xF100,  # SC_KEYMENU
    0xF130,  # SC_TASKLIST
    0xF140,  # SC_SCREENSAVE
    0xF170,  # SC_MONITORPOWER
}

CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000
LATEST_VERSION_JSON = (
    "https://raw.githubusercontent.com/enderhacker/WinLock/refs/heads/main/version.json"
)
UPDATE_URL = "https://winlock.labdigital.es"
UPDATE_STAGING_PREFIX = "WinLock_Update_"

_ES_WEEKDAYS = (
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
)
_ES_MONTHS = (
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

_single_instance_mutex_handle = None
_active_input_blocker = None

# GUIDs de botones de energía en Windows
GUID_SYSTEM_BUTTON_SUBGROUP = "4f971e89-eebd-4455-a8de-9e59040e7347"
POWER_BUTTON_SETTINGS = (
    "7648efa3-dd9c-4e3e-b566-50f929386280",  # Botón de encendido (pulsación corta)
    "96996bc0-ad50-47ec-923b-6f41874dd9eb",  # Botón de suspensión
    "5ca83367-6e45-459f-a27b-476b1d01c936",  # Acción al cerrar la tapa del portátil
)

# Políticas temporales para blindar Ctrl+Alt+Del y bloqueo de apagado
REG_POLICIES = [
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Policies\System", "DisableTaskMgr", "DWORD", 1),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Policies\System", "DisableLockWorkstation", "DWORD", 1),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Policies\System", "DisableChangePassword", "DWORD", 1),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoClose", "DWORD", 1),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoLogoff", "DWORD", 1),
    ("HKCU", r"Control Panel\Desktop", "AutoEndTasks", "SZ", "0"),
    # Solo se aplican si WinLock se ejecuta con permisos de Administrador
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", "HideFastUserSwitching", "DWORD", 1),
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", "ShutdownWithoutLogon", "DWORD", 0),
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoClose", "DWORD", 1),
]

# Procesos que SIEMPRE se cierran durante el bloqueo (evitan apagado, bypass o cierre forzado)
ALWAYS_KILL_TARGETS = {
    "taskmgr.exe",
    "processhacker.exe",
    "procexp.exe",
    "procexp64.exe",
    "shutdown.exe",
    "logoff.exe",
    "tsdiscon.exe",
    "slidetoshutdown.exe",
    "utilman.exe",
    "sethc.exe",
    "osk.exe",
    "narrator.exe",
    "magnify.exe",
}

# Terminales y herramientas: si ya estaban abiertos antes de bloquear, SE RESPETAN
# (incluyendo sus subprocesos). Solo se cierran instancias NUEVAS.
NEW_INSTANCE_BLOCK_TARGETS = {
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "windowsterminal.exe",
    "wt.exe",
    "regedit.exe",
    "msconfig.exe",
    "perfmon.exe",
    "mmc.exe",
    "control.exe",
    "runonce.exe",
}

TASKBAR_CLASSES = ("Shell_TrayWnd", "Shell_SecondaryTrayWnd")

MENU_OVERLAY_PROCESSES = {
    "startmenuexperiencehost.exe",
    "searchhost.exe",
    "searchapp.exe",
    "shellexperiencehost.exe",
}


# ==============================================================================
# DETECCIÓN DE ENTORNO COMPILADO (NUITKA / PYINSTALLER / PYTHON PURO)
# ==============================================================================

def is_compiled_executable():
    """Detecta si se ejecuta como binario compilado (Nuitka --onefile/--standalone o PyInstaller)."""
    return bool(
        getattr(sys, "frozen", False)
        or ("__compiled__" in globals())
        or ("NUITKA_ONEFILE_PARENT" in os.environ)
    )


def get_process_exe_path(pid):
    """Devuelve la ruta completa del ejecutable de un PID (o None si no accesible)."""
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_proc:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        kernel32.CloseHandle(h_proc)
    return None


def get_executable_path():
    """
    Devuelve la ruta real del ejecutable WinLock.exe (en Nuitka --onefile apunta al
    .exe exterior y NO al binario desempaquetado en %TEMP%). En modo script devuelve __file__.
    """
    if not is_compiled_executable():
        return os.path.abspath(__file__)

    parent_pid_str = os.environ.get("NUITKA_ONEFILE_PARENT", "").strip()
    if parent_pid_str.isdigit():
        parent_exe = get_process_exe_path(int(parent_pid_str))
        if parent_exe and os.path.isfile(parent_exe):
            return os.path.abspath(parent_exe)

    if sys.argv and sys.argv[0]:
        argv0_abs = os.path.abspath(sys.argv[0])
        if argv0_abs.lower().endswith(".exe") and os.path.isfile(argv0_abs):
            return argv0_abs

    buf = ctypes.create_unicode_buffer(1024)
    n = kernel32.GetModuleFileNameW(None, buf, 1024)
    if 0 < n < 1024 and os.path.isfile(buf.value):
        return os.path.abspath(buf.value)

    return os.path.abspath(sys.executable)


# ==============================================================================
# UTILIDADES NATIVAS DE WINDOWS (SIN DEPENDENCIAS EXTERNAS)
# ==============================================================================

def is_admin():
    """Indica si la aplicación corre con privilegios de Administrador."""
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def const_time_equals(a, b):
    """Comparación en tiempo constante para contraseñas y hashes."""
    ba = a.encode("utf-8") if isinstance(a, str) else bytes(a)
    bb = b.encode("utf-8") if isinstance(b, str) else bytes(b)
    diff = len(ba) ^ len(bb)
    for x, y in zip(ba, bb):
        diff |= x ^ y
    return diff == 0


def format_spanish_date(lt=None):
    """Formatea la fecha en español sin depender de la configuración regional del SO."""
    lt = lt or time.localtime()
    return (
        f"{_ES_WEEKDAYS[lt.tm_wday]}, {lt.tm_mday:02d} de "
        f"{_ES_MONTHS[lt.tm_mon]} de {lt.tm_year}"
    )


def get_temp_dir():
    """Obtiene la carpeta temporal de Windows mediante GetTempPathW."""
    buf = ctypes.create_unicode_buffer(512)
    n = kernel32.GetTempPathW(512, buf)
    if 0 < n < 512:
        return os.path.abspath(buf.value)
    return os.path.abspath(os.environ.get("TEMP") or os.environ.get("TMP") or ".")


def get_free_disk_bytes(path):
    """Devuelve el espacio libre en bytes para la unidad de la ruta indicada."""
    free_bytes = ctypes.c_ulonglong(0)
    if kernel32.GetDiskFreeSpaceExW(str(path), ctypes.byref(free_bytes), None, None):
        return free_bytes.value
    return None


def remove_tree(path, ignore_errors=False):
    """Elimina recursivamente un directorio sin requerir shutil."""
    if not os.path.exists(path):
        return
    for root_dir, dirs, files in os.walk(path, topdown=False):
        for name in files:
            fp = os.path.join(root_dir, name)
            try:
                os.chmod(fp, 0o666)
                os.remove(fp)
            except Exception:
                if not ignore_errors:
                    raise
        for name in dirs:
            dp = os.path.join(root_dir, name)
            try:
                os.rmdir(dp)
            except Exception:
                if not ignore_errors:
                    raise
    try:
        os.rmdir(path)
    except FileNotFoundError:
        if not ignore_errors:
            raise
    except Exception as e:
        if not ignore_errors:
            raise
        write_log("No se pudo borrar por completo la carpeta temporal.", level="WARNING", error=e)


def copy_file_bytes(src, dst):
    """Copia un archivo por bloques de 64 KB."""
    with open(src, "rb") as f_in, open(dst, "wb") as f_out:
        while True:
            chunk = f_in.read(65536)
            if not chunk:
                break
            f_out.write(chunk)


def find_in_path(exe_name):
    """Busca un ejecutable en la variable de entorno PATH."""
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = os.path.join(directory.strip('"'), exe_name)
        if os.path.isfile(candidate):
            return candidate
    return None


def list_processes():
    """Devuelve {pid: (nombre_lower, parent_pid)} usando Toolhelp32 nativo."""
    procs = {}
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return procs
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                procs[entry.th32ProcessID] = (
                    entry.szExeFile.lower(),
                    entry.th32ParentProcessID,
                )
                if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    return procs


def get_process_creation_time(pid):
    """Devuelve la marca FILETIME de creación de un PID (o None si no accesible)."""
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_proc:
        return None
    try:
        ct = ctypes.wintypes.FILETIME()
        et = ctypes.wintypes.FILETIME()
        kt = ctypes.wintypes.FILETIME()
        ut = ctypes.wintypes.FILETIME()
        if kernel32.GetProcessTimes(
            h_proc,
            ctypes.byref(ct),
            ctypes.byref(et),
            ctypes.byref(kt),
            ctypes.byref(ut),
        ):
            return (ct.dwHighDateTime << 32) | ct.dwLowDateTime
    finally:
        kernel32.CloseHandle(h_proc)
    return None


def terminate_process(pid):
    """Termina un proceso por PID usando OpenProcess + TerminateProcess."""
    h_proc = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h_proc:
        return False
    try:
        return bool(kernel32.TerminateProcess(h_proc, 1))
    finally:
        kernel32.CloseHandle(h_proc)


def parse_version(version_str):
    """Convierte versiones como 'v0.9', 'v0.10.0' en tuplas comparables normalizadas."""
    try:
        cleaned = str(version_str).strip().lstrip("vV")
        parts = []
        for seg in cleaned.split("."):
            seg = seg.strip()
            digits = ""
            for ch in seg:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if digits:
                parts.append(int(digits))
            else:
                break
        while len(parts) > 1 and parts[-1] == 0:
            parts.pop()
        return tuple(parts) if parts else (0,)
    except Exception:
        return (0,)


def parse_human_size(size_value):
    """Convierte tamaños como '10.93 MB', '512 KB' o enteros a bytes aproximados."""
    if isinstance(size_value, (int, float)) and size_value > 0:
        return int(size_value)
    if not isinstance(size_value, str):
        return 0
    s = size_value.strip()
    idx = 0
    while idx < len(s) and (s[idx].isdigit() or s[idx] in ".,"):
        idx += 1
    num_str = s[:idx]
    unit = s[idx:].strip().upper()
    if not num_str:
        return 0
    try:
        num = float(num_str.replace(",", "."))
        factors = {
            "": 1,
            "B": 1,
            "K": 1024,
            "KB": 1024,
            "M": 1024**2,
            "MB": 1024**2,
            "G": 1024**3,
            "GB": 1024**3,
            "T": 1024**4,
            "TB": 1024**4,
        }
        if unit not in factors:
            return 0
        return int(num * factors[unit])
    except Exception:
        return 0


def format_bytes(num_bytes):
    """Formatea una cantidad de bytes a cadena legible."""
    val = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024.0 or unit == "GB":
            return f"{val:.2f} {unit}" if unit in ("MB", "GB") else f"{val:.0f} {unit}"
        val /= 1024.0
    return f"{val:.2f} GB"


def format_duration(total_seconds):
    """Formatea una duración en segundos como '1d 2h 3m 4s'."""
    delta = max(0, int(total_seconds))
    d, r = divmod(delta, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    return (
        (f"{d}d " if d else "")
        + (f"{h}h " if h else "")
        + (f"{m}m " if m else "")
        + f"{s}s"
    )


def resource_path(relative_path):
    """Obtiene la ruta de los recursos en PyInstaller, Nuitka (--onefile/--standalone) o script."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(meipass)
    try:
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    try:
        candidates.append(os.path.dirname(get_executable_path()))
    except Exception:
        pass
    candidates.append(os.path.abspath("."))

    for base_path in candidates:
        full_path = os.path.join(base_path, relative_path)
        if os.path.exists(full_path):
            return full_path
    return os.path.join(candidates[0], relative_path)


def get_dpi_scale(win):
    """Obtiene el factor de escala DPI de la ventana Tkinter (1.0 = 96 DPI)."""
    try:
        scale = float(win.winfo_fpixels("1i")) / 96.0
        return max(1.0, scale)
    except Exception:
        return 1.0


def _get_toplevel_hwnd(win):
    """Obtiene el HWND real de nivel superior sin confundir padre con propietario."""
    try:
        frame = win.wm_frame()
        if frame and frame != "0x0":
            hwnd = int(frame, 16)
            if hwnd:
                return hwnd
    except Exception:
        pass
    try:
        hwnd = win.winfo_id()
        root_hwnd = user32.GetAncestor(hwnd, GA_ROOT)
        return root_hwnd or hwnd
    except Exception:
        return 0


def acquire_single_instance_mutex(retries=0, retry_delay=0.15):
    """Evita múltiples instancias simultáneas de WinLock con soporte de reintento."""
    global _single_instance_mutex_handle
    for attempt in range(retries + 1):
        handle = kernel32.CreateMutexW(None, False, "Local\\WinLock_SingleInstance_Mutex")
        if not handle:
            write_log(
                f"No se pudo crear el mutex de instancia única (Win32={ctypes.get_last_error()}).",
                level="WARNING",
            )
            return None, True
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            if attempt < retries:
                time.sleep(retry_delay)
                continue
            return None, False
        _single_instance_mutex_handle = handle
        write_log(f"Mutex de instancia única adquirido (intento {attempt + 1}).")
        return handle, True
    return None, False


def release_single_instance_mutex():
    """Libera explícitamente el mutex de instancia única."""
    global _single_instance_mutex_handle
    if _single_instance_mutex_handle:
        try:
            if kernel32.CloseHandle(_single_instance_mutex_handle):
                write_log("Mutex de instancia única liberado.")
            else:
                write_log(
                    f"No se pudo liberar el mutex (Win32={ctypes.get_last_error()}).",
                    level="WARNING",
                )
        except Exception as e:
            write_log("Error liberando el mutex de instancia única.", level="WARNING", error=e)
        _single_instance_mutex_handle = None


def relaunch_as_admin():
    """Relanza WinLock con elevación UAC mediante ShellExecuteW ('runas')."""
    compiled = is_compiled_executable()
    forwarded_args = [a for a in sys.argv[1:] if a != "--elevated"]
    forwarded_args.append("--elevated")

    if compiled:
        exe_path = get_executable_path()
        params = subprocess.list2cmdline(forwarded_args)
        workdir = os.path.dirname(exe_path) or os.getcwd()
    else:
        exe_path = os.path.abspath(sys.executable)
        script_path = os.path.abspath(__file__)
        params = subprocess.list2cmdline([script_path] + forwarded_args)
        workdir = os.path.dirname(script_path) or os.getcwd()

    release_single_instance_mutex()

    res = shell32.ShellExecuteW(
        None,
        "runas",
        exe_path,
        params,
        workdir,
        SW_SHOWNORMAL,
    )
    if int(res or 0) > 32:
        write_log("Instancia elevada lanzada correctamente. Cerrando instancia actual.")
        return True

    write_log(
        f"Auto-elevación cancelada o fallida (ShellExecuteW={res}). Continuando sin Administrador.",
        level="WARNING",
    )
    acquire_single_instance_mutex(retries=3, retry_delay=0.1)
    return False


def prompt_admin_elevation():
    """
    Si no se ejecuta como Administrador, muestra un modal recomendándolo y
    ofrece auto-elevar con Sí / No. Devuelve True si este proceso debe salir.
    """
    if is_admin():
        return False

    write_log("Mostrando el aviso de permisos de Administrador.")
    modal_root = LoggedTk()
    modal_root.withdraw()
    try:
        modal_root.iconbitmap(resource_path("winlock.ico"))
    except Exception as e:
        write_log("No se pudo cargar el icono del aviso de permisos.", level="WARNING", error=e)
    modal_root.attributes("-topmost", True)

    should_elevate = messagebox.askyesno(
        f"Permisos de Administrador - WinLock {LOCAL_VERSION}",
        "WinLock no se está ejecutando como Administrador.\n\n"
        "Se recomienda ejecutarlo como Administrador para activar la máxima "
        "protección (bloquear cambio de usuario, apagado y todas las políticas del sistema).\n\n"
        "¿Desea reiniciar WinLock automáticamente como Administrador?",
        icon="warning",
        parent=modal_root,
    )
    try:
        modal_root.destroy()
    except Exception as e:
        write_log("Error cerrando el aviso de permisos.", level="WARNING", error=e)

    if not should_elevate:
        write_log("El usuario decidió continuar sin permisos de Administrador.")
        return False

    write_log("Solicitando auto-elevación como Administrador (UAC)...")
    return relaunch_as_admin()


def abort_system_shutdown():
    """Intenta cancelar cualquier apagado o reinicio pendiente."""
    try:
        advapi32.AbortSystemShutdownW(None)
    except Exception:
        pass
    try:
        subprocess.Popen(
            ["shutdown", "/a"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def broadcast_policy_change():
    """Notifica a Windows que las políticas del sistema han cambiado."""
    try:
        res = ctypes.c_size_t(0)
        if not user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Policy",
            SMTO_ABORTIFHUNG,
            300,
            ctypes.byref(res),
        ):
            write_log(
                f"No se confirmó la notificación de cambio de políticas (Win32={ctypes.get_last_error()}).",
                level="WARNING",
            )
    except Exception as e:
        write_log("Error notificando el cambio de políticas.", level="WARNING", error=e)


def restore_thread_execution_state():
    """Quita la solicitud de mantener Windows activo durante el bloqueo."""
    try:
        if not kernel32.SetThreadExecutionState(0x80000000):
            write_log("Windows no pudo restablecer el estado de ejecución.", level="WARNING")
    except Exception as e:
        write_log("Error restableciendo el estado de ejecución.", level="WARNING", error=e)


def start_explorer_if_not_running():
    """Verifica si explorer.exe se está ejecutando y lo inicia si no es así."""
    try:
        explorer_running = any(
            name == "explorer.exe" for name, _ in list_processes().values()
        )
        if not explorer_running:
            write_log("explorer.exe no estaba ejecutándose. Iniciando explorer.exe.")
            subprocess.Popen("explorer.exe")
        else:
            write_log("explorer.exe ya está en ejecución.")
    except Exception as e:
        write_log("Error verificando o iniciando explorer.exe.", level="WARNING", error=e)


class SystemGuard:
    """
    Gestiona políticas de Windows y botones de energía durante el bloqueo,
    con respaldo persistente y recuperación automática tras cortes de luz.
    """

    RUNONCE_KEY = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
    RUNONCE_VALUE = "WinLockRecovery"

    HIVES = {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
    }

    REG_TYPES = {
        "DWORD": winreg.REG_DWORD,
        "SZ": winreg.REG_SZ,
    }

    _engaged = False
    _lock = threading.Lock()

    @classmethod
    def _build_recovery_command(cls):
        if is_compiled_executable():
            return f'"{get_executable_path()}" --restore'
        return f'"{os.path.abspath(sys.executable)}" "{os.path.abspath(__file__)}" --restore'

    @classmethod
    def _set_runonce_recovery(cls, enable):
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, cls.RUNONCE_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                if enable:
                    winreg.SetValueEx(
                        key,
                        cls.RUNONCE_VALUE,
                        0,
                        winreg.REG_SZ,
                        cls._build_recovery_command(),
                    )
                else:
                    try:
                        winreg.DeleteValue(key, cls.RUNONCE_VALUE)
                    except FileNotFoundError:
                        pass
        except Exception as e:
            action = "registrar" if enable else "retirar"
            write_log(f"No se pudo {action} la recuperación automática.", level="WARNING", error=e)

    @classmethod
    def _snapshot_and_apply_power_buttons(cls):
        """Desactiva pulsación corta de botón de encendido, suspensión y cierre de tapa."""
        if powrprof is None:
            return None

        scheme_ptr = ctypes.POINTER(GUID)()
        if powrprof.PowerGetActiveScheme(None, ctypes.byref(scheme_ptr)) != 0 or not scheme_ptr:
            return None

        try:
            scheme_guid = GUID.from_buffer_copy(scheme_ptr.contents)
            subgroup = GUID.from_string(GUID_SYSTEM_BUTTON_SUBGROUP)
            backup = {"scheme_guid": scheme_guid.to_string(), "settings": []}

            modified = False
            for setting_str in POWER_BUTTON_SETTINGS:
                setting_guid = GUID.from_string(setting_str)
                ac_val = ctypes.wintypes.DWORD(0)
                dc_val = ctypes.wintypes.DWORD(0)
                r_ac = powrprof.PowerReadACValueIndex(
                    None,
                    ctypes.byref(scheme_guid),
                    ctypes.byref(subgroup),
                    ctypes.byref(setting_guid),
                    ctypes.byref(ac_val),
                )
                r_dc = powrprof.PowerReadDCValueIndex(
                    None,
                    ctypes.byref(scheme_guid),
                    ctypes.byref(subgroup),
                    ctypes.byref(setting_guid),
                    ctypes.byref(dc_val),
                )
                if r_ac == 0 or r_dc == 0:
                    entry = {
                        "guid": setting_str,
                        "ac": ac_val.value if r_ac == 0 else None,
                        "dc": dc_val.value if r_dc == 0 else None,
                    }
                    w_ac = (
                        powrprof.PowerWriteACValueIndex(
                            None,
                            ctypes.byref(scheme_guid),
                            ctypes.byref(subgroup),
                            ctypes.byref(setting_guid),
                            0,
                        )
                        if r_ac == 0
                        else 1
                    )
                    w_dc = (
                        powrprof.PowerWriteDCValueIndex(
                            None,
                            ctypes.byref(scheme_guid),
                            ctypes.byref(subgroup),
                            ctypes.byref(setting_guid),
                            0,
                        )
                        if r_dc == 0
                        else 1
                    )
                    if w_ac == 0 or w_dc == 0:
                        backup["settings"].append(entry)
                        modified = True

            if modified:
                powrprof.PowerSetActiveScheme(None, ctypes.byref(scheme_guid))
                write_log("Botones de energía y cierre de tapa neutralizados temporalmente.")
                return backup
            return None
        except Exception as e:
            write_log("Error ajustando los botones de energía.", level="WARNING", error=e)
            return None
        finally:
            try:
                kernel32.LocalFree(ctypes.cast(scheme_ptr, ctypes.c_void_p))
            except Exception:
                pass

    @classmethod
    def _restore_power_buttons(cls, power_backup):
        if not power_backup:
            return
        if powrprof is None:
            write_log("No se pueden restaurar los botones de energía: falta powrprof.", level="WARNING")
            return
        try:
            scheme_guid = GUID.from_string(power_backup["scheme_guid"])
            subgroup = GUID.from_string(GUID_SYSTEM_BUTTON_SUBGROUP)
            failed = 0
            for item in power_backup.get("settings", []):
                try:
                    setting_guid = GUID.from_string(item["guid"])
                    ac_result = dc_result = 0
                    if item.get("ac") is not None:
                        ac_result = powrprof.PowerWriteACValueIndex(
                            None,
                            ctypes.byref(scheme_guid),
                            ctypes.byref(subgroup),
                            ctypes.byref(setting_guid),
                            int(item["ac"]),
                        )
                    if item.get("dc") is not None:
                        dc_result = powrprof.PowerWriteDCValueIndex(
                            None,
                            ctypes.byref(scheme_guid),
                            ctypes.byref(subgroup),
                            ctypes.byref(setting_guid),
                            int(item["dc"]),
                        )
                    if ac_result or dc_result:
                        failed += 1
                        write_log(
                            f"No se pudo restaurar todo el ajuste de energía {item['guid']} "
                            f"(AC={ac_result}, DC={dc_result}).",
                            level="WARNING",
                        )
                except Exception as e:
                    failed += 1
                    write_log("Error restaurando un ajuste de energía.", level="WARNING", error=e)
            scheme_result = powrprof.PowerSetActiveScheme(None, ctypes.byref(scheme_guid))
            if failed or scheme_result:
                write_log(
                    f"Restauración de energía incompleta (ajustes con errores: {failed}, "
                    f"PowerSetActiveScheme={scheme_result}).",
                    level="WARNING",
                )
            else:
                write_log("Botones de energía restaurados a su configuración original.")
        except Exception as e:
            write_log("Error restaurando botones de energía.", level="ERROR", error=e)

    @classmethod
    def _fallback_cleanup_policies(cls):
        """
        Limpieza segura sin archivo de respaldo: elimina únicamente las políticas
        restrictivas de WinLock si coinciden con los valores de bloqueo.
        """
        restored = 0
        skipped_admin = 0
        for hive_name, subkey, value_name, _, lock_val in REG_POLICIES:
            if value_name == "AutoEndTasks":
                continue
            hive = cls.HIVES.get(hive_name)
            if not hive:
                continue
            try:
                with winreg.OpenKeyEx(
                    hive, subkey, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE
                ) as key:
                    try:
                        cur_val, _ = winreg.QueryValueEx(key, value_name)
                    except FileNotFoundError:
                        continue

                    if cur_val == lock_val:
                        if value_name == "ShutdownWithoutLogon":
                            winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, 1)
                        else:
                            winreg.DeleteValue(key, value_name)
                        restored += 1
            except FileNotFoundError:
                continue
            except PermissionError:
                skipped_admin += 1
                write_log(
                    f"Sin permisos de Administrador para limpiar {hive_name}\\{subkey}\\{value_name}.",
                    level="WARNING",
                )
            except Exception as e:
                write_log(f"Error en limpieza de respaldo ({value_name}).", level="WARNING", error=e)
        write_log(
            f"Limpieza fallback completada (políticas corregidas: {restored}, omitidas por falta de admin: {skipped_admin})."
        )

    @classmethod
    def engage(cls):
        """Aplica blindaje de registro y botones de energía guardando copia exacta."""
        with cls._lock:
            if cls._engaged:
                return

            reg_backups = []
            for hive_name, subkey, value_name, rtype, lock_val in REG_POLICIES:
                hive = cls.HIVES[hive_name]
                try:
                    with winreg.CreateKeyEx(
                        hive, subkey, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE
                    ) as key:
                        try:
                            old_val, old_type = winreg.QueryValueEx(key, value_name)
                            reg_backups.append(
                                {
                                    "hive": hive_name,
                                    "subkey": subkey,
                                    "name": value_name,
                                    "existed": True,
                                    "old_val": old_val,
                                    "old_type": old_type,
                                }
                            )
                        except FileNotFoundError:
                            reg_backups.append(
                                {
                                    "hive": hive_name,
                                    "subkey": subkey,
                                    "name": value_name,
                                    "existed": False,
                                }
                            )
                except PermissionError:
                    continue
                except Exception as e:
                    write_log(
                        f"Error leyendo la política {hive_name}\\{subkey}\\{value_name}.",
                        level="WARNING",
                        error=e,
                    )

            power_backup = cls._snapshot_and_apply_power_buttons()

            state_payload = {
                "registry": reg_backups,
                "power": power_backup,
            }

            try:
                tmp_path = RESTORE_STATE_PATH + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(state_payload, f, indent=2)
                os.replace(tmp_path, RESTORE_STATE_PATH)
                write_log(f"Estado de recuperación guardado ({len(reg_backups)} entradas de registro).")
            except Exception as e:
                write_log("Error guardando estado de recuperación.", level="ERROR", error=e)

            cls._set_runonce_recovery(True)

            applied = 0
            for hive_name, subkey, value_name, rtype, lock_val in REG_POLICIES:
                hive = cls.HIVES[hive_name]
                try:
                    with winreg.CreateKeyEx(
                        hive, subkey, 0, winreg.KEY_SET_VALUE
                    ) as key:
                        winreg.SetValueEx(
                            key, value_name, 0, cls.REG_TYPES[rtype], lock_val
                        )
                        applied += 1
                except PermissionError:
                    continue
                except Exception as e:
                    write_log(f"Error aplicando la política {value_name}.", level="ERROR", error=e)

            cls._engaged = True
            broadcast_policy_change()
            write_log(f"SystemGuard activado ({applied} políticas aplicadas).")

    @classmethod
    def restore(cls, force_fallback=False):
        """Restaura exactamente el registro y los botones de energía previos."""
        with cls._lock:
            state_payload = None
            state_corrupt = False

            if os.path.exists(RESTORE_STATE_PATH):
                try:
                    with open(RESTORE_STATE_PATH, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict):
                        state_payload = loaded
                    else:
                        state_corrupt = True
                        write_log("Formato inesperado en el archivo de recuperación.", level="WARNING")
                except Exception as e:
                    state_corrupt = True
                    write_log("Archivo de recuperación ilegible o dañado.", level="ERROR", error=e)

            if state_payload:
                write_log("Restaurando Windows desde el estado de recuperación guardado.")
                restored = 0
                skipped_admin = 0
                failed = 0
                for entry in state_payload.get("registry", []):
                    hive = cls.HIVES.get(entry.get("hive"))
                    if not hive:
                        failed += 1
                        write_log("Entrada de recuperación con un registro desconocido.", level="WARNING")
                        continue
                    try:
                        with winreg.CreateKeyEx(
                            hive, entry["subkey"], 0, winreg.KEY_SET_VALUE
                        ) as key:
                            if entry.get("existed"):
                                winreg.SetValueEx(
                                    key,
                                    entry["name"],
                                    0,
                                    entry["old_type"],
                                    entry["old_val"],
                                )
                            else:
                                try:
                                    winreg.DeleteValue(key, entry["name"])
                                except FileNotFoundError:
                                    pass
                        restored += 1
                    except PermissionError:
                        skipped_admin += 1
                        write_log(
                            f"Sin permisos de Administrador para restaurar {entry.get('hive')}\\{entry.get('name')}.",
                            level="WARNING",
                        )
                        continue
                    except Exception as e:
                        failed += 1
                        write_log(
                            f"Error restaurando política {entry.get('name')}.", level="ERROR", error=e
                        )

                cls._restore_power_buttons(state_payload.get("power"))

                try:
                    os.remove(RESTORE_STATE_PATH)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    write_log("No se pudo borrar el archivo de recuperación.", level="WARNING", error=e)

                cls._set_runonce_recovery(False)
                broadcast_policy_change()
                write_log(
                    f"Restauración del registro: {restored} entradas restauradas, "
                    f"{skipped_admin} sin permisos, {failed} con errores.",
                    level="WARNING" if skipped_admin or failed else "INFO",
                )
            elif force_fallback or state_corrupt:
                write_log(f"Iniciando limpieza de respaldo (archivo dañado={state_corrupt}).")
                if state_corrupt:
                    try:
                        os.remove(RESTORE_STATE_PATH)
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        write_log("No se pudo borrar el archivo de recuperación dañado.", level="WARNING", error=e)
                cls._fallback_cleanup_policies()
                cls._set_runonce_recovery(False)
                broadcast_policy_change()

            cls._engaged = False


def find_taskbar_windows():
    """Encuentra todas las ventanas de barra de tareas (principal y secundarias)."""
    hwnds = []

    def _enum_cb(hwnd, lParam):
        buf = ctypes.create_unicode_buffer(64)
        if user32.GetClassNameW(hwnd, buf, 64) and buf.value in TASKBAR_CLASSES:
            hwnds.append(hwnd)
        return True

    cb = WNDENUMPROC(_enum_cb)
    user32.EnumWindows(cb, 0)
    return hwnds


def hide_taskbars():
    """Oculta y deshabilita la barra de tareas sin matar explorer.exe."""
    for hwnd in find_taskbar_windows():
        try:
            user32.EnableWindow(hwnd, False)
            if user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, SW_HIDE)
        except Exception:
            pass


def restore_taskbars():
    """Restaura y rehabilita la barra de tareas en todos los monitores."""
    taskbars = find_taskbar_windows()
    write_log(f"Restaurando barras de tareas ({len(taskbars)} encontradas).")
    for hwnd in taskbars:
        try:
            user32.EnableWindow(hwnd, True)
            user32.ShowWindow(hwnd, SW_SHOW)
        except Exception as e:
            write_log("Error restaurando una barra de tareas.", level="WARNING", error=e)


def get_monitors_info():
    """Obtiene las coordenadas geométricas reales de todos los monitores conectados."""
    monitors = []

    def _monitor_enum_callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        rect = lprcMonitor.contents
        monitors.append(
            {
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
                "is_primary": (rect.left == 0 and rect.top == 0),
            }
        )
        return True

    callback = MONITORENUMPROC(_monitor_enum_callback)
    user32.EnumDisplayMonitors(None, None, callback, 0)

    if not monitors:
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        monitors.append(
            {
                "left": 0,
                "top": 0,
                "right": w,
                "bottom": h,
                "width": w,
                "height": h,
                "is_primary": True,
            }
        )
    return monitors


def translate_key_to_char(vk, scan_code, shift_on, altgr_on, caps_on):
    """Traduce (vk, scan_code) al carácter Unicode exacto según el teclado activo de Windows."""
    try:
        hkl = user32.GetKeyboardLayout(0)
        key_state = (ctypes.c_ubyte * 256)()
        if shift_on:
            key_state[VK_SHIFT] = 0x80
        if altgr_on:
            key_state[VK_CONTROL] = 0x80
            key_state[VK_MENU] = 0x80
        if caps_on:
            key_state[VK_CAPITAL] = 0x01

        buf = ctypes.create_unicode_buffer(8)
        res = user32.ToUnicodeEx(vk, scan_code, key_state, buf, 8, 0, hkl)
        if res > 0:
            text = buf.value[:res]
            if text and text.isprintable():
                return text
        elif res < 0:
            return ""
    except Exception:
        pass
    return ""


def force_window_topmost(win):
    """Fuerza que una ventana de Tkinter permanezca sobre cualquier otra."""
    try:
        if not win.winfo_exists():
            return
        win.attributes("-topmost", True)
        win.lift()
        hwnd = _get_toplevel_hwnd(win)
        if hwnd:
            user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
            )
    except Exception:
        pass


def place_window_on_monitor(win, mon):
    """Coloca una ventana exactamente sobre las coordenadas físicas de un monitor."""
    try:
        win.geometry(
            f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}"
        )
        win.update_idletasks()
        hwnd = _get_toplevel_hwnd(win)
        if hwnd:
            user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                mon["left"],
                mon["top"],
                mon["width"],
                mon["height"],
                SWP_SHOWWINDOW,
            )
    except Exception:
        pass


class InputBlocker:
    """
    Bloquea globalmente teclado (WH_KEYBOARD_LL) y ratón (WH_MOUSE_LL) mediante
    hooks nativos de Windows en un único hilo dedicado con bucle de mensajes.
    """

    WH_KEYBOARD_LL = 13
    WH_MOUSE_LL = 14
    WM_QUIT = 0x0012

    def __init__(self, on_key_callback=None):
        self._on_key_callback = on_key_callback
        self._thread = None
        self._thread_id = None
        self._kbd_hook_id = None
        self._mouse_hook_id = None
        self._kbd_proc = None
        self._mouse_proc = None
        self._running = False
        self._ready_event = threading.Event()

    @property
    def is_active(self):
        return bool(
            self._running
            and self._kbd_hook_id
            and self._mouse_hook_id
            and self._thread
            and self._thread.is_alive()
        )

    def start(self):
        global _active_input_blocker
        if self.is_active:
            return
        self.stop()
        self._running = True
        self._ready_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready_event.wait(timeout=1.5)
        _active_input_blocker = self

    def _run(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        msg = ctypes.wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        def _low_level_kbd_proc(nCode, wParam, lParam):
            if nCode >= 0 and self._running:
                try:
                    kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    if self._on_key_callback:
                        self._on_key_callback(
                            kb.vkCode, kb.scanCode, kb.flags, is_down
                        )
                except Exception:
                    pass
                return 1
            return user32.CallNextHookEx(self._kbd_hook_id, nCode, wParam, lParam)

        def _low_level_mouse_proc(nCode, wParam, lParam):
            if nCode >= 0 and self._running:
                return 1
            return user32.CallNextHookEx(self._mouse_hook_id, nCode, wParam, lParam)

        self._kbd_proc = HOOKPROC(_low_level_kbd_proc)
        self._mouse_proc = HOOKPROC(_low_level_mouse_proc)

        self._kbd_hook_id = user32.SetWindowsHookExW(
            self.WH_KEYBOARD_LL, self._kbd_proc, None, 0
        )
        if not self._kbd_hook_id:
            write_log(
                f"No se pudo instalar WH_KEYBOARD_LL (error={ctypes.get_last_error()}).",
                level="ERROR",
            )

        self._mouse_hook_id = user32.SetWindowsHookExW(
            self.WH_MOUSE_LL, self._mouse_proc, None, 0
        )
        if not self._mouse_hook_id:
            write_log(
                f"No se pudo instalar WH_MOUSE_LL (error={ctypes.get_last_error()}).",
                level="ERROR",
            )

        self._ready_event.set()

        if not self._kbd_hook_id and not self._mouse_hook_id:
            self._running = False
            return

        while self._running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._kbd_hook_id:
            user32.UnhookWindowsHookEx(self._kbd_hook_id)
            self._kbd_hook_id = None
        if self._mouse_hook_id:
            user32.UnhookWindowsHookEx(self._mouse_hook_id)
            self._mouse_hook_id = None

    def stop(self):
        global _active_input_blocker
        self._running = False
        if self._thread_id:
            try:
                user32.PostThreadMessageW(self._thread_id, self.WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._thread_id = None
        if _active_input_blocker is self:
            _active_input_blocker = None


class WinLock:
    def __init__(self, root_window):
        write_log("Inicializando la aplicación WinLock.")
        self.root = root_window
        self.unlock_password = ""
        self.lock_message_optional = None
        self.lock_start_time = 0
        self.lock_start_dt = ""
        self.failed_attempts = 0
        self.last_failed_time = None
        self.cooldown_until = 0.0

        self.security_events = []
        self._events_lock = threading.Lock()
        self._event_dedupe = {}

        self._watchdog_thread = None
        self._watchdog_running = False
        self._allowed_preexisting_procs = set()
        self._input_blocker = InputBlocker(self._on_raw_key_event)
        self._is_locked = False
        self._is_quitting = False

        self._key_events = []
        self._key_events_lock = threading.Lock()
        self._held_shifts = set()
        self._held_ctrls = set()
        self._left_alt_down = False
        self._altgr_down = False
        self._caps_lock_on = bool(user32.GetKeyState(VK_CAPITAL) & 1)
        self._caps_key_held = False

        # Subclasificación de ventanas anti-apagado y anti-cierre
        self._shielded_windows = []

        self.setup_frame = None
        self.setup_caps_label = None
        self.secondary_screens = []
        self.primary_lock_window = None
        self._monitor_signature = None

        self.dpi_scale = get_dpi_scale(self.root)

        self.root.title(f"WinLock {LOCAL_VERSION}")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._quit_app)

        try:
            self.root.iconbitmap(resource_path("winlock.ico"))
        except Exception as e:
            write_log("No se pudo cargar el icono principal.", level="WARNING", error=e)

        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        self.style.configure("TLabel", font=("Segoe UI", 10))
        self.style.configure("TEntry", font=("Segoe UI", 10))
        self.style.configure(
            "Lock.TButton", font=("Segoe UI", 11, "bold"), foreground="white"
        )
        self.style.map(
            "Lock.TButton", background=[("active", "#c00000"), ("!disabled", "#e60000")]
        )

        self.create_setup_window()

    def _px(self, value):
        return max(1, int(round(value * self.dpi_scale)))

    def _enqueue_key(self, kind, payload=None):
        with self._key_events_lock:
            self._key_events.append((kind, payload))

    def _record_event(self, message, level="info", dedupe_key=None, dedupe_seconds=3.0):
        """Registra un evento cronológico de la sesión de bloqueo (thread-safe)."""
        now_mono = time.monotonic()
        ts = time.strftime("%H:%M:%S")
        with self._events_lock:
            if dedupe_key is not None:
                last_seen = self._event_dedupe.get(dedupe_key, 0.0)
                if now_mono - last_seen < dedupe_seconds:
                    return
                self._event_dedupe[dedupe_key] = now_mono
            self.security_events.append((ts, level, message))

    def center_window(self, win, min_width=0, min_height=0):
        """Ajusta al tamaño requerido (compatible con DPI alto) y centra la ventana."""
        win.update_idletasks()
        width = max(min_width, win.winfo_reqwidth(), win.winfo_width())
        height = max(min_height, win.winfo_reqheight(), win.winfo_height())
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        width = min(width, max(200, screen_w - 40))
        height = min(height, max(200, screen_h - 60))
        x = max(0, (screen_w // 2) - (width // 2))
        y = max(0, (screen_h // 2) - (height // 2))
        win.geometry(f"{width}x{height}+{x}+{y}")

    def _update_setup_caps_indicator(self, event=None):
        """Actualiza el aviso de Bloq Mayús en la ventana inicial sin mover elementos."""
        if (
            not self.setup_frame
            or not self.setup_frame.winfo_exists()
            or not self.setup_caps_label
            or not self.setup_caps_label.winfo_exists()
        ):
            return
        caps_on = bool(user32.GetKeyState(VK_CAPITAL) & 1)
        self.setup_caps_label.config(text="Bloq Mayús activado" if caps_on else "")

    def _poll_setup_caps(self):
        """Mantiene sincronizado el indicador de Bloq Mayús mientras existe la ventana inicial."""
        if not self.setup_frame or not self.setup_frame.winfo_exists():
            return
        self._update_setup_caps_indicator()
        self.setup_frame.after(200, self._poll_setup_caps)

    def create_setup_window(self):
        """Crea la ventana inicial con contraseña siempre visible y sin repetición."""
        write_log("Creando la ventana de configuración de contraseña.")
        if self.setup_frame:
            self.setup_frame.destroy()

        pad_x = self._px(20)
        pad_y = self._px(18)
        self.setup_frame = ttk.Frame(
            self.root, padding=(pad_x, pad_y, pad_x, pad_y)
        )
        self.setup_frame.pack(expand=True, fill=tk.BOTH)

        font_style = ("Segoe UI", 10)

        pwd_header = ttk.Frame(self.setup_frame)
        pwd_header.pack(fill=tk.X)
        ttk.Label(pwd_header, text="Contraseña:", font=font_style).pack(side=tk.LEFT)
        self.setup_caps_label = ttk.Label(
            pwd_header,
            text="",
            font=("Segoe UI", 9, "bold"),
            foreground="#d97706",
            width=20,
            anchor="e",
        )
        self.setup_caps_label.pack(side=tk.RIGHT)

        self.password_entry = ttk.Entry(self.setup_frame, font=font_style)
        self.password_entry.pack(
            fill=tk.X, pady=(self._px(2), self._px(10)), ipady=self._px(3)
        )

        ttk.Label(self.setup_frame, text="Mensaje (opcional):", font=font_style).pack(
            anchor="w"
        )
        self.message_text = tk.Text(
            self.setup_frame, height=6, width=35, wrap="word", font=font_style
        )
        self.message_text.pack(
            fill=tk.BOTH, expand=True, pady=(self._px(2), self._px(10))
        )

        admin_status = (
            "Protección máxima activa (Administrador)"
            if is_admin()
            else "Consejo: ejecute como Administrador para bloquear también Cambio de usuario"
        )
        ttk.Label(
            self.setup_frame,
            text=admin_status,
            font=("Segoe UI", 8),
            foreground="#2e7d32" if is_admin() else "#666666",
            wraplength=self._px(365),
        ).pack(anchor="w", pady=(0, self._px(10)))

        self.lock_button = ttk.Button(
            self.setup_frame,
            text="Bloquear equipo",
            command=self.validate_and_confirm,
            style="Lock.TButton",
        )
        self.lock_button.pack(pady=0, ipady=self._px(4), fill=tk.X)

        self.password_entry.bind("<Return>", lambda e: self.validate_and_confirm())
        self.root.bind(
            "<KeyPress-Caps_Lock>",
            lambda e: self.root.after(10, self._update_setup_caps_indicator),
        )
        self.root.bind(
            "<KeyRelease-Caps_Lock>",
            lambda e: self.root.after(10, self._update_setup_caps_indicator),
        )
        self.root.bind("<FocusIn>", self._update_setup_caps_indicator)

        self._update_setup_caps_indicator()
        self._poll_setup_caps()

        self.center_window(
            self.root, min_width=self._px(410), min_height=self._px(375)
        )
        self.root.lift()
        self.root.focus_force()
        self.password_entry.focus_set()
        write_log(f"Ventana de configuración lista (escala DPI={self.dpi_scale:.2f}).")

    def validate_and_confirm(self):
        """Valida la entrada y pide confirmación antes de bloquear."""
        pwd = self.password_entry.get()

        if len(pwd) < 1:
            write_log("Configuración rechazada: falta la contraseña.", level="WARNING")
            messagebox.showwarning(
                "Atención", "La contraseña no puede estar vacía.", parent=self.root
            )
            self.password_entry.focus_set()
            return

        msg = self.message_text.get("1.0", tk.END).strip()
        if len(msg) > 1000:
            write_log("Configuración rechazada: el mensaje supera el límite.", level="WARNING")
            messagebox.showwarning(
                "Atención",
                "El mensaje no puede superar los 1000 caracteres.",
                parent=self.root,
            )
            return

        if not messagebox.askokcancel(
            "Confirmar Bloqueo",
            "¿Está seguro de que desea bloquear este ordenador?",
            parent=self.root,
        ):
            write_log("El usuario canceló la confirmación del bloqueo.")
            return

        self.unlock_password = pwd
        self.lock_message_optional = msg if msg else None

        write_log("Confirmado bloqueo por el usuario.")
        self.setup_frame.destroy()
        self.setup_frame = None
        self.setup_caps_label = None
        self.root.withdraw()
        self.start_locking_process()

    def _snapshot_preexisting_processes(self):
        """Registra terminales/herramientas ya abiertos para no interrumpir tareas activas."""
        self._allowed_preexisting_procs = set()
        for pid, (name, _) in list_processes().items():
            if name in NEW_INSTANCE_BLOCK_TARGETS:
                ctime = get_process_creation_time(pid)
                self._allowed_preexisting_procs.add((pid, ctime))
        write_log(
            f"Snapshot de procesos previos preservados: {len(self._allowed_preexisting_procs)}."
        )

    def _is_descendant_of_allowed(self, pid, procs_map, child_ctime):
        """Permite subprocesos lanzados por scripts/terminales que ya estaban corriendo."""
        visited = {pid}
        cur_pid = pid
        cur_ctime = child_ctime
        while cur_pid in procs_map:
            _, ppid = procs_map[cur_pid]
            if not ppid or ppid in visited or ppid not in procs_map:
                break
            visited.add(ppid)
            p_ctime = get_process_creation_time(ppid)
            if cur_ctime is not None and p_ctime is not None and p_ctime > cur_ctime:
                break
            if (ppid, p_ctime) in self._allowed_preexisting_procs:
                return True
            cur_pid = ppid
            cur_ctime = p_ctime
        return False

    def _install_window_shield(self, win, create_shutdown_reason=True):
        """
        Subclasifica una ventana para interceptar y rechazar
        WM_QUERYENDSESSION, WM_ENDSESSION, WM_CLOSE y WM_SYSCOMMAND.
        """
        try:
            win.update_idletasks()
            hwnd = _get_toplevel_hwnd(win)
            if not hwnd:
                return
            if any(entry["hwnd"] == hwnd for entry in self._shielded_windows):
                return

            kernel32.SetProcessShutdownParameters(0x3FF, 0)
            if create_shutdown_reason:
                user32.ShutdownBlockReasonCreate(
                    hwnd,
                    "WinLock: Este equipo está bloqueado. Desbloquee antes de apagar o reiniciar.",
                )

            state = {"orig": None, "ref": None}

            def _shield_wndproc(h, msg, wParam, lParam):
                if self._is_locked:
                    if msg == WM_QUERYENDSESSION:
                        write_log("Intento de apagado/cierre de sesión interceptado y bloqueado.")
                        self._record_event(
                            "Intento de apagado o cierre de sesión interceptado.",
                            level="alert",
                            dedupe_key="shutdown_wm",
                            dedupe_seconds=2.0,
                        )
                        abort_system_shutdown()
                        return 0
                    if msg == WM_ENDSESSION:
                        return 0
                    if msg == WM_CLOSE:
                        return 0
                    if msg == WM_SYSCOMMAND and (wParam & 0xFFF0) in BLOCKED_SYSCOMMANDS:
                        return 0
                if state["orig"]:
                    return user32.CallWindowProcW(
                        state["orig"], h, msg, wParam, lParam
                    )
                return 0

            wndproc_ref = WNDPROC(_shield_wndproc)
            ptr = ctypes.cast(wndproc_ref, ctypes.c_void_p)
            old = _set_window_long_ptr(hwnd, GWLP_WNDPROC, ptr)
            if old:
                state["orig"] = old
                state["ref"] = wndproc_ref
                self._shielded_windows.append(
                    {
                        "hwnd": hwnd,
                        "orig": old,
                        "ref": wndproc_ref,
                        "reason": create_shutdown_reason,
                    }
                )
                if create_shutdown_reason:
                    write_log("Escudo anti-apagado (WM_QUERYENDSESSION) instalado.")
        except Exception as e:
            write_log("Error instalando el escudo de ventana.", level="WARNING", error=e)

    def _remove_window_shield(self):
        """Restaura el WndProc original y elimina el bloqueo de apagado."""
        for entry in reversed(self._shielded_windows):
            hwnd = entry["hwnd"]
            try:
                if entry.get("orig"):
                    _set_window_long_ptr(hwnd, GWLP_WNDPROC, entry["orig"])
            except Exception:
                pass
            if entry.get("reason"):
                try:
                    user32.ShutdownBlockReasonDestroy(hwnd)
                except Exception:
                    pass
        self._shielded_windows.clear()

    def start_locking_process(self):
        """Inicia todas las capas de protección manteniendo copias y terminales activos."""
        write_log("Iniciando proceso de bloqueo blindado.")
        self._is_locked = True
        self.lock_start_time = time.time()
        self.lock_start_dt = time.strftime("%H:%M:%S")
        self.failed_attempts = 0
        self.last_failed_time = None
        self.cooldown_until = 0.0
        self._held_shifts.clear()
        self._held_ctrls.clear()
        self._left_alt_down = False
        self._altgr_down = False
        self._caps_key_held = False
        self._caps_lock_on = bool(user32.GetKeyState(VK_CAPITAL) & 1)

        with self._key_events_lock:
            self._key_events.clear()

        with self._events_lock:
            self.security_events = []
            self._event_dedupe = {}

        self._record_event("Equipo bloqueado e inicio de protección.", level="info")

        self._snapshot_preexisting_processes()
        SystemGuard.engage()
        hide_taskbars()
        self.start_watchdog()

        try:
            kernel32.SetThreadExecutionState(
                0x80000000 | 0x00000001 | 0x00000002 | 0x00000040
            )
        except Exception as e:
            write_log("Error cambiando el estado de ejecución.", level="WARNING", error=e)

        self.create_lock_screen()

    def _kill_target_processes(self):
        """Cierra procesos prohibidos y solo nuevas instancias no autorizadas de terminales."""
        my_pid = os.getpid()
        procs_map = list_processes()
        for pid, (name, _) in procs_map.items():
            if not self._watchdog_running:
                return
            if not name or pid == my_pid:
                continue

            if name in ALWAYS_KILL_TARGETS:
                if terminate_process(pid):
                    write_log(f"Proceso bloqueado eliminado: {name} (PID {pid})")
                    self._record_event(
                        f"Proceso bloqueado terminado: {name}",
                        level="alert",
                        dedupe_key=f"kill:{name}",
                        dedupe_seconds=2.5,
                    )
                    if name in ("shutdown.exe", "logoff.exe", "slidetoshutdown.exe"):
                        abort_system_shutdown()
            elif name in NEW_INSTANCE_BLOCK_TARGETS:
                ctime = get_process_creation_time(pid)
                key = (pid, ctime)
                if key in self._allowed_preexisting_procs:
                    continue
                if self._is_descendant_of_allowed(pid, procs_map, ctime):
                    self._allowed_preexisting_procs.add(key)
                    continue
                if terminate_process(pid):
                    write_log(
                        f"Nueva instancia bloqueada eliminada: {name} (PID {pid})"
                    )
                    self._record_event(
                        f"Nueva instancia bloqueada cerrada: {name}",
                        level="warn",
                        dedupe_key=f"kill_new:{name}",
                        dedupe_seconds=2.5,
                    )

    def _watchdog_loop(self):
        """Loop de control en hilo secundario."""
        while self._watchdog_running:
            self._kill_target_processes()
            time.sleep(0.15)

    def start_watchdog(self):
        if not self._watchdog_running:
            self._watchdog_running = True
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, daemon=True
            )
            self._watchdog_thread.start()

    def stop_watchdog(self):
        self._watchdog_running = False
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=1.5)

    @staticmethod
    def _clip_cursor(primary_mon=None):
        """Ancla el cursor en el centro de la pantalla principal sin alterar ShowCursor."""
        try:
            if primary_mon:
                cx = primary_mon["left"] + (primary_mon["width"] // 2)
                cy = primary_mon["top"] + (primary_mon["height"] // 2)
            else:
                cx = user32.GetSystemMetrics(0) // 2
                cy = user32.GetSystemMetrics(1) // 2
            rect = ctypes.wintypes.RECT(cx, cy, cx + 1, cy + 1)
            user32.ClipCursor(ctypes.byref(rect))
            user32.SetCursorPos(cx, cy)
        except Exception as e:
            write_log(f"Error anclando el cursor: {e}", level="WARNING")

    @staticmethod
    def _hide_and_clip_cursor(primary_mon=None):
        """Oculta el cursor una vez y lo ancla en el centro de la pantalla principal."""
        try:
            ci = CURSORINFO()
            ci.cbSize = ctypes.sizeof(CURSORINFO)
            if not user32.GetCursorInfo(ctypes.byref(ci)) or (ci.flags & CURSOR_SHOWING):
                for _ in range(16):
                    if user32.ShowCursor(False) < 0:
                        break
            WinLock._clip_cursor(primary_mon)
        except Exception as e:
            write_log("Error ocultando el cursor.", level="WARNING", error=e)

    @staticmethod
    def _show_system_cursor():
        """Restaura el cursor y libera el movimiento en todas las pantallas."""
        try:
            if not user32.ClipCursor(None):
                write_log(
                    f"No se pudo liberar el movimiento del cursor (Win32={ctypes.get_last_error()}).",
                    level="WARNING",
                )
            for _ in range(32):
                if user32.ShowCursor(True) >= 0:
                    break
            else:
                write_log("El cursor sigue oculto tras intentar mostrarlo.", level="WARNING")
        except Exception as e:
            write_log("Error restaurando el cursor.", level="ERROR", error=e)

    def _build_secondary_screens(self, secondary_mons):
        """Crea o reconstruye ventanas negras en todos los monitores secundarios."""
        for sw in self.secondary_screens:
            try:
                if sw.winfo_exists():
                    sw.destroy()
            except Exception:
                pass
        self.secondary_screens = []

        for idx, mon in enumerate(secondary_mons):
            sec_win = tk.Toplevel(self.root)
            sec_win.title(f"WinLock Guard {idx}")
            sec_win.overrideredirect(True)
            sec_win.attributes("-topmost", True)
            sec_win.config(cursor="none", bg="#0a0a0a")
            sec_win.protocol("WM_DELETE_WINDOW", lambda: None)

            tk.Label(
                sec_win,
                text="WinLock - Pantalla protegida",
                font=("Segoe UI", 14),
                fg="#333333",
                bg="#0a0a0a",
                cursor="none",
            ).pack(expand=True)
            place_window_on_monitor(sec_win, mon)
            self.secondary_screens.append(sec_win)

    def _prune_stuck_modifiers(self):
        """Limpia modificadores cuyos KEYUP se perdieron (ej. tras Ctrl+Alt+Del)."""
        if self._held_shifts:
            self._held_shifts = {
                k for k in self._held_shifts if user32.GetAsyncKeyState(k) & 0x8000
            }
        if self._held_ctrls:
            self._held_ctrls = {
                k for k in self._held_ctrls if user32.GetAsyncKeyState(k) & 0x8000
            }
        if self._left_alt_down and not (user32.GetAsyncKeyState(VK_LMENU) & 0x8000):
            self._left_alt_down = False
        if self._altgr_down and not (user32.GetAsyncKeyState(VK_RMENU) & 0x8000):
            self._altgr_down = False

    def _on_raw_key_event(self, vk, scan_code, flags, is_down):
        """
        Procesa teclas capturadas por WH_KEYBOARD_LL (ya suprimidas para el SO)
        y encola únicamente acciones y caracteres seguros para el hilo de Tkinter.
        """
        if not self._is_locked:
            return

        if vk in (VK_SHIFT, VK_LSHIFT, VK_RSHIFT):
            if is_down:
                self._held_shifts.add(vk)
            else:
                self._held_shifts.discard(vk)
                self._held_shifts.discard(VK_SHIFT)
            return

        if vk == VK_RMENU or (vk == VK_MENU and (flags & LLKHF_EXTENDED)):
            self._altgr_down = is_down
            return

        if vk == VK_LMENU or (vk == VK_MENU and not (flags & LLKHF_EXTENDED)):
            self._left_alt_down = is_down
            return

        if vk in (VK_CONTROL, VK_LCONTROL, VK_RCONTROL):
            if is_down:
                self._held_ctrls.add(vk)
            else:
                self._held_ctrls.discard(vk)
                self._held_ctrls.discard(VK_CONTROL)
            return

        if vk == VK_CAPITAL:
            if is_down and not self._caps_key_held:
                self._caps_lock_on = not self._caps_lock_on
                self._enqueue_key("CAPS", self._caps_lock_on)
            self._caps_key_held = is_down
            return

        if not is_down:
            return

        if vk in BLOCKED_VK_CODES:
            return

        self._prune_stuck_modifiers()

        if self._left_alt_down:
            return

        if self._held_ctrls and not self._altgr_down:
            if vk == VK_BACK:
                self._enqueue_key("CLEAR")
            return

        if vk == VK_RETURN:
            self._enqueue_key("ENTER")
        elif vk == VK_BACK:
            self._enqueue_key("BACKSPACE")
        elif vk == VK_ESCAPE:
            self._enqueue_key("CLEAR")
        elif vk == VK_SPACE:
            self._enqueue_key("CHAR", " ")
        elif vk in NUMPAD_VK_CHARS:
            self._enqueue_key("CHAR", NUMPAD_VK_CHARS[vk])
        else:
            self._enqueue_key(
                "KEY",
                (
                    vk,
                    scan_code,
                    bool(self._held_shifts),
                    self._altgr_down,
                    self._caps_lock_on,
                ),
            )

    def create_lock_screen(self):
        """Crea ventanas de bloqueo en TODOS los monitores detectados."""
        write_log("Creando pantallas de bloqueo multi-monitor.")
        monitors = get_monitors_info()
        primary_mon = next((m for m in monitors if m["is_primary"]), monitors[0])
        secondary_mons = [m for m in monitors if m != primary_mon]
        self._monitor_signature = tuple(
            (m["left"], m["top"], m["width"], m["height"]) for m in monitors
        )
        write_log(f"Monitores detectados ({len(monitors)}): {self._monitor_signature}.")

        self._hide_and_clip_cursor(primary_mon)
        self._build_secondary_screens(secondary_mons)

        self.primary_lock_window = tk.Toplevel(self.root)
        lock_win = self.primary_lock_window
        lock_win.title("WinLock - Bloqueado")
        lock_win.overrideredirect(True)
        lock_win.attributes("-topmost", True)
        lock_win.config(cursor="none", bg="#1c1c1c")
        lock_win.protocol("WM_DELETE_WINDOW", lambda: None)

        place_window_on_monitor(lock_win, primary_mon)
        self._install_window_shield(lock_win, create_shutdown_reason=True)
        self._install_window_shield(self.root, create_shutdown_reason=False)

        tk.Label(
            lock_win,
            text=f"WinLock {LOCAL_VERSION} - LabDigital",
            font=("Segoe UI", 10),
            fg="#808080",
            bg="#1c1c1c",
            cursor="none",
        ).place(x=self._px(15), y=self._px(15), anchor="nw")

        tk.Label(
            lock_win,
            text="WinLock",
            font=("Segoe UI Black", 44),
            fg="white",
            bg="#1c1c1c",
            cursor="none",
        ).pack(pady=(self._px(45), 0))

        time_label = tk.Label(
            lock_win, font=("Segoe UI Light", 64), fg="white", bg="#1c1c1c", cursor="none"
        )
        time_label.pack(pady=(self._px(10), 0))

        date_label = tk.Label(
            lock_win,
            font=("Segoe UI Semilight", 20),
            fg="#A0A0A0",
            bg="#1c1c1c",
            cursor="none",
        )
        date_label.pack()

        duration_label = tk.Label(
            lock_win, font=("Segoe UI", 12), fg="#A0A0A0", bg="#1c1c1c", cursor="none"
        )
        duration_label.pack(pady=self._px(8))

        center_frame = tk.Frame(lock_win, bg="#1c1c1c", cursor="none")
        center_frame.pack(expand=True)

        tk.Label(
            center_frame,
            text="Contraseña:",
            font=("Segoe UI", 12),
            fg="#cccccc",
            bg="#1c1c1c",
            cursor="none",
        ).pack(pady=(self._px(10), self._px(5)))

        entry_frame = tk.Frame(
            center_frame,
            bg="#1c1c1c",
            highlightthickness=2,
            highlightbackground="#333333",
            cursor="none",
        )
        entry_frame.pack(pady=(0, self._px(8)))

        unlock_entry = tk.Entry(
            entry_frame,
            show="•",
            font=("Segoe UI", 16),
            bg="#1e1e1e",
            fg="white",
            insertbackground="white",
            disabledbackground="#1e1e1e",
            disabledforeground="white",
            readonlybackground="#1e1e1e",
            highlightthickness=0,
            relief="flat",
            bd=0,
            width=25,
            justify="center",
            state="readonly",
            cursor="none",
        )
        unlock_entry.pack(ipady=self._px(8))

        # Texto fijo y oculto mediante color de fondo para no desplazar ningún elemento
        caps_label = tk.Label(
            center_frame,
            text="Bloq Mayús activado",
            font=("Segoe UI", 9, "bold"),
            fg="#f0ad4e" if self._caps_lock_on else "#1c1c1c",
            bg="#1c1c1c",
            cursor="none",
        )
        caps_label.pack(pady=(0, self._px(2)))

        status_label = tk.Label(
            center_frame,
            text="",
            font=("Segoe UI", 11),
            fg="#ff3b30",
            bg="#1c1c1c",
            cursor="none",
        )
        status_label.pack(pady=self._px(4))

        if self.lock_message_optional:
            message_frame = tk.Frame(
                center_frame,
                bg="#252525",
                bd=1,
                relief="solid",
                padx=self._px(15),
                pady=self._px(10),
                cursor="none",
            )
            message_frame.pack(pady=(self._px(12), 0))
            tk.Label(
                message_frame,
                text="Mensaje del propietario:",
                font=("Segoe UI", 11, "bold"),
                fg="#ffffff",
                bg="#252525",
                cursor="none",
            ).pack()
            tk.Label(
                message_frame,
                text=self.lock_message_optional,
                font=("Segoe UI", 11),
                fg="#cccccc",
                bg="#252525",
                wraplength=min(self._px(600), max(300, primary_mon["width"] - 120)),
                justify="center",
                cursor="none",
            ).pack(pady=(self._px(5), 0))

        bottom_frame = tk.Frame(lock_win, bg="#1c1c1c", cursor="none")
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=self._px(18))
        tk.Label(
            bottom_frame,
            text="Este equipo está protegido con WinLock. Todos los intentos quedan registrados.",
            font=("Segoe UI", 10),
            fg="#808080",
            bg="#1c1c1c",
            cursor="none",
        ).pack()

        status_clear_job = {"id": None}

        def ceil_sec(delta):
            iv = int(delta)
            return max(1, iv + (1 if delta > iv else 0))

        def set_entry_text(action, value=""):
            unlock_entry.config(state="normal")
            if action == "append":
                if len(unlock_entry.get()) < 128:
                    unlock_entry.insert(tk.END, value)
            elif action == "backspace":
                cur = unlock_entry.get()
                if cur:
                    unlock_entry.delete(len(cur) - 1, tk.END)
            elif action == "clear":
                unlock_entry.delete(0, tk.END)
            unlock_entry.config(state="readonly")

        def flash_error_border():
            entry_frame.config(highlightbackground="#ff3b30")
            lock_win.after(
                600,
                lambda: entry_frame.winfo_exists()
                and entry_frame.config(highlightbackground="#333333"),
            )

        def check_password():
            now = time.time()
            if now < self.cooldown_until:
                rem = ceil_sec(self.cooldown_until - now)
                status_label.config(
                    text=f"Demasiados intentos fallidos ({self.failed_attempts}). Espere {rem}s..."
                )
                return

            entered_pass = unlock_entry.get()
            if const_time_equals(entered_pass, self.unlock_password):
                write_log(
                    f"Contraseña correcta. Desbloqueando (intentos fallidos: {self.failed_attempts})."
                )
                self._record_event("Contraseña correcta. Equipo desbloqueado.", level="ok")
                self._unlock_and_exit()
            else:
                self.failed_attempts += 1
                self.last_failed_time = time.strftime("%H:%M:%S")
                write_log(
                    f"Contraseña incorrecta introducida (intento #{self.failed_attempts}).",
                    level="WARNING",
                )
                self._record_event(
                    f"Intento de contraseña incorrecta (#{self.failed_attempts}).",
                    level="alert",
                )
                set_entry_text("clear")
                flash_error_border()

                # Cada 3 intentos fallidos obliga a esperar 10 segundos
                if self.failed_attempts % 3 == 0:
                    delay = 10
                    self.cooldown_until = time.time() + delay
                    write_log(f"Espera de {delay}s aplicada tras {self.failed_attempts} intentos fallidos.")
                    if status_clear_job["id"]:
                        lock_win.after_cancel(status_clear_job["id"])
                        status_clear_job["id"] = None
                    self._record_event(
                        f"Penalización de {delay}s activada tras {self.failed_attempts} intentos fallidos.",
                        level="warn",
                    )
                    status_label.config(
                        text=f"Demasiados intentos fallidos ({self.failed_attempts}). Espere {delay}s..."
                    )
                else:
                    status_label.config(
                        text=f"Contraseña incorrecta (intento {self.failed_attempts})"
                    )
                    if status_clear_job["id"]:
                        lock_win.after_cancel(status_clear_job["id"])
                    status_clear_job["id"] = lock_win.after(
                        2500,
                        lambda: status_label.winfo_exists()
                        and time.time() >= self.cooldown_until
                        and status_label.config(text=""),
                    )

        def process_key_queue():
            """Procesa los eventos de teclado pendientes en el hilo principal."""
            if not self._is_locked or not lock_win.winfo_exists():
                return
            with self._key_events_lock:
                pending = self._key_events
                self._key_events = []

            for kind, payload in pending:
                if kind == "CAPS":
                    caps_label.config(fg="#f0ad4e" if payload else "#1c1c1c")
                    continue

                if time.time() < self.cooldown_until:
                    continue

                if status_label.cget("text"):
                    status_label.config(text="")

                if kind == "ENTER":
                    check_password()
                    if not self._is_locked:
                        return
                elif kind == "BACKSPACE":
                    set_entry_text("backspace")
                elif kind == "CLEAR":
                    set_entry_text("clear")
                elif kind == "CHAR":
                    set_entry_text("append", payload)
                elif kind == "KEY":
                    char = translate_key_to_char(*payload)
                    if char:
                        set_entry_text("append", char)

            if self._is_locked and lock_win.winfo_exists():
                lock_win.after(20, process_key_queue)

        def update_time_and_duration():
            if not self._is_locked or not lock_win.winfo_exists():
                return
            lt = time.localtime()
            time_label.config(text=time.strftime("%H:%M", lt))
            date_label.config(text=format_spanish_date(lt))

            duration_label.config(
                text="Tiempo bloqueado: "
                + format_duration(time.time() - self.lock_start_time)
            )

            now = time.time()
            if now < self.cooldown_until:
                rem = ceil_sec(self.cooldown_until - now)
                status_label.config(
                    text=f"Demasiados intentos fallidos ({self.failed_attempts}). Espere {rem}s..."
                )
            elif self.cooldown_until > 0 and "Espere" in status_label.cget("text"):
                status_label.config(text="")
                self.cooldown_until = 0.0

            lock_win.after(500, update_time_and_duration)

        monitor_check_counter = {"n": 0}
        current_primary = {"mon": primary_mon}

        def enforce_protection():
            """Mantiene ventanas al frente, barra oculta, hooks activos, cursor anclado y monitores sincronizados."""
            if not self._is_locked or not lock_win.winfo_exists():
                return
            try:
                monitor_check_counter["n"] += 1
                if monitor_check_counter["n"] % 8 == 0:
                    mons = get_monitors_info()
                    sig = tuple(
                        (m["left"], m["top"], m["width"], m["height"]) for m in mons
                    )
                    if sig != self._monitor_signature:
                        write_log(
                            f"Cambio de configuración de monitores: {self._monitor_signature} → {sig}."
                        )
                        self._record_event(
                            f"Cambio de monitores detectado ({len(mons)} pantalla(s) activa(s)).",
                            level="warn",
                        )
                        self._monitor_signature = sig
                        p_mon = next((m for m in mons if m["is_primary"]), mons[0])
                        s_mons = [m for m in mons if m != p_mon]
                        current_primary["mon"] = p_mon
                        place_window_on_monitor(lock_win, p_mon)
                        self._build_secondary_screens(s_mons)

                if not self._input_blocker.is_active:
                    self._input_blocker.start()
                    self._record_event(
                        "Bloqueo de teclado/ratón restaurado automáticamente.",
                        level="warn",
                        dedupe_key="input_repair",
                        dedupe_seconds=5.0,
                    )

                hide_taskbars()
                self._clip_cursor(current_primary["mon"])

                primary_hwnd = _get_toplevel_hwnd(lock_win)
                lock_hwnds = {primary_hwnd}
                for sw in self.secondary_screens:
                    if sw.winfo_exists():
                        lock_hwnds.add(_get_toplevel_hwnd(sw))

                fg = user32.GetForegroundWindow()
                if fg and fg not in lock_hwnds:
                    pid = ctypes.wintypes.DWORD(0)
                    user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
                    if pid.value:
                        exe_path = get_process_exe_path(pid.value)
                        pname = os.path.basename(exe_path).lower() if exe_path else ""
                        if pname in MENU_OVERLAY_PROCESSES:
                            user32.ShowWindow(fg, SW_HIDE)
                            self._record_event(
                                f"Menú emergente del sistema ocultado ({pname}).",
                                level="warn",
                                dedupe_key=f"overlay:{pname}",
                                dedupe_seconds=3.0,
                            )

                for sw in self.secondary_screens:
                    force_window_topmost(sw)
                force_window_topmost(lock_win)
                if primary_hwnd:
                    user32.SetForegroundWindow(primary_hwnd)
            except Exception:
                pass

            if self._is_locked and lock_win.winfo_exists():
                lock_win.after(200, enforce_protection)

        self._input_blocker.start()
        lock_win.focus_force()

        update_time_and_duration()
        process_key_queue()
        enforce_protection()
        write_log("Ventanas de bloqueo inicializadas.")

    def show_unlock_summary_popup(self, total_seconds, start_time_str, end_time_str):
        """Muestra una ventana emergente personalizada en Tkinter con el resumen del bloqueo."""
        try:
            with self._events_lock:
                events_copy = list(self.security_events)

            alert_count = sum(1 for _, lvl, _ in events_copy if lvl in ("alert", "warn"))
            has_incidents = self.failed_attempts > 0 or alert_count > 0

            popup = tk.Toplevel(self.root)
            popup.title(f"Resumen de sesión - WinLock {LOCAL_VERSION}")
            popup.resizable(False, False)
            popup.configure(bg="#161616")

            try:
                popup.iconbitmap(resource_path("winlock.ico"))
            except Exception as e:
                write_log("No se pudo cargar el icono del resumen.", level="WARNING", error=e)

            def close_popup(event=None):
                try:
                    if popup.winfo_exists():
                        popup.destroy()
                except Exception as e:
                    write_log("Error cerrando el resumen de sesión.", level="WARNING", error=e)

            popup.protocol("WM_DELETE_WINDOW", close_popup)

            header = tk.Frame(
                popup, bg="#1f1f1f", padx=self._px(22), pady=self._px(16)
            )
            header.pack(fill=tk.X)

            badge_color = (
                "#ff4d4f"
                if self.failed_attempts > 0
                else ("#f0ad4e" if alert_count > 0 else "#2ea043")
            )
            badge_text = (
                "ALERTA DE SEGURIDAD"
                if self.failed_attempts > 0
                else ("EVENTOS REGISTRADOS" if alert_count > 0 else "TODO BIEN")
            )

            top_row = tk.Frame(header, bg="#1f1f1f")
            top_row.pack(fill=tk.X)

            tk.Label(
                top_row,
                text="Equipo desbloqueado",
                font=("Segoe UI", 16, "bold"),
                fg="#ffffff",
                bg="#1f1f1f",
            ).pack(side=tk.LEFT)

            tk.Label(
                top_row,
                text=badge_text,
                font=("Segoe UI", 8, "bold"),
                fg="#ffffff",
                bg=badge_color,
                padx=self._px(8),
                pady=self._px(3),
            ).pack(side=tk.RIGHT)

            tk.Label(
                header,
                text=f"Inicio: {start_time_str}   •   Desbloqueo: {end_time_str}",
                font=("Segoe UI", 9),
                fg="#a0a0a0",
                bg="#1f1f1f",
            ).pack(anchor="w", pady=(self._px(4), 0))

            stats_frame = tk.Frame(
                popup, bg="#161616", padx=self._px(20), pady=self._px(14)
            )
            stats_frame.pack(fill=tk.X)
            stats_frame.columnconfigure(0, weight=1)
            stats_frame.columnconfigure(1, weight=1)
            stats_frame.columnconfigure(2, weight=1)

            def make_stat_card(col, title, value, val_color="#ffffff"):
                card = tk.Frame(
                    stats_frame,
                    bg="#222222",
                    highlightthickness=1,
                    highlightbackground="#303030",
                    padx=self._px(12),
                    pady=self._px(10),
                )
                card.grid(row=0, column=col, sticky="nsew", padx=self._px(4))
                tk.Label(
                    card,
                    text=title,
                    font=("Segoe UI", 8),
                    fg="#9e9e9e",
                    bg="#222222",
                ).pack(anchor="w")
                tk.Label(
                    card,
                    text=value,
                    font=("Segoe UI", 14, "bold"),
                    fg=val_color,
                    bg="#222222",
                ).pack(anchor="w", pady=(self._px(2), 0))

            make_stat_card(
                0, "Tiempo total bloqueado", format_duration(total_seconds), "#4da6ff"
            )
            make_stat_card(
                1,
                "Intentos fallidos",
                str(self.failed_attempts),
                "#ff4d4f" if self.failed_attempts > 0 else "#3fb950",
            )
            make_stat_card(
                2,
                "Eventos registrados",
                str(len(events_copy)),
                "#f0ad4e" if has_incidents else "#e0e0e0",
            )

            events_container = tk.Frame(popup, bg="#161616", padx=self._px(24))
            events_container.pack(fill=tk.BOTH, expand=True)

            tk.Label(
                events_container,
                text="Registro de eventos durante el bloqueo:",
                font=("Segoe UI", 10, "bold"),
                fg="#d9d9d9",
                bg="#161616",
            ).pack(anchor="w", pady=(0, self._px(6)))

            log_box_frame = tk.Frame(
                events_container,
                bg="#111111",
                highlightthickness=1,
                highlightbackground="#303030",
            )
            log_box_frame.pack(fill=tk.BOTH, expand=True)

            scrollbar = ttk.Scrollbar(log_box_frame, orient="vertical")
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            events_text = tk.Text(
                log_box_frame,
                bg="#111111",
                fg="#d4d4d4",
                font=("Consolas", 9),
                relief="flat",
                bd=self._px(8),
                height=10,
                wrap="word",
                yscrollcommand=scrollbar.set,
                cursor="arrow",
            )
            events_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.config(command=events_text.yview)

            events_text.tag_configure("ts", foreground="#7a7a7a")
            events_text.tag_configure("info", foreground="#cccccc")
            events_text.tag_configure("warn", foreground="#f0ad4e")
            events_text.tag_configure("alert", foreground="#ff6b6b")
            events_text.tag_configure("ok", foreground="#3fb950")

            for ts, lvl, msg in events_copy:
                events_text.insert(tk.END, f"[{ts}] ", "ts")
                events_text.insert(
                    tk.END,
                    f"{msg}\n",
                    lvl if lvl in ("info", "warn", "alert", "ok") else "info",
                )

            if self.last_failed_time:
                events_text.insert(
                    tk.END,
                    f"\nÚltimo intento fallido registrado a las {self.last_failed_time}.\n",
                    "alert",
                )

            events_text.see(tk.END)
            events_text.config(state="disabled")

            footer = tk.Frame(
                popup, bg="#161616", padx=self._px(24), pady=self._px(16)
            )
            footer.pack(fill=tk.X)

            def open_logs_folder():
                try:
                    os.startfile(LOG_DIRECTORY)
                except Exception as e:
                    write_log("No se pudo abrir la carpeta de logs.", level="WARNING", error=e)

            tk.Button(
                footer,
                text="Abrir carpeta de logs",
                command=open_logs_folder,
                font=("Segoe UI", 9),
                bg="#2a2a2a",
                fg="#e0e0e0",
                activebackground="#3a3a3a",
                activeforeground="#ffffff",
                relief="flat",
                padx=self._px(12),
                pady=self._px(6),
                cursor="hand2",
            ).pack(side=tk.LEFT)

            close_btn = tk.Button(
                footer,
                text="Aceptar",
                command=close_popup,
                font=("Segoe UI", 10, "bold"),
                bg="#0078d4",
                fg="#ffffff",
                activebackground="#106ebe",
                activeforeground="#ffffff",
                relief="flat",
                padx=self._px(20),
                pady=self._px(6),
                cursor="hand2",
            )
            close_btn.pack(side=tk.RIGHT)

            self.center_window(
                popup, min_width=self._px(560), min_height=self._px(500)
            )
            popup.attributes("-topmost", True)
            popup.after(
                250, lambda: popup.winfo_exists() and popup.attributes("-topmost", False)
            )

            popup.bind("<Return>", close_popup)
            popup.bind("<Escape>", close_popup)
            popup.grab_set()
            popup.lift()
            popup.focus_force()
            close_btn.focus_set()

            write_log(f"Mostrando resumen de sesión ({len(events_copy)} eventos, {alert_count} alertas).")
            self.root.wait_window(popup)
        except Exception as e:
            write_log("Error mostrando el resumen de sesión.", level="ERROR", error=e)

    def _unlock_and_exit(self):
        """Desbloquea el sistema, restaura todas las políticas y muestra el resumen."""
        self._is_locked = False
        self.unlock_password = ""
        total_seconds = time.time() - self.lock_start_time
        end_time_str = time.strftime("%H:%M:%S")
        start_time_str = self.lock_start_dt or end_time_str
        write_log(f"Restaurando el escritorio tras {format_duration(total_seconds)} de bloqueo.")

        self._input_blocker.stop()
        self.stop_watchdog()
        self._remove_window_shield()
        SystemGuard.restore()
        restore_taskbars()
        self._show_system_cursor()

        restore_thread_execution_state()

        if self.primary_lock_window:
            try:
                self.primary_lock_window.destroy()
            except Exception as e:
                write_log("Error cerrando la ventana principal de bloqueo.", level="WARNING", error=e)
            self.primary_lock_window = None

        for sw in self.secondary_screens:
            try:
                sw.destroy()
            except Exception as e:
                write_log("Error cerrando una ventana secundaria de bloqueo.", level="WARNING", error=e)
        self.secondary_screens = []

        self.show_unlock_summary_popup(total_seconds, start_time_str, end_time_str)
        self._quit_app()

    def _quit_app(self):
        """Detiene vigilantes, restaura el sistema y finaliza limpiamente (idempotente)."""
        if self._is_quitting:
            return
        self._is_quitting = True
        self._is_locked = False
        self.unlock_password = ""

        write_log("Finalizando aplicación y restaurando sistema.")

        self._input_blocker.stop()
        self.stop_watchdog()
        self._remove_window_shield()
        SystemGuard.restore()
        restore_taskbars()
        self._show_system_cursor()

        for sw in self.secondary_screens:
            try:
                if sw.winfo_exists():
                    sw.destroy()
            except Exception as e:
                write_log("Error cerrando una ventana secundaria de bloqueo al salir.", level="WARNING", error=e)
        self.secondary_screens = []

        if self.primary_lock_window:
            try:
                if self.primary_lock_window.winfo_exists():
                    self.primary_lock_window.destroy()
            except Exception as e:
                write_log("Error cerrando la ventana principal de bloqueo al salir.", level="WARNING", error=e)
            self.primary_lock_window = None

        try:
            if hasattr(self, "root") and self.root.winfo_exists():
                self.root.quit()
                self.root.destroy()
        except Exception as e:
            write_log("Error cerrando la ventana principal de la aplicación.", level="WARNING", error=e)

        restore_thread_execution_state()
        write_log("Fin de la limpieza de la aplicación.")


# ==============================================================================
# SISTEMA DE AUTOACTUALIZACIÓN IN-PLACE (ROBUSTO, RESILIENTE Y EFICIENTE)
# ==============================================================================

def _build_clean_subprocess_env():
    """Devuelve el entorno del proceso limpiando variables heredadas de PyInstaller/Nuitka."""
    env = os.environ.copy()
    for var in (
        "_MEIPASS",
        "_MEIPASS2",
        "_PYI_APPLICATION_HOME_DIR",
        "_PYI_ARCHIVE_FILE",
        "_PYI_PARENT_PROCESS_LEVEL",
        "_PYI_SPLASH_IPC",
        "TCL_LIBRARY",
        "TK_LIBRARY",
        "NUITKA_ONEFILE_PARENT",
        "NUITKA_ONEFILE_BINARY",
        "NUITKA_ONEFILE_DIRECTORY",
        "NUITKA_ONEFILE_START",
        "NUITKA_ONEFILE_TIME_US",
        "NUITKA_ONEFILE_RANDOM",
        "NUITKA_ORIGINAL_ARGV0",
    ):
        env.pop(var, None)
    return env


def _collect_self_pids(target_exe):
    """
    Devuelve nuestro PID y el PID del proceso padre/bootstrapper (Nuitka --onefile
    o PyInstaller --onefile) que mantiene el bloqueo del .exe en disco.
    """
    my_pid = os.getpid()
    pids = [my_pid]
    try:
        nuitka_parent = os.environ.get("NUITKA_ONEFILE_PARENT", "").strip()
        if nuitka_parent.isdigit():
            npid = int(nuitka_parent)
            if npid > 0 and npid not in pids:
                pids.append(npid)

        norm_target = os.path.normcase(os.path.abspath(target_exe))
        procs = list_processes()
        if my_pid in procs:
            _, ppid = procs[my_pid]
            if ppid and ppid not in pids:
                parent_exe = get_process_exe_path(ppid)
                if parent_exe and os.path.normcase(os.path.abspath(parent_exe)) == norm_target:
                    pids.append(ppid)
    except Exception as e:
        write_log("Error identificando los procesos de WinLock para la actualización.", level="WARNING", error=e)
    return pids


def cleanup_update_staging_dir(dir_path, delay_seconds=1.5):
    """Elimina de forma segura la carpeta temporal de actualización en %TEMP%."""
    if not dir_path:
        write_log("No se indicó una carpeta temporal de actualización.", level="WARNING")
        return
    try:
        temp_root = os.path.normcase(get_temp_dir())
        target = os.path.abspath(dir_path)
        norm_target = os.path.normcase(target)
        base = os.path.basename(target)
        if not norm_target.startswith(temp_root + os.sep):
            write_log("Omitida limpieza de actualización: la carpeta está fuera de TEMP.", level="WARNING")
            return
        if not base.startswith(UPDATE_STAGING_PREFIX):
            write_log("Omitida limpieza de actualización: nombre de carpeta inesperado.", level="WARNING")
            return
    except Exception as e:
        write_log("No se pudo comprobar la ruta de limpieza de actualización.", level="WARNING", error=e)
        return

    def _worker():
        write_log(f"Limpieza de actualización programada (espera: {delay_seconds}s).")
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        for attempt in range(1, 6):
            if not os.path.exists(target):
                write_log("La carpeta temporal de actualización ya no existe.")
                return
            try:
                remove_tree(target, ignore_errors=False)
                write_log(f"Carpeta temporal de actualización limpiada (intento {attempt}): {target}")
                return
            except Exception as e:
                if attempt == 5:
                    write_log("Agotados los reintentos de limpieza temporal.", level="WARNING", error=e)
                time.sleep(0.5)
        remove_tree(target, ignore_errors=True)

    threading.Thread(target=_worker, name="UpdateCleanup", daemon=True).start()


def validate_pe_executable(
    file_path,
    expected_content_length=None,
    declared_size_bytes=0,
    expected_sha256=None,
):
    """
    Verifica rigurosamente que el archivo descargado es un ejecutable Windows PE válido
    y completo antes de tocar el .exe existente.
    """
    if not os.path.isfile(file_path):
        raise ValueError("El archivo descargado no existe.")

    actual_size = os.path.getsize(file_path)
    if actual_size < 256 * 1024:
        raise ValueError(
            f"El archivo descargado es demasiado pequeño ({format_bytes(actual_size)})."
        )

    if expected_content_length and actual_size != expected_content_length:
        raise ValueError(
            f"Tamaño incompleto: {format_bytes(actual_size)} de {format_bytes(expected_content_length)}."
        )

    if (
        not expected_content_length
        and declared_size_bytes > 0
        and actual_size < int(declared_size_bytes * 0.5)
    ):
        raise ValueError(
            f"El archivo descargado ({format_bytes(actual_size)}) no coincide con el tamaño esperado."
        )

    with open(file_path, "rb") as f:
        dos_header = f.read(64)
        if len(dos_header) < 64 or dos_header[:2] != b"MZ":
            raise ValueError(
                "El archivo descargado no es un ejecutable Windows válido (cabecera MZ)."
            )
        pe_offset = int.from_bytes(dos_header[0x3C:0x40], "little")
        if pe_offset < 64 or pe_offset > actual_size - 4:
            raise ValueError("Cabecera PE fuera de rango (archivo corrupto).")
        f.seek(pe_offset)
        if f.read(4) != b"PE\x00\x00":
            raise ValueError(
                "Firma PE inválida (posible página de error en lugar de .exe)."
            )

    if expected_sha256:
        expected_hex = str(expected_sha256).strip().lower()
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
        actual_hex = hasher.hexdigest().lower()
        if not const_time_equals(actual_hex, expected_hex):
            raise ValueError("La verificación de integridad SHA-256 no coincide.")

    try:
        ads_path = f"{file_path}:Zone.Identifier"
        if os.path.exists(ads_path):
            os.remove(ads_path)
    except Exception:
        pass

    return actual_size


def download_file_resilient(
    url,
    dest_path,
    declared_size_bytes=0,
    cancel_event=None,
    progress_cb=None,
    max_retries=3,
):
    """
    Descarga un archivo por HTTPS con streaming de 64 KB, timeout por lectura,
    reintentos automáticos y reanudación HTTP Range (206 Partial Content).
    """
    if not str(url).lower().startswith("https://"):
        raise ValueError("La URL de actualización debe utilizar HTTPS.")

    last_error = None
    chunk_size = 65536

    for attempt in range(1, max_retries + 1):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Descarga cancelada por el usuario.")

        resume_from = 0
        if attempt > 1 and os.path.exists(dest_path):
            resume_from = os.path.getsize(dest_path)

        headers = {
            "User-Agent": f"WinLock-Updater/{LOCAL_VERSION}",
            "Accept": "application/octet-stream, */*;q=0.8",
            "Cache-Control": "no-cache",
        }
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"

        write_log(f"Descarga: intento {attempt}/{max_retries} (bytes previos: {resume_from}).")
        if progress_cb:
            msg = (
                "Conectando con el servidor..."
                if attempt == 1
                else f"Reintentando descarga ({attempt}/{max_retries})..."
            )
            progress_cb(None, msg)

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as response:
                status = getattr(response, "status", response.getcode())
                content_len_hdr = response.headers.get("Content-Length")

                expected_total = None
                if status == 206 and resume_from > 0:
                    content_range = response.headers.get("Content-Range", "")
                    if "/" in content_range:
                        total_part = content_range.rsplit("/", 1)[1].strip()
                        if total_part.isdigit():
                            expected_total = int(total_part)
                    if expected_total is None and content_len_hdr and content_len_hdr.isdigit():
                        expected_total = resume_from + int(content_len_hdr)
                    file_mode = "ab"
                    downloaded = resume_from
                else:
                    if content_len_hdr and content_len_hdr.isdigit():
                        expected_total = int(content_len_hdr)
                    file_mode = "wb"
                    downloaded = 0

                write_log(
                    f"Respuesta de descarga HTTP {status} (bytes totales: {expected_total}, "
                    f"desplazamiento inicial: {downloaded})."
                )
                display_total = expected_total or declared_size_bytes or 0
                start_mono = time.monotonic()
                session_bytes = 0
                last_ui_update = 0.0

                with open(dest_path, file_mode) as out_file:
                    while True:
                        if cancel_event and cancel_event.is_set():
                            raise InterruptedError("Descarga cancelada por el usuario.")
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        n = len(chunk)
                        downloaded += n
                        session_bytes += n

                        now_mono = time.monotonic()
                        if progress_cb and (now_mono - last_ui_update >= 0.08):
                            last_ui_update = now_mono
                            elapsed = max(0.05, now_mono - start_mono)
                            speed_mbs = (session_bytes / 1048576.0) / elapsed
                            if display_total > 0:
                                pct = min(99, int(downloaded * 100 / display_total))
                                txt = (
                                    f"{downloaded / 1048576:.2f} MB / "
                                    f"{display_total / 1048576:.2f} MB "
                                    f"({pct}%)  •  {speed_mbs:.1f} MB/s"
                                )
                                progress_cb(pct, txt)
                            else:
                                txt = f"{downloaded / 1048576:.2f} MB descargados  •  {speed_mbs:.1f} MB/s"
                                progress_cb(None, txt)

                    out_file.flush()

                if expected_total is not None and downloaded != expected_total:
                    raise IOError(
                        f"Descarga incompleta ({downloaded} de {expected_total} bytes)."
                    )

                if progress_cb:
                    total_for_msg = expected_total or downloaded
                    progress_cb(
                        100,
                        f"{downloaded / 1048576:.2f} MB / {total_for_msg / 1048576:.2f} MB (100%)",
                    )
                write_log(
                    f"Descarga completada ({downloaded} bytes, {time.monotonic() - start_mono:.1f}s en este intento)."
                )
                return downloaded, expected_total

        except InterruptedError:
            raise
        except Exception as err:
            if getattr(err, "code", None) == 416 and os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                    write_log("Descarga parcial descartada tras recibir HTTP 416.")
                except OSError as e:
                    write_log("No se pudo borrar la descarga parcial tras HTTP 416.", level="WARNING", error=e)
            last_error = err
            write_log(
                f"Error de descarga en intento {attempt}/{max_retries}.",
                level="WARNING" if attempt < max_retries else "ERROR",
                error=err,
            )

        if attempt < max_retries:
            backoff = 1.0 * attempt
            end_wait = time.monotonic() + backoff
            while time.monotonic() < end_wait:
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("Descarga cancelada por el usuario.")
                time.sleep(0.1)

    raise RuntimeError(f"No se pudo completar la descarga: {last_error}")


def _launch_cmd_updater_fallback(target_exe, new_exe, backup_exe, staging_dir, wait_pids):
    """Plan B puro en cmd.exe si PowerShell no estuviera disponible."""
    bat_path = os.path.join(staging_dir, "updater.bat")
    workdir = os.path.dirname(target_exe) or "."
    pid_wait_lines = []
    for pid in wait_pids:
        pid_wait_lines.append(
            f'for /L %%i in (1,1,40) do ('
            f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul '
            f'&& (ping -n 1 -w 250 127.0.0.1 >nul) || goto :pid_{pid}_done'
            f')\r\n:pid_{pid}_done'
        )
    pid_block = "\r\n".join(pid_wait_lines)

    bat_content = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        f"{pid_block}\r\n"
        'copy /b /y "{target}" "{backup}" >nul 2>&1\r\n'
        "set OK=0\r\n"
        "for /L %%i in (1,1,30) do (\r\n"
        '    copy /b /y "{new}" "{target}" >nul 2>&1 && (set OK=1 & goto :copied)\r\n'
        "    ping -n 1 -w 250 127.0.0.1 >nul\r\n"
        ")\r\n"
        ":copied\r\n"
        'if "%OK%"=="0" (\r\n'
        '    if exist "{backup}" copy /b /y "{backup}" "{target}" >nul 2>&1\r\n'
        ")\r\n"
        "set _MEIPASS=\r\n"
        "set _MEIPASS2=\r\n"
        "set _PYI_APPLICATION_HOME_DIR=\r\n"
        "set _PYI_ARCHIVE_FILE=\r\n"
        "set _PYI_PARENT_PROCESS_LEVEL=\r\n"
        "set _PYI_SPLASH_IPC=\r\n"
        "set TCL_LIBRARY=\r\n"
        "set TK_LIBRARY=\r\n"
        "set NUITKA_ONEFILE_PARENT=\r\n"
        "set NUITKA_ONEFILE_BINARY=\r\n"
        "set NUITKA_ONEFILE_DIRECTORY=\r\n"
        "set NUITKA_ONEFILE_START=\r\n"
        "set NUITKA_ONEFILE_TIME_US=\r\n"
        "set NUITKA_ONEFILE_RANDOM=\r\n"
        "set NUITKA_ORIGINAL_ARGV0=\r\n"
        'start "" /D "{workdir}" "{target}" --updated --cleanup-update "{staging}"\r\n'
        'del /f /q "{new}" >nul 2>&1\r\n'
        'del /f /q "{backup}" >nul 2>&1\r\n'
        "exit /b 0\r\n"
    ).format(
        target=target_exe,
        new=new_exe,
        backup=backup_exe,
        workdir=workdir,
        staging=staging_dir,
    )

    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    subprocess.Popen(
        ["cmd.exe", "/d", "/c", bat_path],
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        env=_build_clean_subprocess_env(),
        close_fds=True,
    )


def launch_inplace_updater(target_exe, new_exe, staging_dir, target_version=""):
    """Lanza el actualizador independiente que sobrescribe el .exe in-place con rollback."""
    target_exe = os.path.abspath(target_exe)
    new_exe = os.path.abspath(new_exe)
    staging_dir = os.path.abspath(staging_dir)
    backup_exe = os.path.join(staging_dir, "WinLock_backup.exe")
    manifest_path = os.path.join(staging_dir, "manifest.json")
    ps_path = os.path.join(staging_dir, "updater.ps1")

    wait_pids = _collect_self_pids(target_exe)
    manifest = {
        "target_exe": target_exe,
        "new_exe": new_exe,
        "backup_exe": backup_exe,
        "staging_dir": staging_dir,
        "working_dir": os.path.dirname(target_exe) or ".",
        "log_path": UPDATER_LOG_PATH,
        "wait_pids": wait_pids,
        "target_version": str(target_version or ""),
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    ps_script = r"""param(
    [Parameter(Mandatory=$true)]
    [string]$ManifestPath,
    [switch]$Elevated
)

$ErrorActionPreference = "Stop"

$manifest = $null
try {
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    exit 1
}

$targetExe  = [string]$manifest.target_exe
$newExe     = [string]$manifest.new_exe
$backupExe  = [string]$manifest.backup_exe
$stagingDir = [string]$manifest.staging_dir
$workingDir = [string]$manifest.working_dir
$logPath    = [string]$manifest.log_path
$waitPids   = @($manifest.wait_pids)

function Write-UpdateLog {
    param([string]$Message)
    try {
        $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
        Add-Content -LiteralPath $logPath -Value "[$ts] [Updater] $Message" -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch {}
}

function Copy-InPlace {
    param(
        [Parameter(Mandatory=$true)][string]$SourcePath,
        [Parameter(Mandatory=$true)][string]$DestPath
    )
    $src = $null
    $dst = $null
    try {
        $src = [System.IO.File]::Open(
            $SourcePath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::Read
        )
        if (Test-Path -LiteralPath $DestPath) {
            $dst = [System.IO.File]::Open(
                $DestPath,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
        } else {
            $dst = [System.IO.File]::Open(
                $DestPath,
                [System.IO.FileMode]::Create,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
        }
        $dst.Position = 0
        $src.CopyTo($dst, 65536)
        $dst.SetLength($src.Length)
        $dst.Flush($true)
    } finally {
        if ($null -ne $dst) { $dst.Dispose() }
        if ($null -ne $src) { $src.Dispose() }
    }
}

function Clear-BundlerEnv {
    foreach ($v in @(
        "_MEIPASS", "_MEIPASS2", "_PYI_APPLICATION_HOME_DIR",
        "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL",
        "_PYI_SPLASH_IPC", "TCL_LIBRARY", "TK_LIBRARY",
        "NUITKA_ONEFILE_PARENT", "NUITKA_ONEFILE_BINARY",
        "NUITKA_ONEFILE_DIRECTORY", "NUITKA_ONEFILE_START",
        "NUITKA_ONEFILE_TIME_US", "NUITKA_ONEFILE_RANDOM",
        "NUITKA_ORIGINAL_ARGV0"
    )) {
        [Environment]::SetEnvironmentVariable($v, $null, "Process")
    }
}

function Start-TargetApp {
    param([bool]$PassUpdatedArgs)
    Clear-BundlerEnv
    $argStr = ""
    if ($PassUpdatedArgs) {
        $argStr = '--updated --cleanup-update "' + $stagingDir + '"'
    }
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        try {
            if ($argStr) {
                Start-Process -FilePath $targetExe -ArgumentList $argStr -WorkingDirectory $workingDir
            } else {
                Start-Process -FilePath $targetExe -WorkingDirectory $workingDir
            }
            return $true
        } catch {
            Write-UpdateLog "Reintento $attempt lanzando '$targetExe' fallido: $($_.Exception.Message)"
            Start-Sleep -Milliseconds 400
        }
    }
    return $false
}

Write-UpdateLog "Iniciando actualizacion in-place de '$targetExe' (Elevated=$Elevated)"

$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $deadline) {
    $stillRunning = $false
    foreach ($p in $waitPids) {
        if ($p -gt 0) {
            $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
            if ($null -ne $proc -and -not $proc.HasExited) {
                $stillRunning = $true
                break
            }
        }
    }
    if (-not $stillRunning) { break }
    Start-Sleep -Milliseconds 100
}

foreach ($p in $waitPids) {
    if ($p -gt 0) {
        $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
        if ($null -ne $proc -and -not $proc.HasExited) {
            Write-UpdateLog "Finalizando PID residual $p"
            Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
        }
    }
}
Start-Sleep -Milliseconds 180

if (-not (Test-Path -LiteralPath $newExe)) {
    Write-UpdateLog "ERROR: Ejecutable nuevo no encontrado en '$newExe'."
    exit 1
}

$expectedLen = (Get-Item -LiteralPath $newExe -Force).Length
$origCreationUtc = $null
$origAttributes = $null
$hasBackup = $false
$needsElevation = $false

if (Test-Path -LiteralPath $targetExe) {
    try {
        $fi = Get-Item -LiteralPath $targetExe -Force
        $origCreationUtc = $fi.CreationTimeUtc
        $origAttributes = $fi.Attributes
        if (($origAttributes -band [System.IO.FileAttributes]::ReadOnly) -ne 0) {
            try {
                [System.IO.File]::SetAttributes(
                    $targetExe,
                    ($origAttributes -band (-bnot [System.IO.FileAttributes]::ReadOnly))
                )
            } catch [System.UnauthorizedAccessException] {
                if (-not $Elevated) { $needsElevation = $true }
            }
        }
        [System.IO.File]::Copy($targetExe, $backupExe, $true)
        $hasBackup = $true
    } catch {
        Write-UpdateLog "Aviso preparando respaldo/metadatos: $($_.Exception.Message)"
    }
}

$replaced = $false
$unauthCount = 0
$lastErr = ""

if (-not $needsElevation) {
    for ($i = 1; $i -le 40; $i++) {
        try {
            Copy-InPlace -SourcePath $newExe -DestPath $targetExe
            $writtenLen = (Get-Item -LiteralPath $targetExe -Force).Length
            if ($writtenLen -ne $expectedLen) {
                throw "Tamano escrito ($writtenLen) distinto al esperado ($expectedLen)."
            }
            $replaced = $true
            break
        } catch [System.UnauthorizedAccessException] {
            $lastErr = $_.Exception.Message
            $unauthCount++
            if (-not $Elevated -and $unauthCount -ge 6) {
                $needsElevation = $true
                break
            }
            Start-Sleep -Milliseconds 250
        } catch {
            $lastErr = $_.Exception.Message
            Start-Sleep -Milliseconds 250
        }
    }
}

if ($needsElevation) {
    Write-UpdateLog "Permisos insuficientes para '$targetExe'. Solicitando elevacion UAC."
    $psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $psExe)) { $psExe = "powershell.exe" }
    $elevArgs = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $PSCommandPath + '" -ManifestPath "' + $ManifestPath + '" -Elevated'
    try {
        Start-Process -FilePath $psExe -Verb RunAs -WindowStyle Hidden -ArgumentList $elevArgs
        exit 0
    } catch {
        Write-UpdateLog "Elevacion UAC cancelada o fallida: $($_.Exception.Message)"
        Start-TargetApp -PassUpdatedArgs $false | Out-Null
        exit 1
    }
}

if (-not $replaced) {
    Write-UpdateLog "ERROR reemplazando '$targetExe': $lastErr"
    if ($hasBackup -and (Test-Path -LiteralPath $backupExe)) {
        Write-UpdateLog "Restaurando ejecutable original desde respaldo..."
        for ($r = 1; $r -le 10; $r++) {
            try {
                Copy-InPlace -SourcePath $backupExe -DestPath $targetExe
                Write-UpdateLog "Respaldo restaurado correctamente."
                break
            } catch {
                Start-Sleep -Milliseconds 250
            }
        }
    }
    Start-TargetApp -PassUpdatedArgs $false | Out-Null
    exit 1
}

if ($null -ne $origCreationUtc) {
    try { [System.IO.File]::SetCreationTimeUtc($targetExe, $origCreationUtc) } catch {}
}
if ($null -ne $origAttributes) {
    try { [System.IO.File]::SetAttributes($targetExe, $origAttributes) } catch {}
}
try { Unblock-File -LiteralPath $targetExe -ErrorAction SilentlyContinue } catch {}

Write-UpdateLog "Actualizacion in-place completada ($expectedLen bytes). Relanzando '$targetExe'."

$launched = Start-TargetApp -PassUpdatedArgs $true
if (-not $launched -and $hasBackup -and (Test-Path -LiteralPath $backupExe)) {
    Write-UpdateLog "No se pudo arrancar la nueva version. Ejecutando rollback..."
    try {
        Copy-InPlace -SourcePath $backupExe -DestPath $targetExe
        Start-TargetApp -PassUpdatedArgs $false | Out-Null
    } catch {}
}

Remove-Item -LiteralPath $newExe -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $backupExe -Force -ErrorAction SilentlyContinue
exit 0
"""

    with open(ps_path, "w", encoding="utf-8-sig") as f:
        f.write(ps_script)

    write_log(f"Archivos del instalador preparados para la versión {target_version!r}.")
    release_single_instance_mutex()

    ps_exe = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"),
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )
    if not os.path.isfile(ps_exe):
        ps_exe = find_in_path("powershell.exe") or find_in_path("pwsh.exe")

    if ps_exe:
        try:
            subprocess.Popen(
                [
                    ps_exe,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    ps_path,
                    "-ManifestPath",
                    manifest_path,
                ],
                creationflags=DETACHED_PROCESS
                | CREATE_NEW_PROCESS_GROUP
                | CREATE_NO_WINDOW,
                env=_build_clean_subprocess_env(),
                close_fds=True,
            )
            write_log(
                f"Actualizador PowerShell iniciado (PIDs monitorizados: {wait_pids}). "
                f"Detalles de instalación: {UPDATER_LOG_PATH}"
            )
            return
        except Exception as ps_err:
            write_log("No se pudo iniciar PowerShell; usando cmd.exe.", level="WARNING", error=ps_err)
    else:
        write_log("No se encontró PowerShell; usando cmd.exe.", level="WARNING")

    _launch_cmd_updater_fallback(target_exe, new_exe, backup_exe, staging_dir, wait_pids)
    write_log(f"Actualizador cmd.exe fallback iniciado (PIDs monitorizados: {wait_pids}).")


def show_startup_and_check_updates():
    """
    Muestra una ventana de carga mientras comprueba actualizaciones en segundo plano.
    Al pulsar 'Actualizar', descarga, verifica e instala in-place.
    Devuelve True si se inició una actualización y el programa debe salir.
    """
    write_log("Mostrando la ventana de inicio y comprobando actualizaciones.")
    splash = LoggedTk()
    splash.title("WinLock")
    splash.resizable(False, False)

    try:
        splash.iconbitmap(resource_path("winlock.ico"))
    except Exception as e:
        write_log("No se pudo cargar el icono de inicio.", level="WARNING", error=e)

    dpi_scale = get_dpi_scale(splash)

    def px(v):
        return max(1, int(round(v * dpi_scale)))

    def resize_and_center(min_w=430, min_h=175):
        splash.update_idletasks()
        w = max(px(min_w), splash.winfo_reqwidth())
        h = max(px(min_h), splash.winfo_reqheight())
        x = max(0, (splash.winfo_screenwidth() // 2) - (w // 2))
        y = max(0, (splash.winfo_screenheight() // 2) - (h // 2))
        splash.geometry(f"{w}x{h}+{x}+{y}")

    style = ttk.Style(splash)
    style.theme_use("clam")
    style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"))

    container = ttk.Frame(splash, padding=(px(20), px(18), px(20), px(18)))
    container.pack(expand=True, fill=tk.BOTH)

    ttk.Label(
        container,
        text=f"Iniciando WinLock {LOCAL_VERSION}...",
        font=("Segoe UI", 12, "bold"),
    ).pack(anchor="w")

    ttk.Label(
        container,
        text="Comprobando actualizaciones...",
        font=("Segoe UI", 9),
        foreground="#555555",
    ).pack(anchor="w", pady=(px(5), px(10)))

    progress = ttk.Progressbar(container, orient="horizontal", mode="indeterminate")
    progress.pack(fill=tk.X)
    progress.start(12)

    resize_and_center(410, 155)

    state = {
        "result": None,
        "done": False,
        "closed": False,
        "updating": False,
        "cancel_event": threading.Event(),
        "staging_dir": None,
    }

    def cleanup_current_staging():
        sdir = state.get("staging_dir")
        if sdir and not state["updating"]:
            state["staging_dir"] = None
            remove_tree(sdir, ignore_errors=True)

    def clear_container():
        for widget in container.winfo_children():
            if isinstance(widget, ttk.Progressbar):
                widget.stop()
            widget.destroy()

    def close_splash():
        write_log(f"Cerrando la ventana de inicio (instalador iniciado={state['updating']}).")
        state["closed"] = True
        state["cancel_event"].set()
        cleanup_current_staging()
        try:
            if splash.winfo_exists():
                try:
                    clear_container()
                finally:
                    splash.destroy()
        except Exception as e:
            write_log("Error cerrando la ventana de inicio.", level="WARNING", error=e)

    splash.protocol("WM_DELETE_WINDOW", close_splash)

    def check_network():
        started = time.monotonic()
        try:
            req = urllib.request.Request(
                LATEST_VERSION_JSON,
                headers={
                    "User-Agent": f"WinLock/{LOCAL_VERSION}",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                state["result"] = json.loads(response.read().decode("utf-8"))
            if isinstance(state["result"], dict):
                write_log(f"Metadatos de actualización recibidos en {time.monotonic() - started:.1f}s.")
            else:
                write_log("Formato inesperado en los metadatos de actualización.", level="WARNING")
        except Exception as err:
            write_log("Error consultando los metadatos de actualización.", level="WARNING", error=err)
            state["result"] = None
        finally:
            state["done"] = True

    threading.Thread(target=check_network, name="UpdateCheck", daemon=True).start()

    def show_error_view(latest_info, error_text):
        if state["closed"] or not splash.winfo_exists():
            return
        cleanup_current_staging()
        clear_container()

        ttk.Label(
            container,
            text="No se pudo completar la actualización",
            font=("Segoe UI", 11, "bold"),
            foreground="#b91c1c",
        ).pack(anchor="w")

        ttk.Label(
            container,
            text=error_text,
            font=("Segoe UI", 9),
            foreground="#444444",
            wraplength=px(390),
            justify="left",
        ).pack(anchor="w", pady=(px(6), px(12)))

        btn_row = ttk.Frame(container)
        btn_row.pack(fill=tk.X)

        def open_manual_site():
            try:
                os.startfile(UPDATE_URL)
                write_log("Abierta la web de actualización manual.")
            except Exception as e:
                write_log("No se pudo abrir la web de actualización manual.", level="WARNING", error=e)
            close_splash()

        ttk.Button(
            btn_row,
            text="Abrir web",
            command=open_manual_site,
        ).pack(side=tk.LEFT)

        ttk.Button(
            btn_row,
            text="Reintentar",
            style="Primary.TButton",
            command=lambda: start_autoupdate(latest_info),
        ).pack(side=tk.RIGHT, padx=(px(6), 0))

        ttk.Button(
            btn_row,
            text="Continuar",
            command=close_splash,
        ).pack(side=tk.RIGHT)

        resize_and_center(435, 175)

    def start_autoupdate(latest_info):
        if state["closed"] or not splash.winfo_exists():
            return

        compiled = is_compiled_executable()
        remote_tag = str(latest_info.get("tag_name") or "").strip()
        dl_url = str(latest_info.get("download_url") or "").strip()
        declared_size_bytes = parse_human_size(latest_info.get("size"))
        expected_sha256 = latest_info.get("sha256")
        write_log(
            f"Actualización solicitada a {remote_tag!r} (modo compilado={compiled}, "
            f"tamaño anunciado={declared_size_bytes} bytes)."
        )

        if compiled:
            target_exe = get_executable_path()
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            target_exe = os.path.join(script_dir, "WinLock.exe")

        try:
            temp_root = get_temp_dir()
            needed_bytes = max(30 * 1024 * 1024, int(declared_size_bytes * 2.5))
            free_bytes = get_free_disk_bytes(temp_root)
            if free_bytes is not None and free_bytes < needed_bytes:
                write_log(
                    f"Espacio temporal insuficiente (libre: {free_bytes}, requerido: {needed_bytes} bytes).",
                    level="WARNING",
                )
                show_error_view(
                    latest_info,
                    "No hay suficiente espacio libre en la unidad temporal para descargar la actualización.",
                )
                return
            if free_bytes is None:
                write_log(
                    f"No se pudo consultar el espacio temporal (Win32={ctypes.get_last_error()}).",
                    level="WARNING",
                )
        except Exception as e:
            write_log("Error comprobando el espacio libre para actualizar.", level="WARNING", error=e)

        state["cancel_event"] = threading.Event()
        cancel_ev = state["cancel_event"]

        clear_container()

        ttk.Label(
            container,
            text=f"Actualizando a WinLock {remote_tag}...",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")

        pb = ttk.Progressbar(
            container,
            orient="horizontal",
            mode="indeterminate" if not declared_size_bytes else "determinate",
            maximum=100,
        )
        pb.pack(fill=tk.X, pady=(px(10), px(6)))
        if not declared_size_bytes:
            pb.start(12)

        st = ttk.Label(
            container,
            text="Conectando con el servidor...",
            font=("Segoe UI", 9),
            foreground="#555555",
        )
        st.pack(anchor="w")

        footer = ttk.Frame(container)
        footer.pack(fill=tk.X, pady=(px(10), 0))

        cancel_btn = ttk.Button(
            footer,
            text="Cancelar",
            command=close_splash,
        )
        cancel_btn.pack(side=tk.RIGHT)

        resize_and_center(435, 175)

        ui_state = {"indeterminate": not bool(declared_size_bytes)}

        def update_ui(pct, text):
            if state["closed"] or not splash.winfo_exists():
                return
            if pct is None:
                if not ui_state["indeterminate"]:
                    pb.config(mode="indeterminate")
                    pb.start(12)
                    ui_state["indeterminate"] = True
            else:
                if ui_state["indeterminate"]:
                    pb.stop()
                    pb.config(mode="determinate")
                    ui_state["indeterminate"] = False
                pb["value"] = max(0, min(100, pct))
            st.config(text=text)

        def finalize_install(new_exe, staging_dir):
            if state["closed"] or cancel_ev.is_set():
                write_log("Instalación cancelada antes de aplicar la actualización.")
                cleanup_current_staging()
                return
            try:
                cancel_btn.config(state="disabled")
                update_ui(100, "Instalando y reiniciando WinLock...")
                splash.update_idletasks()

                if compiled:
                    state["updating"] = True
                    launch_inplace_updater(
                        target_exe=target_exe,
                        new_exe=new_exe,
                        staging_dir=staging_dir,
                        target_version=remote_tag,
                    )
                    close_splash()
                else:
                    copy_file_bytes(new_exe, target_exe)
                    write_log(f"Ejecutable actualizado guardado en: {target_exe}")
                    cleanup_current_staging()
                    messagebox.showinfo(
                        "Actualización descargada - WinLock",
                        f"Se ha descargado WinLock {remote_tag} en:\n{target_exe}\n\n"
                        "Ejecute ese archivo .exe para usar la nueva versión.",
                        parent=splash,
                    )
                    close_splash()
            except Exception as inst_err:
                state["updating"] = False
                write_log("Error aplicando la actualización descargada.", level="ERROR", error=inst_err)
                show_error_view(
                    latest_info,
                    f"La descarga se completó, pero no se pudo aplicar la actualización:\n{inst_err}",
                )

        def download_worker():
            staging_dir = os.path.join(
                get_temp_dir(),
                f"{UPDATE_STAGING_PREFIX}{os.urandom(5).hex()}",
            )
            state["staging_dir"] = staging_dir
            try:
                os.makedirs(staging_dir, exist_ok=True)
                write_log(f"Carpeta temporal de actualización preparada: {staging_dir}")
                staged_exe = os.path.join(staging_dir, "WinLock_new.exe")

                def on_progress(pct, text):
                    if not state["closed"] and not cancel_ev.is_set():
                        splash.after(0, update_ui, pct, text)

                _, server_len = download_file_resilient(
                    url=dl_url,
                    dest_path=staged_exe,
                    declared_size_bytes=declared_size_bytes,
                    cancel_event=cancel_ev,
                    progress_cb=on_progress,
                    max_retries=3,
                )

                if cancel_ev.is_set() or state["closed"]:
                    write_log("Actualización cancelada después de la descarga.")
                    remove_tree(staging_dir, ignore_errors=True)
                    return

                write_log(f"Verificando el ejecutable descargado (SHA-256 disponible={bool(expected_sha256)}).")
                splash.after(0, update_ui, 100, "Verificando integridad del ejecutable...")
                verified_size = validate_pe_executable(
                    file_path=staged_exe,
                    expected_content_length=server_len,
                    declared_size_bytes=declared_size_bytes,
                    expected_sha256=expected_sha256,
                )
                write_log(f"Verificación del ejecutable completada ({verified_size} bytes).")

                if cancel_ev.is_set() or state["closed"]:
                    write_log("Actualización cancelada después de la verificación.")
                    remove_tree(staging_dir, ignore_errors=True)
                    return

                splash.after(0, finalize_install, staged_exe, staging_dir)

            except InterruptedError:
                write_log("Autoactualización cancelada por el usuario.")
                remove_tree(staging_dir, ignore_errors=True)
            except Exception as ex:
                write_log("Error preparando la actualización.", level="ERROR", error=ex)
                if not state["closed"] and not cancel_ev.is_set():
                    splash.after(
                        0,
                        show_error_view,
                        latest_info,
                        f"Ocurrió un error al descargar o verificar la actualización:\n{ex}",
                    )
                else:
                    remove_tree(staging_dir, ignore_errors=True)

        threading.Thread(target=download_worker, name="UpdateDownload", daemon=True).start()

    def prompt_update(latest_info):
        clear_container()

        remote_tag = str(latest_info.get("tag_name") or "").strip()
        size_text = str(latest_info.get("size") or "").strip()
        size_suffix = f"  ({size_text})" if size_text else ""

        ttk.Label(
            container,
            text="¡Actualización disponible!",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            container,
            text=(
                f"Versión actual: {LOCAL_VERSION}  →  Disponible: {remote_tag}{size_suffix}\n"
                "Se actualizará automáticamente manteniendo el mismo archivo y ubicación."
            ),
            font=("Segoe UI", 9),
            foreground="#444444",
            wraplength=px(390),
            justify="left",
        ).pack(anchor="w", pady=(px(6), px(14)))

        btn_box = ttk.Frame(container)
        btn_box.pack(fill=tk.X)

        update_btn = ttk.Button(
            btn_box,
            text="Actualizar ahora",
            style="Primary.TButton",
            command=lambda: start_autoupdate(latest_info),
        )
        update_btn.pack(side=tk.RIGHT, padx=(px(6), 0))

        ttk.Button(
            btn_box,
            text="Más tarde",
            command=close_splash,
        ).pack(side=tk.RIGHT)

        resize_and_center(435, 175)
        update_btn.focus_set()

    def monitor_progress():
        if state["closed"] or not splash.winfo_exists():
            return
        if not state["done"]:
            splash.after(100, monitor_progress)
            return

        info = state["result"]
        if isinstance(info, dict):
            remote_tag = info.get("tag_name")
            dl_url = info.get("download_url")
            if not remote_tag or not dl_url or not str(dl_url).strip().lower().startswith("https://"):
                write_log("Metadatos sin versión o enlace HTTPS de descarga válido.", level="WARNING")
            elif parse_version(remote_tag) > parse_version(LOCAL_VERSION):
                write_log(f"Actualización disponible: {remote_tag!r}.")
                prompt_update(info)
                return
            else:
                write_log(f"No hay una versión más reciente (versión remota: {remote_tag!r}).")
        close_splash()

    splash.after(100, monitor_progress)
    splash.mainloop()
    return state["updating"]


def full_emergency_restore(explicit_restore=False):
    """Restaura políticas, botones de energía, barras de tareas, explorer, hooks y cursor."""
    write_log(f"Iniciando recuperación del sistema (modo explícito={explicit_restore}).")
    if _active_input_blocker is not None:
        try:
            _active_input_blocker.stop()
        except Exception as e:
            write_log("Error deteniendo el bloqueo de entrada durante la recuperación.", level="ERROR", error=e)

    try:
        SystemGuard.restore(force_fallback=explicit_restore)
    except Exception as e:
        write_log("Error restaurando la configuración de Windows.", level="ERROR", error=e)

    try:
        restore_taskbars()
    except Exception as e:
        write_log("Error restaurando las barras de tareas.", level="ERROR", error=e)

    if explicit_restore:
        start_explorer_if_not_running()

    try:
        WinLock._show_system_cursor()
    except Exception as e:
        write_log("Error restaurando el cursor durante la recuperación.", level="ERROR", error=e)

    restore_thread_execution_state()
    write_log("Fin de la recuperación del sistema.")


if __name__ == "__main__":
    just_updated = "--updated" in sys.argv
    just_elevated = "--elevated" in sys.argv

    # Modo silencioso de recuperación tras corte eléctrico, fallo o ejecución manual
    if "--restore" in sys.argv:
        write_log(f"Ejecutando recuperación robusta (--restore, admin={is_admin()}).")
        full_emergency_restore(explicit_restore=True)
        sys.exit(0)

    # Margen breve si venimos de reiniciar tras actualizar o elevar permisos
    mutex_handle, is_first_instance = acquire_single_instance_mutex(
        retries=25 if (just_updated or just_elevated) else 0,
        retry_delay=0.15,
    )
    if not is_first_instance:
        write_log("Inicio cancelado: ya hay otra instancia de WinLock.", level="WARNING")
        _r = LoggedTk()
        _r.withdraw()
        messagebox.showinfo("WinLock", "WinLock ya se está ejecutando.")
        _r.destroy()
        sys.exit(0)

    write_log(
        f"Modo de inicio: administrador={is_admin()}, compilado={is_compiled_executable()}, "
        f"recién actualizado={just_updated}, relanzado con elevación={just_elevated}."
    )

    # Antes de restaurar estado previo o comprobar actualizaciones: ofrecer auto-elevación (Sí/No)
    if not is_admin() and prompt_admin_elevation():
        sys.exit(0)

    # Si quedó un estado pendiente de una sesión interrumpida, restaurar (HKCU + HKLM si es Admin)
    if os.path.exists(RESTORE_STATE_PATH):
        write_log("Detectado estado pendiente de sesión anterior. Restaurando sistema.")
        full_emergency_restore(explicit_restore=True)
    else:
        write_log("No se encontró un estado pendiente de recuperación.")

    # Limpieza silenciosa de la carpeta temporal tras completar una autoactualización
    if "--cleanup-update" in sys.argv:
        try:
            idx = sys.argv.index("--cleanup-update")
            if idx + 1 < len(sys.argv):
                cleanup_update_staging_dir(sys.argv[idx + 1], delay_seconds=1.5)
            else:
                write_log("La opción --cleanup-update necesita una carpeta.", level="WARNING")
        except Exception as e:
            write_log("Error preparando la limpieza de actualización.", level="WARNING", error=e)

    # Si acaba de actualizarse, evitar comprobación redundante y posibles bucles de versión
    if just_updated:
        write_log("Comprobación de actualizaciones omitida tras el reinicio de la aplicación.")
    elif show_startup_and_check_updates():
        write_log("Cerrando WinLock para que el instalador aplique la actualización.")
        release_single_instance_mutex()
        sys.exit(0)

    app_instance = None
    try:
        root = LoggedTk()
        app_instance = WinLock(root)
        write_log("Iniciando el bucle principal de Tkinter.")
        root.mainloop()
        write_log("Bucle principal de Tkinter finalizado.")
    except (KeyboardInterrupt, SystemExit) as e:
        write_log(f"Cierre del hilo principal solicitado ({type(e).__name__}).")
    except Exception as e:
        write_log("Error general en el hilo principal.", level="ERROR", error=e)
    finally:
        if app_instance:
            app_instance._quit_app()
        else:
            full_emergency_restore()
        release_single_instance_mutex()
        write_log("Proceso principal de WinLock finalizado.")
        sys.exit(0)
