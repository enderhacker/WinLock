LOCAL_VERSION = "v0.9"

import sys

try:
    import psutil
    import subprocess
    import tkinter as tk
    from tkinter import ttk, messagebox
    import time
    import math
    import random
    import ctypes
    import ctypes.wintypes
    import keyboard
    import os
    import threading
    import queue
    import json
    import hmac
    import uuid
    import winreg
    import atexit
    import urllib.request
    import urllib.error
    import webbrowser
    import locale
    import hashlib
    import struct
    import shutil
    import tempfile
    import re
    from datetime import datetime
except ImportError as e:
    print(f"Faltan bibliotecas necesarias: {e}", file=sys.stderr)
    try:
        import tkinter as _tk
        from tkinter import messagebox as _mb

        _root = _tk.Tk()
        _root.withdraw()
        _mb.showerror(
            "Instalación fallida - WinLock",
            f"Faltan bibliotecas necesarias ({e.name}). Reinstala la aplicación.",
        )
        _root.destroy()
    except Exception:
        pass
    sys.exit(1)

# Windows DPI Awareness para mapeo exacto de píxeles en multi-monitor
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
try:
    powrprof = ctypes.WinDLL("powrprof", use_last_error=True)
except Exception:
    powrprof = None

LRESULT = ctypes.c_ssize_t
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


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, guid_str):
        return cls.from_buffer_copy(uuid.UUID(guid_str).bytes_le)

    def to_string(self):
        return str(uuid.UUID(bytes_le=bytes(self)))


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

user32.MapVirtualKeyExW.argtypes = [
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.wintypes.HKL,
]
user32.MapVirtualKeyExW.restype = ctypes.c_uint

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

user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.wintypes.LPARAM]
user32.EnumWindows.restype = ctypes.wintypes.BOOL

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

advapi32.AbortSystemShutdownW.argtypes = [ctypes.wintypes.LPCWSTR]
advapi32.AbortSystemShutdownW.restype = ctypes.wintypes.BOOL

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
SW_SHOW = 5
GWLP_WNDPROC = -4
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_SETTINGCHANGE = 0x001A
WM_SYSCOMMAND = 0x0112
SMTO_ABORTIFHUNG = 0x0002
ERROR_ALREADY_EXISTS = 183

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
LOG_FOLDER_NAME = "WinLock"
LOG_FILE_NAME = f"logs-{datetime.now().strftime('%d_%m_%Y-%H_%M_%S')}.txt"
LATEST_VERSION_JSON = (
    "https://raw.githubusercontent.com/enderhacker/WinLock/refs/heads/main/version.json"
)
UPDATE_URL = "https://winlock.labdigital.es"
UPDATE_STAGING_PREFIX = "WinLock_Update_"

_single_instance_mutex_handle = None

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

BLOCKED_SPECIAL_KEYS = {
    "left windows",
    "right windows",
    "apps",
    "tab",
    "home",
    "end",
    "insert",
    "delete",
    "page up",
    "page down",
    "print screen",
    "scroll lock",
    "pause",
    "sleep",
    "power",
    "wake",
    "f1",
    "f2",
    "f3",
    "f4",
    "f5",
    "f6",
    "f7",
    "f8",
    "f9",
    "f10",
    "f11",
    "f12",
    "up",
    "down",
    "left",
    "right",
    "num lock",
}


def is_admin():
    """Indica si la aplicación corre con privilegios de Administrador."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def parse_version(version_str):
    """Convierte versiones como 'v0.9', 'v0.10.0' en tuplas comparables normalizadas."""
    try:
        cleaned = str(version_str).strip().lstrip("vV")
        parts = []
        for seg in cleaned.split("."):
            m = re.match(r"^(\d+)", seg.strip())
            if m:
                parts.append(int(m.group(1)))
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
    m = re.match(r"^\s*([\d.,]+)\s*([KMGTP]?B?)\s*$", size_value.strip(), re.IGNORECASE)
    if not m:
        return 0
    try:
        num = float(m.group(1).replace(",", "."))
        unit = m.group(2).upper()
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
        return int(num * factors.get(unit, 1))
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

try:
    os.makedirs(LOG_DIRECTORY, exist_ok=True)
except OSError:
    pass


def write_log(message):
    """Escribe un mensaje detallado con timestamp en el archivo de logs."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        log_entry = f"[{timestamp}] - {message}\n"
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(log_entry)
    except Exception as e:
        print(f"Error al escribir en el log: {e}", file=sys.stderr)


def resource_path(relative_path):
    """Obtiene la ruta de los recursos junto al código o en el paquete."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def acquire_single_instance_mutex(retries=0, retry_delay=0.15):
    """Evita múltiples instancias simultáneas de WinLock con soporte de reintento tras actualizar."""
    global _single_instance_mutex_handle
    for attempt in range(retries + 1):
        handle = kernel32.CreateMutexW(None, False, "Local\\WinLock_SingleInstance_Mutex")
        if not handle:
            return None, True
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            if attempt < retries:
                time.sleep(retry_delay)
                continue
            return None, False
        _single_instance_mutex_handle = handle
        return handle, True
    return None, False


def release_single_instance_mutex():
    """Libera explícitamente el mutex de instancia única."""
    global _single_instance_mutex_handle
    if _single_instance_mutex_handle:
        try:
            kernel32.CloseHandle(_single_instance_mutex_handle)
        except Exception:
            pass
        _single_instance_mutex_handle = None


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
        user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Policy",
            SMTO_ABORTIFHUNG,
            300,
            ctypes.byref(res),
        )
    except Exception:
        pass


def start_explorer_if_not_running():
    """Verifica si explorer.exe se está ejecutando y lo inicia si no es así."""
    try:
        explorer_running = any(
            (proc.info.get("name") or "").lower() == "explorer.exe"
            for proc in psutil.process_iter(["name"])
        )
        if not explorer_running:
            write_log("explorer.exe no estaba ejecutándose. Iniciando explorer.exe.")
            subprocess.Popen("explorer.exe")
    except Exception as e:
        write_log(f"Aviso verificando/iniciando explorer.exe: {e}")


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
        if getattr(sys, "frozen", False):
            return f'"{os.path.abspath(sys.executable)}" --restore'
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
            write_log(f"Aviso gestionando RunOnce de recuperación: {e}")

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
            write_log(f"Aviso modificando botones de energía: {e}")
            return None
        finally:
            try:
                kernel32.LocalFree(scheme_ptr)
            except Exception:
                pass

    @classmethod
    def _restore_power_buttons(cls, power_backup):
        if not power_backup or powrprof is None:
            return
        try:
            scheme_guid = GUID.from_string(power_backup["scheme_guid"])
            subgroup = GUID.from_string(GUID_SYSTEM_BUTTON_SUBGROUP)
            for item in power_backup.get("settings", []):
                try:
                    setting_guid = GUID.from_string(item["guid"])
                    if item.get("ac") is not None:
                        powrprof.PowerWriteACValueIndex(
                            None,
                            ctypes.byref(scheme_guid),
                            ctypes.byref(subgroup),
                            ctypes.byref(setting_guid),
                            int(item["ac"]),
                        )
                    if item.get("dc") is not None:
                        powrprof.PowerWriteDCValueIndex(
                            None,
                            ctypes.byref(scheme_guid),
                            ctypes.byref(subgroup),
                            ctypes.byref(setting_guid),
                            int(item["dc"]),
                        )
                except Exception as e:
                    write_log(f"Aviso restaurando ajuste de energía {item.get('guid')}: {e}")
            powrprof.PowerSetActiveScheme(None, ctypes.byref(scheme_guid))
            write_log("Botones de energía restaurados a su configuración original.")
        except Exception as e:
            write_log(f"Error restaurando botones de energía: {e}")

    @classmethod
    def _fallback_cleanup_policies(cls):
        """
        Limpieza segura sin archivo de respaldo: elimina únicamente las políticas
        restrictivas de WinLock si coinciden con los valores de bloqueo.
        Funciona con o sin permisos de Administrador (omite HKLM si no hay permisos).
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
                    f"Sin permisos de Administrador para limpiar {hive_name}\\{subkey}\\{value_name} (continuando)."
                )
            except Exception as e:
                write_log(f"Aviso en limpieza de respaldo ({value_name}): {e}")
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
                    write_log(f"Aviso leyendo política {hive_name}\\{subkey}\\{value_name}: {e}")

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
            except Exception as e:
                write_log(f"Error guardando estado de recuperación: {e}")

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
                    write_log(f"Error aplicando política {value_name}: {e}")

            cls._engaged = True
            broadcast_policy_change()
            write_log(f"SystemGuard activado ({applied} políticas aplicadas).")

    @classmethod
    def restore(cls, force_fallback=False):
        """
        Restaura exactamente el registro y los botones de energía previos.
        Si no existe respaldo o está dañado y force_fallback=True, realiza una
        limpieza segura sin requerir privilegios de Administrador.
        """
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
                except Exception as e:
                    state_corrupt = True
                    write_log(f"Archivo de recuperación ilegible o dañado: {e}")

            if state_payload:
                skipped_admin = 0
                for entry in state_payload.get("registry", []):
                    hive = cls.HIVES.get(entry.get("hive"))
                    if not hive:
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
                    except PermissionError:
                        skipped_admin += 1
                        write_log(
                            f"Sin permisos de Administrador para restaurar {entry.get('hive')}\\{entry.get('name')}; continuando."
                        )
                        continue
                    except Exception as e:
                        write_log(
                            f"Error restaurando política {entry.get('name')}: {e}"
                        )

                cls._restore_power_buttons(state_payload.get("power"))

                try:
                    os.remove(RESTORE_STATE_PATH)
                except OSError:
                    pass

                cls._set_runonce_recovery(False)
                broadcast_policy_change()
                if skipped_admin:
                    write_log(
                        f"SystemGuard restaurado parcialmente ({skipped_admin} entradas HKLM requieren Administrador)."
                    )
                else:
                    write_log("SystemGuard restaurado por completo.")
            elif force_fallback or state_corrupt:
                if state_corrupt:
                    try:
                        os.remove(RESTORE_STATE_PATH)
                    except OSError:
                        pass
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
    for hwnd in find_taskbar_windows():
        try:
            user32.EnableWindow(hwnd, True)
            user32.ShowWindow(hwnd, SW_SHOW)
        except Exception:
            pass


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

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL,
        ctypes.wintypes.HMONITOR,
        ctypes.wintypes.HDC,
        ctypes.POINTER(ctypes.wintypes.RECT),
        ctypes.wintypes.LPARAM,
    )

    callback = MONITORENUMPROC(_monitor_enum_callback)
    user32.EnumDisplayMonitors(0, 0, callback, 0)

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


def translate_key_to_char(
    scan_code, is_keypad, shift_on, altgr_on, caps_on, fallback_name
):
    """Traduce un scan_code al carácter Unicode exacto según el teclado de Windows."""
    if is_keypad:
        if fallback_name == "decimal":
            return "."
        if fallback_name and len(fallback_name) == 1 and fallback_name.isprintable():
            return fallback_name
        return ""

    try:
        hkl = user32.GetKeyboardLayout(0)
        vk = user32.MapVirtualKeyExW(scan_code, 1, hkl)  # MAPVK_VSC_TO_VK
        if vk:
            key_state = (ctypes.c_ubyte * 256)()
            if shift_on:
                key_state[0x10] = 0x80  # VK_SHIFT
            if altgr_on:
                key_state[0x11] = 0x80  # VK_CONTROL
                key_state[0x12] = 0x80  # VK_MENU
            if caps_on:
                key_state[0x14] = 0x01  # VK_CAPITAL

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

    if fallback_name and len(fallback_name) == 1 and fallback_name.isprintable():
        if fallback_name.isalpha():
            is_upper = (caps_on and not shift_on) or (not caps_on and shift_on)
            return fallback_name.upper() if is_upper else fallback_name.lower()
        return fallback_name
    return ""


def force_window_topmost(win):
    """Fuerza que una ventana de Tkinter permanezca sobre cualquier otra."""
    try:
        if not win.winfo_exists():
            return
        win.attributes("-topmost", True)
        win.lift()
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
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


class MouseBlocker:
    """Bloquea movimiento y clics del ratón mediante WH_MOUSE_LL en un hilo dedicado."""

    WH_MOUSE_LL = 14
    WM_QUIT = 0x0012

    def __init__(self):
        self._thread = None
        self._thread_id = None
        self._hook_id = None
        self._hook_proc = None
        self._running = False
        self._ready_event = threading.Event()

    @property
    def is_active(self):
        return bool(
            self._running
            and self._hook_id
            and self._thread
            and self._thread.is_alive()
        )

    def start(self):
        if self.is_active:
            return
        self._running = True
        self._ready_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready_event.wait(timeout=1.0)

    def _run(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        msg = ctypes.wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        def _low_level_mouse_proc(nCode, wParam, lParam):
            if nCode >= 0 and self._running:
                return 1
            return user32.CallNextHookEx(self._hook_id, nCode, wParam, lParam)

        self._hook_proc = HOOKPROC(_low_level_mouse_proc)
        self._hook_id = user32.SetWindowsHookExW(
            self.WH_MOUSE_LL, self._hook_proc, None, 0
        )
        self._ready_event.set()

        if not self._hook_id:
            write_log(
                f"No se pudo instalar WH_MOUSE_LL (error={ctypes.get_last_error()})."
            )
            self._running = False
            return

        while self._running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._hook_id:
            user32.UnhookWindowsHookEx(self._hook_id)
            self._hook_id = None

    def stop(self):
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
        self._mouse_blocker = MouseBlocker()
        self._is_locked = False
        self._is_quitting = False
        self._key_queue = queue.Queue()
        self._held_shifts = set()
        self._held_ctrls = set()
        self._left_alt_down = False
        self._altgr_down = False
        self._caps_lock_on = bool(user32.GetKeyState(0x14) & 1)
        self._caps_key_held = False

        # Subclasificación de ventana anti-apagado y anti-cierre
        self._shielded_hwnd = None
        self._orig_wndproc = None
        self._wndproc_ref = None

        self.setup_frame = None
        self.setup_caps_label = None
        self.secondary_screens = []
        self.primary_lock_window = None
        self._monitor_signature = None

        try:
            locale.setlocale(locale.LC_TIME, "es_ES.UTF-8")
        except locale.Error:
            try:
                locale.setlocale(locale.LC_TIME, "Spanish_Spain.1252")
            except locale.Error:
                pass

        self.root.title(f"WinLock {LOCAL_VERSION}")
        self.root.geometry("410x375")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._quit_app)

        try:
            self.root.iconbitmap(resource_path("winlock.ico"))
        except Exception:
            pass

        self.center_window(self.root)

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

    def _record_event(self, message, level="info", dedupe_key=None, dedupe_seconds=3.0):
        """Registra un evento cronológico de la sesión de bloqueo (thread-safe)."""
        now_mono = time.monotonic()
        ts = datetime.now().strftime("%H:%M:%S")
        with self._events_lock:
            if dedupe_key is not None:
                last_seen = self._event_dedupe.get(dedupe_key, 0.0)
                if now_mono - last_seen < dedupe_seconds:
                    return
                self._event_dedupe[dedupe_key] = now_mono
            self.security_events.append((ts, level, message))

    def center_window(self, win):
        """Centra una ventana de tkinter en la pantalla principal."""
        win.update_idletasks()
        width = win.winfo_width()
        height = win.winfo_height()
        x = (win.winfo_screenwidth() // 2) - (width // 2)
        y = (win.winfo_screenheight() // 2) - (height // 2)
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
        caps_on = bool(user32.GetKeyState(0x14) & 1)
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

        self.setup_frame = ttk.Frame(self.root, padding="20 18 20 18")
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
        self.password_entry.pack(fill=tk.X, pady=(2, 10), ipady=3)

        ttk.Label(self.setup_frame, text="Mensaje (opcional):", font=font_style).pack(
            anchor="w"
        )
        self.message_text = tk.Text(
            self.setup_frame, height=7, width=35, wrap="word", font=font_style
        )
        self.message_text.pack(fill=tk.BOTH, expand=True, pady=(2, 10))

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
            wraplength=365,
        ).pack(anchor="w", pady=(0, 10))

        self.lock_button = ttk.Button(
            self.setup_frame,
            text="Bloquear equipo",
            command=self.validate_and_confirm,
            style="Lock.TButton",
        )
        self.lock_button.pack(pady=0, ipady=4, fill=tk.X)

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

        self.root.lift()
        self.root.focus_force()
        self.password_entry.focus_set()

    def validate_and_confirm(self):
        """Valida la entrada y pide confirmación antes de bloquear."""
        pwd = self.password_entry.get()

        if len(pwd) < 1:
            messagebox.showwarning(
                "Atención", "La contraseña no puede estar vacía.", parent=self.root
            )
            self.password_entry.focus_set()
            return

        msg = self.message_text.get("1.0", tk.END).strip()
        if len(msg) > 1000:
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
        for proc in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name in NEW_INSTANCE_BLOCK_TARGETS:
                    self._allowed_preexisting_procs.add(
                        (proc.info["pid"], proc.info.get("create_time"))
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        write_log(
            f"Snapshot de procesos previos preservados: {len(self._allowed_preexisting_procs)}."
        )

    def _is_descendant_of_allowed(self, proc):
        """Permite subprocesos lanzados por scripts/terminales que ya estaban corriendo."""
        try:
            for parent in proc.parents():
                if (
                    parent.pid,
                    parent.create_time(),
                ) in self._allowed_preexisting_procs:
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
        return False

    def _install_window_shield(self, win):
        """
        Subclasifica la ventana de bloqueo para interceptar y rechazar
        WM_QUERYENDSESSION, WM_ENDSESSION, WM_CLOSE y WM_SYSCOMMAND.
        """
        try:
            win.update_idletasks()
            hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
            if not hwnd:
                return

            kernel32.SetProcessShutdownParameters(0x3FF, 0)
            user32.ShutdownBlockReasonCreate(
                hwnd,
                "WinLock: Este equipo está bloqueado. Desbloquee antes de apagar o reiniciar.",
            )

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
                if self._orig_wndproc:
                    return user32.CallWindowProcW(
                        self._orig_wndproc, h, msg, wParam, lParam
                    )
                return 0

            self._wndproc_ref = WNDPROC(_shield_wndproc)
            ptr = ctypes.cast(self._wndproc_ref, ctypes.c_void_p)
            old = _set_window_long_ptr(hwnd, GWLP_WNDPROC, ptr)
            if old:
                self._shielded_hwnd = hwnd
                self._orig_wndproc = old
                write_log("Escudo anti-apagado (WM_QUERYENDSESSION) instalado.")
        except Exception as e:
            write_log(f"Error instalando escudo de ventana: {e}")

    def _remove_window_shield(self):
        """Restaura el WndProc original y elimina el bloqueo de apagado."""
        if self._shielded_hwnd:
            try:
                if self._orig_wndproc:
                    _set_window_long_ptr(
                        self._shielded_hwnd, GWLP_WNDPROC, self._orig_wndproc
                    )
            except Exception:
                pass
            try:
                user32.ShutdownBlockReasonDestroy(self._shielded_hwnd)
            except Exception:
                pass
            self._shielded_hwnd = None
            self._orig_wndproc = None
            self._wndproc_ref = None

    def start_locking_process(self):
        """Inicia todas las capas de protección manteniendo copias y terminales activos."""
        write_log("Iniciando proceso de bloqueo blindado.")
        self._is_locked = True
        self.lock_start_time = time.time()
        self.lock_start_dt = datetime.now().strftime("%H:%M:%S")
        self.failed_attempts = 0
        self.last_failed_time = None
        self.cooldown_until = 0.0
        self._caps_lock_on = bool(user32.GetKeyState(0x14) & 1)

        while not self._key_queue.empty():
            try:
                self._key_queue.get_nowait()
            except queue.Empty:
                break

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
            write_log(f"FALLO al cambiar estado de ejecución: {e}")

        self.create_lock_screen()

    def _kill_target_processes(self):
        """Cierra procesos prohibidos y solo nuevas instancias no autorizadas de terminales."""
        for proc in psutil.process_iter(["pid", "name", "create_time"]):
            if not self._watchdog_running:
                return
            try:
                name = (proc.info.get("name") or "").lower()
                if not name:
                    continue

                if name in ALWAYS_KILL_TARGETS:
                    proc.kill()
                    write_log(f"Proceso bloqueado eliminado: {name} (PID {proc.pid})")
                    self._record_event(
                        f"Proceso bloqueado terminado: {name}",
                        level="alert",
                        dedupe_key=f"kill:{name}",
                        dedupe_seconds=2.5,
                    )
                    if name in ("shutdown.exe", "logoff.exe", "slidetoshutdown.exe"):
                        abort_system_shutdown()
                elif name in NEW_INSTANCE_BLOCK_TARGETS:
                    key = (proc.info["pid"], proc.info.get("create_time"))
                    if key in self._allowed_preexisting_procs:
                        continue
                    if self._is_descendant_of_allowed(proc):
                        self._allowed_preexisting_procs.add(key)
                        continue
                    proc.kill()
                    write_log(
                        f"Nueva instancia bloqueada eliminada: {name} (PID {proc.pid})"
                    )
                    self._record_event(
                        f"Nueva instancia bloqueada cerrada: {name}",
                        level="warn",
                        dedupe_key=f"kill_new:{name}",
                        dedupe_seconds=2.5,
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                pass

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
    def _hide_and_clip_cursor(primary_mon=None):
        """Oculta y ancla el cursor en el centro de la pantalla principal."""
        try:
            while user32.ShowCursor(False) >= 0:
                pass
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
            write_log(f"Error ocultando cursor: {e}")

    @staticmethod
    def _show_system_cursor():
        """Restaura el cursor y libera el movimiento en todas las pantallas."""
        try:
            user32.ClipCursor(None)
            while user32.ShowCursor(True) < 0:
                pass
        except Exception as e:
            write_log(f"Error restaurando cursor: {e}")

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
            sec_win.geometry(
                f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}"
            )
            sec_win.attributes("-topmost", True)
            sec_win.config(cursor="none", bg="#0a0a0a")
            sec_win.protocol("WM_DELETE_WINDOW", lambda: None)

            sec_label = tk.Label(
                sec_win,
                text="WinLock - Pantalla protegida",
                font=("Segoe UI", 14),
                fg="#333333",
                bg="#0a0a0a",
                cursor="none",
            )
            sec_label.pack(expand=True)
            self.secondary_screens.append(sec_win)

    def _on_raw_key_event(self, event):
        """
        Hook global de teclado (hilo de keyboard).
        Suprime SIEMPRE todos los eventos (KEY_DOWN y KEY_UP) devolviendo False
        y encola las teclas seguras para el hilo principal de Tkinter.
        """
        if not self._is_locked:
            return True

        name = (event.name or "").lower()
        is_down = event.event_type == keyboard.KEY_DOWN
        scan_code = event.scan_code

        if name in ("shift", "left shift", "right shift"):
            if is_down:
                self._held_shifts.add(scan_code)
            else:
                self._held_shifts.discard(scan_code)
            return False

        if name in ("right alt", "alt gr"):
            self._altgr_down = is_down
            return False

        if name in ("alt", "left alt"):
            self._left_alt_down = is_down
            return False

        if name in ("ctrl", "left ctrl", "right ctrl"):
            if is_down:
                self._held_ctrls.add(scan_code)
            else:
                self._held_ctrls.discard(scan_code)
            return False

        if name in ("caps lock", "bloq mayús", "bloq mayus") or (
            scan_code == 58 and not event.is_keypad
        ):
            if is_down and not self._caps_key_held:
                self._caps_lock_on = not self._caps_lock_on
                self._key_queue.put(("CAPS", self._caps_lock_on))
            self._caps_key_held = is_down
            return False

        if not is_down:
            return False

        if name in BLOCKED_SPECIAL_KEYS:
            return False

        if self._left_alt_down:
            return False

        if self._held_ctrls and not self._altgr_down:
            if name == "backspace":
                self._key_queue.put(("CLEAR", None))
            return False

        if name == "enter":
            self._key_queue.put(("ENTER", None))
        elif name == "backspace":
            self._key_queue.put(("BACKSPACE", None))
        elif name == "esc":
            self._key_queue.put(("CLEAR", None))
        elif name == "space":
            self._key_queue.put(("CHAR", " "))
        else:
            self._key_queue.put(
                (
                    "KEY",
                    (
                        scan_code,
                        bool(event.is_keypad),
                        bool(self._held_shifts),
                        self._altgr_down,
                        self._caps_lock_on,
                        event.name,
                    ),
                )
            )
        return False

    def create_lock_screen(self):
        """Crea ventanas de bloqueo en TODOS los monitores detectados."""
        write_log("Creando pantallas de bloqueo multi-monitor.")
        monitors = get_monitors_info()
        primary_mon = next((m for m in monitors if m["is_primary"]), monitors[0])
        secondary_mons = [m for m in monitors if m != primary_mon]
        self._monitor_signature = tuple(
            (m["left"], m["top"], m["width"], m["height"]) for m in monitors
        )

        self._hide_and_clip_cursor(primary_mon)
        self._build_secondary_screens(secondary_mons)

        self.primary_lock_window = tk.Toplevel(self.root)
        lock_win = self.primary_lock_window
        lock_win.title("WinLock - Bloqueado")
        lock_win.overrideredirect(True)
        lock_win.geometry(
            f"{primary_mon['width']}x{primary_mon['height']}+{primary_mon['left']}+{primary_mon['top']}"
        )
        lock_win.attributes("-topmost", True)
        lock_win.config(cursor="none", bg="#1c1c1c")
        lock_win.protocol("WM_DELETE_WINDOW", lambda: None)

        self._install_window_shield(lock_win)

        tk.Label(
            lock_win,
            text=f"WinLock {LOCAL_VERSION} - LabDigital",
            font=("Segoe UI", 10),
            fg="#808080",
            bg="#1c1c1c",
            cursor="none",
        ).place(x=15, y=15, anchor="nw")

        tk.Label(
            lock_win,
            text="WinLock",
            font=("Segoe UI Black", 44),
            fg="white",
            bg="#1c1c1c",
            cursor="none",
        ).pack(pady=(55, 0))

        time_label = tk.Label(
            lock_win, font=("Segoe UI Light", 64), fg="white", bg="#1c1c1c", cursor="none"
        )
        time_label.pack(pady=(12, 0))

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
        duration_label.pack(pady=10)

        center_frame = tk.Frame(lock_win, bg="#1c1c1c", cursor="none")
        center_frame.pack(expand=True)

        tk.Label(
            center_frame,
            text="Contraseña:",
            font=("Segoe UI", 12),
            fg="#cccccc",
            bg="#1c1c1c",
            cursor="none",
        ).pack(pady=(10, 5))

        entry_frame = tk.Frame(
            center_frame,
            bg="#1c1c1c",
            highlightthickness=2,
            highlightbackground="#333333",
            cursor="none",
        )
        entry_frame.pack(pady=(0, 8))

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
        unlock_entry.pack(ipady=8)

        # Texto fijo y oculto mediante color de fondo para no desplazar ningún elemento
        caps_label = tk.Label(
            center_frame,
            text="Bloq Mayús activado",
            font=("Segoe UI", 9, "bold"),
            fg="#f0ad4e" if self._caps_lock_on else "#1c1c1c",
            bg="#1c1c1c",
            cursor="none",
        )
        caps_label.pack(pady=(0, 2))

        status_label = tk.Label(
            center_frame,
            text="",
            font=("Segoe UI", 11),
            fg="#ff3b30",
            bg="#1c1c1c",
            cursor="none",
        )
        status_label.pack(pady=4)

        if self.lock_message_optional:
            message_frame = tk.Frame(
                center_frame,
                bg="#252525",
                bd=1,
                relief="solid",
                padx=15,
                pady=10,
                cursor="none",
            )
            message_frame.pack(pady=(12, 0))
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
                wraplength=600,
                justify="center",
                cursor="none",
            ).pack(pady=(5, 0))

        bottom_frame = tk.Frame(lock_win, bg="#1c1c1c", cursor="none")
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
        tk.Label(
            bottom_frame,
            text="Este equipo está protegido con WinLock. Todos los intentos quedan registrados.",
            font=("Segoe UI", 10),
            fg="#808080",
            bg="#1c1c1c",
            cursor="none",
        ).pack()

        status_clear_job = {"id": None}

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
                rem = max(1, math.ceil(self.cooldown_until - now))
                status_label.config(
                    text=f"Demasiados intentos fallidos ({self.failed_attempts}). Espere {rem}s..."
                )
                return

            entered_pass = unlock_entry.get()
            if hmac.compare_digest(entered_pass, self.unlock_password):
                write_log(
                    f"Contraseña correcta. Desbloqueando (intentos fallidos: {self.failed_attempts})."
                )
                self._record_event("Contraseña correcta. Equipo desbloqueado.", level="ok")
                self._unlock_and_exit()
            else:
                self.failed_attempts += 1
                self.last_failed_time = datetime.now().strftime("%H:%M:%S")
                write_log(
                    f"Contraseña incorrecta introducida (intento #{self.failed_attempts})."
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
            """Procesa la cola de eventos de teclado en el hilo principal."""
            if not self._is_locked or not lock_win.winfo_exists():
                return
            try:
                while True:
                    kind, payload = self._key_queue.get_nowait()
                    if kind == "CAPS":
                        caps_label.config(
                            fg="#f0ad4e" if payload else "#1c1c1c"
                        )
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
            except queue.Empty:
                pass

            if self._is_locked and lock_win.winfo_exists():
                lock_win.after(20, process_key_queue)

        def update_time_and_duration():
            if not self._is_locked or not lock_win.winfo_exists():
                return
            time_label.config(text=time.strftime("%H:%M"))
            date_label.config(text=time.strftime("%A, %d de %B de %Y").capitalize())

            duration_label.config(
                text="Tiempo bloqueado: " + format_duration(time.time() - self.lock_start_time)
            )

            now = time.time()
            if now < self.cooldown_until:
                rem = max(1, math.ceil(self.cooldown_until - now))
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
                            "Cambio de configuración de monitores detectado. Ajustando pantallas."
                        )
                        self._record_event(
                            f"Cambio de monitores detectado ({len(mons)} pantalla(s) activa(s)).",
                            level="warn",
                        )
                        self._monitor_signature = sig
                        p_mon = next((m for m in mons if m["is_primary"]), mons[0])
                        s_mons = [m for m in mons if m != p_mon]
                        current_primary["mon"] = p_mon
                        lock_win.geometry(
                            f"{p_mon['width']}x{p_mon['height']}+{p_mon['left']}+{p_mon['top']}"
                        )
                        self._build_secondary_screens(s_mons)

                if not self._mouse_blocker.is_active:
                    self._mouse_blocker.start()
                    self._record_event(
                        "Bloqueo de ratón restaurado automáticamente.",
                        level="warn",
                        dedupe_key="mouse_repair",
                        dedupe_seconds=5.0,
                    )

                hide_taskbars()
                self._hide_and_clip_cursor(current_primary["mon"])

                primary_hwnd = (
                    user32.GetParent(lock_win.winfo_id()) or lock_win.winfo_id()
                )
                lock_hwnds = {primary_hwnd}
                for sw in self.secondary_screens:
                    if sw.winfo_exists():
                        lock_hwnds.add(user32.GetParent(sw.winfo_id()) or sw.winfo_id())

                fg = user32.GetForegroundWindow()
                if fg and fg not in lock_hwnds:
                    pid = ctypes.wintypes.DWORD(0)
                    user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
                    if pid.value:
                        try:
                            pname = psutil.Process(pid.value).name().lower()
                            if pname in MENU_OVERLAY_PROCESSES:
                                user32.ShowWindow(fg, SW_HIDE)
                                self._record_event(
                                    f"Menú emergente del sistema ocultado ({pname}).",
                                    level="warn",
                                    dedupe_key=f"overlay:{pname}",
                                    dedupe_seconds=3.0,
                                )
                        except (
                            psutil.NoSuchProcess,
                            psutil.AccessDenied,
                            psutil.ZombieProcess,
                        ):
                            pass

                for sw in self.secondary_screens:
                    force_window_topmost(sw)
                force_window_topmost(lock_win)
                user32.SetForegroundWindow(primary_hwnd)
            except Exception:
                pass

            if self._is_locked and lock_win.winfo_exists():
                lock_win.after(200, enforce_protection)

        keyboard.hook(self._on_raw_key_event, suppress=True)
        self._mouse_blocker.start()

        update_time_and_duration()
        process_key_queue()
        enforce_protection()

    def show_unlock_summary_popup(self, total_seconds, start_time_str, end_time_str):
        """Muestra una ventana emergente personalizada en Tkinter con el resumen del bloqueo."""
        try:
            with self._events_lock:
                events_copy = list(self.security_events)

            alert_count = sum(1 for _, lvl, _ in events_copy if lvl in ("alert", "warn"))
            has_incidents = self.failed_attempts > 0 or alert_count > 0

            popup = tk.Toplevel(self.root)
            popup.title(f"Resumen de sesión - WinLock {LOCAL_VERSION}")
            popup.geometry("560x500")
            popup.resizable(False, False)
            popup.configure(bg="#161616")

            try:
                popup.iconbitmap(resource_path("winlock.ico"))
            except Exception:
                pass

            self.center_window(popup)
            popup.attributes("-topmost", True)
            popup.after(250, lambda: popup.winfo_exists() and popup.attributes("-topmost", False))

            def close_popup(event=None):
                try:
                    if popup.winfo_exists():
                        popup.destroy()
                except Exception:
                    pass

            popup.protocol("WM_DELETE_WINDOW", close_popup)

            # Cabecera
            header = tk.Frame(popup, bg="#1f1f1f", padx=22, pady=16)
            header.pack(fill=tk.X)

            badge_color = "#ff4d4f" if self.failed_attempts > 0 else ("#f0ad4e" if alert_count > 0 else "#2ea043")
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
                padx=8,
                pady=3,
            ).pack(side=tk.RIGHT)

            tk.Label(
                header,
                text=f"Inicio: {start_time_str}   •   Desbloqueo: {end_time_str}",
                font=("Segoe UI", 9),
                fg="#a0a0a0",
                bg="#1f1f1f",
            ).pack(anchor="w", pady=(4, 0))

            # Tarjetas de estadísticas
            stats_frame = tk.Frame(popup, bg="#161616", padx=20, pady=14)
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
                    padx=12,
                    pady=10,
                )
                card.grid(row=0, column=col, sticky="nsew", padx=4)
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
                ).pack(anchor="w", pady=(2, 0))

            make_stat_card(0, "Tiempo total bloqueado", format_duration(total_seconds), "#4da6ff")
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

            # Lista de eventos ocurridos
            events_container = tk.Frame(popup, bg="#161616", padx=24)
            events_container.pack(fill=tk.BOTH, expand=True)

            tk.Label(
                events_container,
                text="Registro de eventos durante el bloqueo:",
                font=("Segoe UI", 10, "bold"),
                fg="#d9d9d9",
                bg="#161616",
            ).pack(anchor="w", pady=(0, 6))

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
                bd=8,
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
                events_text.insert(tk.END, f"{msg}\n", lvl if lvl in ("info", "warn", "alert", "ok") else "info")

            if self.last_failed_time:
                events_text.insert(
                    tk.END,
                    f"\nÚltimo intento fallido registrado a las {self.last_failed_time}.\n",
                    "alert",
                )

            events_text.see(tk.END)
            events_text.config(state="disabled")

            # Botones inferiores
            footer = tk.Frame(popup, bg="#161616", padx=24, pady=16)
            footer.pack(fill=tk.X)

            def open_logs_folder():
                try:
                    os.startfile(LOG_DIRECTORY)
                except Exception as ex:
                    write_log(f"No se pudo abrir carpeta de logs: {ex}")

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
                padx=12,
                pady=6,
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
                padx=20,
                pady=6,
                cursor="hand2",
            )
            close_btn.pack(side=tk.RIGHT)

            popup.bind("<Return>", close_popup)
            popup.bind("<Escape>", close_popup)
            popup.grab_set()
            popup.lift()
            popup.focus_force()
            close_btn.focus_set()

            self.root.wait_window(popup)
        except Exception as e:
            write_log(f"Error mostrando popup de resumen: {e}")

    def _unlock_and_exit(self):
        """Desbloquea el sistema, restaura todas las políticas y muestra el resumen."""
        self._is_locked = False
        self.unlock_password = ""
        total_seconds = time.time() - self.lock_start_time
        end_time_str = datetime.now().strftime("%H:%M:%S")
        start_time_str = self.lock_start_dt or end_time_str

        try:
            keyboard.unhook_all()
        except Exception:
            pass

        self._mouse_blocker.stop()
        self.stop_watchdog()
        self._remove_window_shield()
        SystemGuard.restore()
        restore_taskbars()
        self._show_system_cursor()

        try:
            kernel32.SetThreadExecutionState(0x80000000)
        except Exception:
            pass

        if self.primary_lock_window:
            try:
                self.primary_lock_window.destroy()
            except Exception:
                pass
            self.primary_lock_window = None

        for sw in self.secondary_screens:
            try:
                sw.destroy()
            except Exception:
                pass
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

        try:
            keyboard.unhook_all()
        except Exception:
            pass

        self._mouse_blocker.stop()
        self.stop_watchdog()
        self._remove_window_shield()
        SystemGuard.restore()
        restore_taskbars()
        self._show_system_cursor()

        for sw in self.secondary_screens:
            try:
                if sw.winfo_exists():
                    sw.destroy()
            except Exception:
                pass
        self.secondary_screens = []

        if self.primary_lock_window:
            try:
                if self.primary_lock_window.winfo_exists():
                    self.primary_lock_window.destroy()
            except Exception:
                pass
            self.primary_lock_window = None

        try:
            if hasattr(self, "root") and self.root.winfo_exists():
                self.root.quit()
                self.root.destroy()
        except Exception:
            pass

        try:
            kernel32.SetThreadExecutionState(0x80000000)
        except Exception:
            pass


# ==============================================================================
# SISTEMA DE AUTOACTUALIZACIÓN IN-PLACE (ROBUSTO, RESILIENTE Y EFICIENTE)
# ==============================================================================

def _build_clean_subprocess_env():
    """Devuelve el entorno del proceso limpiando variables heredadas de PyInstaller."""
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
    ):
        env.pop(var, None)
    return env


def _collect_self_pids(target_exe):
    """
    Devuelve nuestro PID y, en ejecutables PyInstaller --onefile,
    también el PID del bootloader padre que mantiene el bloqueo del .exe.
    """
    pids = [os.getpid()]
    try:
        norm_target = os.path.normcase(os.path.abspath(target_exe))
        cur_proc = psutil.Process(os.getpid())
        parent = cur_proc.parent()
        if parent and parent.pid not in pids:
            try:
                parent_exe = os.path.normcase(os.path.abspath(parent.exe()))
                if parent_exe == norm_target:
                    pids.append(parent.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    except Exception:
        pass
    return pids


def cleanup_update_staging_dir(dir_path, delay_seconds=1.5):
    """Elimina de forma segura la carpeta temporal de actualización en %TEMP%."""
    if not dir_path:
        return
    try:
        temp_root = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
        target = os.path.abspath(dir_path)
        norm_target = os.path.normcase(target)
        base = os.path.basename(target)
        if not norm_target.startswith(temp_root + os.sep):
            return
        if not base.startswith(UPDATE_STAGING_PREFIX):
            return
    except Exception:
        return

    def _worker():
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        for _ in range(5):
            if not os.path.exists(target):
                return
            try:
                shutil.rmtree(target, ignore_errors=False)
                write_log(f"Carpeta temporal de actualización limpiada: {target}")
                return
            except Exception:
                time.sleep(0.5)
        shutil.rmtree(target, ignore_errors=True)

    threading.Thread(target=_worker, daemon=True).start()


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
            raise ValueError("El archivo descargado no es un ejecutable Windows válido (cabecera MZ).")
        pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
        if pe_offset < 64 or pe_offset > actual_size - 4:
            raise ValueError("Cabecera PE fuera de rango (archivo corrupto).")
        f.seek(pe_offset)
        if f.read(4) != b"PE\x00\x00":
            raise ValueError("Firma PE inválida (posible página de error en lugar de .exe).")

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
        if not hmac.compare_digest(actual_hex, expected_hex):
            raise ValueError("La verificación de integridad SHA-256 no coincide.")

    # Eliminar Mark-of-the-Web si existiera
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
    Devuelve (bytes_descargados, content_length_del_servidor).
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
                    m = re.search(r"/(\d+)$", content_range)
                    if m:
                        expected_total = int(m.group(1))
                    elif content_len_hdr and content_len_hdr.isdigit():
                        expected_total = resume_from + int(content_len_hdr)
                    file_mode = "ab"
                    downloaded = resume_from
                else:
                    if content_len_hdr and content_len_hdr.isdigit():
                        expected_total = int(content_len_hdr)
                    file_mode = "wb"
                    downloaded = 0

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
                return downloaded, expected_total

        except InterruptedError:
            raise
        except urllib.error.HTTPError as http_err:
            # Si Range no es aceptado (416), reiniciar desde 0
            if http_err.code == 416 and os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
            last_error = http_err
            write_log(f"Error HTTP en intento {attempt}/{max_retries}: {http_err}")
        except Exception as err:
            last_error = err
            write_log(f"Error de red en intento {attempt}/{max_retries}: {err}")

        if attempt < max_retries:
            backoff = 1.0 * attempt
            end_wait = time.monotonic() + backoff
            while time.monotonic() < end_wait:
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("Descarga cancelada por el usuario.")
                time.sleep(0.1)

    raise RuntimeError(f"No se pudo completar la descarga: {last_error}")


def _launch_cmd_updater_fallback(target_exe, new_exe, backup_exe, staging_dir, wait_pids):
    """
    Plan B puro en cmd.exe si PowerShell no estuviera disponible en el equipo.
    Usa 'copy /b /y' que sobrescribe in-place sin eliminar el archivo ni perder su sitio en el Escritorio.
    """
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
    """
    Lanza el actualizador independiente que:
      1. Espera a que termine WinLock (y su bootloader PyInstaller).
      2. Guarda copia de seguridad en %TEMP% (nunca ensucia el Escritorio).
      3. Sobrescribe el .exe IN-PLACE (mantiene nombre exacto, posición en el Escritorio,
         atributos y fecha de creación).
      4. Solicita elevación UAC automáticamente solo si el directorio está protegido (ej. Program Files).
      5. Hace rollback automático si falla la escritura o el relanzamiento.
      6. Relanza el .exe actualizado con el entorno limpio.
    """
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
            # FileMode.Open preserva la entrada de directorio, nombre exacto y posición del icono en el Escritorio
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

function Clear-PyInstallerEnv {
    foreach ($v in @(
        "_MEIPASS", "_MEIPASS2", "_PYI_APPLICATION_HOME_DIR",
        "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL",
        "_PYI_SPLASH_IPC", "TCL_LIBRARY", "TK_LIBRARY"
    )) {
        [Environment]::SetEnvironmentVariable($v, $null, "Process")
    }
}

function Start-TargetApp {
    param([bool]$PassUpdatedArgs)
    Clear-PyInstallerEnv
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

# 1. Esperar cierre limpio de WinLock (y su bootloader PyInstaller si es --onefile)
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

# 2. Guardar metadatos y respaldo en %TEMP% (nunca crear archivos en el Escritorio)
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

# 3. Sobrescritura estrictamente IN-PLACE con reintentos (OneDrive/Defender/desmontaje de imagen)
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

# 4. Si la carpeta esta protegida (ej. Program Files), elevar via UAC automaticamente
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

# 5. Rollback automatico si fallo el reemplazo
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

# 6. Restaurar fecha de creacion y atributos originales
if ($null -ne $origCreationUtc) {
    try { [System.IO.File]::SetCreationTimeUtc($targetExe, $origCreationUtc) } catch {}
}
if ($null -ne $origAttributes) {
    try { [System.IO.File]::SetAttributes($targetExe, $origAttributes) } catch {}
}
try { Unblock-File -LiteralPath $targetExe -ErrorAction SilentlyContinue } catch {}

Write-UpdateLog "Actualizacion in-place completada ($expectedLen bytes). Relanzando '$targetExe'."

# 7. Relanzar la nueva version (con rollback si fallara el arranque)
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

    # UTF-8 con BOM para compatibilidad total con tildes y rutas Unicode en PowerShell 5.1
    with open(ps_path, "w", encoding="utf-8-sig") as f:
        f.write(ps_script)

    # Liberar el mutex antes de lanzar el actualizador para evitar bloqueo en el reinicio
    release_single_instance_mutex()

    ps_exe = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"),
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )
    if not os.path.isfile(ps_exe):
        ps_exe = shutil.which("powershell.exe") or shutil.which("pwsh.exe")

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
            write_log(f"Actualizador PowerShell iniciado (PIDs monitorizados: {wait_pids}).")
            return
        except Exception as ps_err:
            write_log(f"No se pudo iniciar PowerShell ({ps_err}); usando fallback cmd.exe.")

    _launch_cmd_updater_fallback(target_exe, new_exe, backup_exe, staging_dir, wait_pids)
    write_log(f"Actualizador cmd.exe fallback iniciado (PIDs monitorizados: {wait_pids}).")


def show_startup_and_check_updates():
    """
    Muestra una ventana de carga mientras comprueba actualizaciones en segundo plano.
    Al pulsar 'Actualizar', descarga, verifica e instala in-place sin ir a la web.
    Devuelve True si se inició una actualización y el programa debe salir.
    """
    splash = tk.Tk()
    splash.title("WinLock")
    splash.resizable(False, False)

    try:
        splash.iconbitmap(resource_path("winlock.ico"))
    except Exception:
        pass

    def resize_and_center(min_w=430, min_h=175):
        splash.update_idletasks()
        w = max(min_w, splash.winfo_reqwidth())
        h = max(min_h, splash.winfo_reqheight())
        x = (splash.winfo_screenwidth() // 2) - (w // 2)
        y = (splash.winfo_screenheight() // 2) - (h // 2)
        splash.geometry(f"{w}x{h}+{x}+{y}")

    style = ttk.Style(splash)
    style.theme_use("clam")
    style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"))

    container = ttk.Frame(splash, padding="20 18 20 18")
    container.pack(expand=True, fill=tk.BOTH)

    title_label = ttk.Label(
        container,
        text=f"Iniciando WinLock {LOCAL_VERSION}...",
        font=("Segoe UI", 12, "bold"),
    )
    title_label.pack(anchor="w")

    status_label = ttk.Label(
        container,
        text="Comprobando actualizaciones...",
        font=("Segoe UI", 9),
        foreground="#555555",
    )
    status_label.pack(anchor="w", pady=(5, 10))

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
            try:
                shutil.rmtree(sdir, ignore_errors=True)
            except Exception:
                pass

    def close_splash():
        state["closed"] = True
        state["cancel_event"].set()
        cleanup_current_staging()
        try:
            if splash.winfo_exists():
                splash.destroy()
        except Exception:
            pass

    splash.protocol("WM_DELETE_WINDOW", close_splash)

    def check_network():
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
        except Exception as err:
            write_log(f"Error comprobando actualizaciones: {err}")
            state["result"] = None
        finally:
            state["done"] = True

    threading.Thread(target=check_network, daemon=True).start()

    def clear_container():
        for w in container.winfo_children():
            w.destroy()

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
            wraplength=390,
            justify="left",
        ).pack(anchor="w", pady=(6, 12))

        btn_row = ttk.Frame(container)
        btn_row.pack(fill=tk.X)

        def open_manual_site():
            webbrowser.open(UPDATE_URL)
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
        ).pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Button(
            btn_row,
            text="Continuar",
            command=close_splash,
        ).pack(side=tk.RIGHT)

        resize_and_center(435, 175)

    def start_autoupdate(latest_info):
        if state["closed"] or not splash.winfo_exists():
            return

        is_frozen = bool(getattr(sys, "frozen", False))
        remote_tag = str(latest_info.get("tag_name") or "").strip()
        dl_url = str(latest_info.get("download_url") or "").strip()
        declared_size_bytes = parse_human_size(latest_info.get("size"))
        expected_sha256 = latest_info.get("sha256")

        if is_frozen:
            target_exe = os.path.abspath(sys.executable)
        else:
            # En modo desarrollo (.py) nunca sobrescribir python.exe: descargar WinLock.exe en la carpeta del script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            target_exe = os.path.join(script_dir, "WinLock.exe")

        # Comprobar espacio libre antes de descargar
        try:
            temp_root = tempfile.gettempdir()
            needed_bytes = max(30 * 1024 * 1024, int(declared_size_bytes * 2.5))
            if shutil.disk_usage(temp_root).free < needed_bytes:
                show_error_view(
                    latest_info,
                    "No hay suficiente espacio libre en la unidad temporal para descargar la actualización.",
                )
                return
        except Exception:
            pass

        state["cancel_event"] = threading.Event()
        cancel_ev = state["cancel_event"]

        clear_container()

        heading = ttk.Label(
            container,
            text=f"Actualizando a WinLock {remote_tag}...",
            font=("Segoe UI", 11, "bold"),
        )
        heading.pack(anchor="w")

        pb = ttk.Progressbar(
            container,
            orient="horizontal",
            mode="indeterminate" if not declared_size_bytes else "determinate",
            maximum=100,
        )
        pb.pack(fill=tk.X, pady=(10, 6))
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
        footer.pack(fill=tk.X, pady=(10, 0))

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
                cleanup_current_staging()
                return
            try:
                cancel_btn.config(state="disabled")
                update_ui(100, "Instalando y reiniciando WinLock...")
                splash.update_idletasks()

                if is_frozen:
                    state["updating"] = True
                    launch_inplace_updater(
                        target_exe=target_exe,
                        new_exe=new_exe,
                        staging_dir=staging_dir,
                        target_version=remote_tag,
                    )
                    close_splash()
                else:
                    # Modo .py: guardar el ejecutable validado sin tocar python.exe
                    shutil.copy2(new_exe, target_exe)
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
                write_log(f"Error lanzando instalador in-place: {inst_err}")
                show_error_view(
                    latest_info,
                    f"La descarga se completó, pero no se pudo aplicar la actualización:\n{inst_err}",
                )

        def download_worker():
            staging_dir = os.path.join(
                tempfile.gettempdir(),
                f"{UPDATE_STAGING_PREFIX}{uuid.uuid4().hex[:10]}",
            )
            state["staging_dir"] = staging_dir
            try:
                os.makedirs(staging_dir, exist_ok=True)
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
                    return

                splash.after(0, update_ui, 100, "Verificando integridad del ejecutable...")
                validate_pe_executable(
                    file_path=staged_exe,
                    expected_content_length=server_len,
                    declared_size_bytes=declared_size_bytes,
                    expected_sha256=expected_sha256,
                )

                if cancel_ev.is_set() or state["closed"]:
                    return

                splash.after(0, finalize_install, staged_exe, staging_dir)

            except InterruptedError:
                write_log("Autoactualización cancelada por el usuario.")
                cleanup_current_staging()
            except Exception as ex:
                write_log(f"Error durante la autoactualización: {ex}")
                if not state["closed"] and not cancel_ev.is_set():
                    splash.after(
                        0,
                        show_error_view,
                        latest_info,
                        f"Ocurrió un error al descargar o verificar la actualización:\n{ex}",
                    )

        threading.Thread(target=download_worker, daemon=True).start()

    def prompt_update(latest_info):
        progress.stop()
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
            wraplength=390,
            justify="left",
        ).pack(anchor="w", pady=(6, 14))

        btn_box = ttk.Frame(container)
        btn_box.pack(fill=tk.X)

        update_btn = ttk.Button(
            btn_box,
            text="Actualizar ahora",
            style="Primary.TButton",
            command=lambda: start_autoupdate(latest_info),
        )
        update_btn.pack(side=tk.RIGHT, padx=(6, 0))

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
        if state["done"]:
            info = state["result"]
            remote_tag = info.get("tag_name") if isinstance(info, dict) else None
            dl_url = info.get("download_url") if isinstance(info, dict) else None
            if (
                remote_tag
                and dl_url
                and str(dl_url).strip().lower().startswith("https://")
                and parse_version(remote_tag) > parse_version(LOCAL_VERSION)
            ):
                prompt_update(info)
            else:
                close_splash()
        else:
            splash.after(100, monitor_progress)

    splash.after(100, monitor_progress)
    splash.mainloop()
    return state["updating"]


def full_emergency_restore(explicit_restore=False):
    """
    Restaura políticas, botones de energía, barras de tareas, explorer y cursor.
    Si explicit_restore=True (--restore), realiza limpieza segura incluso sin
    archivo de respaldo o sin permisos de Administrador.
    """
    try:
        SystemGuard.restore(force_fallback=explicit_restore)
    except Exception as e:
        write_log(f"Aviso en SystemGuard.restore: {e}")

    try:
        restore_taskbars()
    except Exception as e:
        write_log(f"Aviso restaurando barras de tareas: {e}")

    if explicit_restore:
        start_explorer_if_not_running()

    try:
        WinLock._show_system_cursor()
    except Exception as e:
        write_log(f"Aviso restaurando cursor: {e}")

    try:
        kernel32.SetThreadExecutionState(0x80000000)
    except Exception:
        pass

    try:
        keyboard.unhook_all()
    except Exception:
        pass


if __name__ == "__main__":
    # Limpieza silenciosa de la carpeta temporal tras completar una autoactualización
    if "--cleanup-update" in sys.argv:
        try:
            idx = sys.argv.index("--cleanup-update")
            if idx + 1 < len(sys.argv):
                cleanup_update_staging_dir(sys.argv[idx + 1], delay_seconds=1.5)
        except Exception:
            pass

    just_updated = "--updated" in sys.argv

    # Modo silencioso de recuperación tras corte eléctrico, fallo o ejecución manual
    if "--restore" in sys.argv:
        write_log(
            f"Ejecutando recuperación robusta (--restore, admin={is_admin()})."
        )
        full_emergency_restore(explicit_restore=True)
        sys.exit(0)

    # Si quedó un estado pendiente de una sesión interrumpida, restaurar primero
    if os.path.exists(RESTORE_STATE_PATH):
        write_log("Detectado estado pendiente de sesión anterior. Restaurando sistema.")
        full_emergency_restore(explicit_restore=True)

    atexit.register(full_emergency_restore)

    # Si venimos de reiniciar tras actualizar, dar un margen breve para que termine el proceso anterior
    mutex_handle, is_first_instance = acquire_single_instance_mutex(
        retries=25 if just_updated else 0,
        retry_delay=0.15,
    )
    if not is_first_instance:
        _r = tk.Tk()
        _r.withdraw()
        messagebox.showinfo("WinLock", "WinLock ya se está ejecutando.")
        _r.destroy()
        sys.exit(0)

    write_log(
        f"\n{'='*50}\nIniciando sesión de WinLock {LOCAL_VERSION}"
        + (" (recién actualizado)" if just_updated else "")
    )

    # Si acaba de actualizarse, evitar comprobación redundante y posibles bucles de versión
    if not just_updated and show_startup_and_check_updates():
        release_single_instance_mutex()
        sys.exit(0)

    app_instance = None
    try:
        root = tk.Tk()
        app_instance = WinLock(root)
        root.mainloop()
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        write_log(f"Error general en hilo principal: {e}")
    finally:
        if app_instance:
            app_instance._quit_app()
        else:
            full_emergency_restore()
        release_single_instance_mutex()
        sys.exit(0)
