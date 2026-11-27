LOCAL_VERSION = "v0.8"

import sys

try:
    import psutil
    import subprocess
    import tkinter as tk
    from tkinter import ttk, messagebox
    import time
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
    import webbrowser
    import locale
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
    """Convierte versiones como 'v0.8' en tuplas comparables (0, 8)."""
    try:
        cleaned = str(version_str).strip().lstrip("vV")
        parts = [int(p) for p in cleaned.split(".") if p.isdigit()]
        return tuple(parts) if parts else (0,)
    except Exception:
        return (0,)


def get_app_data_dir():
    """Obtiene la carpeta de datos de WinLock."""
    try:
        app_data_path = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(app_data_path, LOG_FOLDER_NAME)
    except Exception:
        return os.path.abspath(".")


LOG_DIRECTORY = get_app_data_dir()
LOG_FILE_PATH = os.path.join(LOG_DIRECTORY, LOG_FILE_NAME)
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


def acquire_single_instance_mutex():
    """Evita múltiples instancias simultáneas de WinLock."""
    handle = kernel32.CreateMutexW(None, False, "Local\\WinLock_SingleInstance_Mutex")
    if not handle:
        return None, True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return handle, False
    return handle, True


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
            powrprof.PowerSetActiveScheme(None, ctypes.byref(scheme_guid))
            write_log("Botones de energía restaurados a su configuración original.")
        except Exception as e:
            write_log(f"Error restaurando botones de energía: {e}")

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
                    # HKLM sin permisos de administrador: omitir sin fallar
                    continue
                except Exception as e:
                    write_log(f"Aviso leyendo política {hive_name}\\{subkey}\\{value_name}: {e}")

            power_backup = cls._snapshot_and_apply_power_buttons()

            state_payload = {
                "registry": reg_backups,
                "power": power_backup,
            }

            # Guardar respaldo en disco ANTES de escribir las políticas restrictivas
            try:
                tmp_path = RESTORE_STATE_PATH + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(state_payload, f, indent=2)
                os.replace(tmp_path, RESTORE_STATE_PATH)
            except Exception as e:
                write_log(f"Error guardando estado de recuperación: {e}")

            cls._set_runonce_recovery(True)

            # Aplicar políticas de bloqueo
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
    def restore(cls):
        """Restaura exactamente el registro y los botones de energía previos."""
        with cls._lock:
            state_payload = None
            if os.path.exists(RESTORE_STATE_PATH):
                try:
                    with open(RESTORE_STATE_PATH, "r", encoding="utf-8") as f:
                        state_payload = json.load(f)
                except Exception as e:
                    write_log(f"Error leyendo estado de recuperación: {e}")

            if state_payload:
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
                write_log("SystemGuard restaurado por completo.")

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
        self.failed_attempts = 0
        self.last_failed_time = None
        self.cooldown_until = 0.0

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

    def center_window(self, win):
        """Centra una ventana de tkinter en la pantalla principal."""
        win.update_idletasks()
        width = win.winfo_width()
        height = win.winfo_height()
        x = (win.winfo_screenwidth() // 2) - (width // 2)
        y = (win.winfo_screenheight() // 2) - (height // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")

    def create_setup_window(self):
        """Crea la ventana inicial con contraseña siempre visible y sin repetición."""
        write_log("Creando la ventana de configuración de contraseña.")
        if self.setup_frame:
            self.setup_frame.destroy()

        self.setup_frame = ttk.Frame(self.root, padding="20 18 20 18")
        self.setup_frame.pack(expand=True, fill=tk.BOTH)

        font_style = ("Segoe UI", 10)

        ttk.Label(self.setup_frame, text="Contraseña:", font=font_style).pack(anchor="w")
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

            # Notificar primero a WinLock si Windows intenta apagar, antes de cerrar otras apps
            kernel32.SetProcessShutdownParameters(0x3FF, 0)
            user32.ShutdownBlockReasonCreate(
                hwnd,
                "WinLock: Este equipo está bloqueado. Desbloquee antes de apagar o reiniciar.",
            )

            def _shield_wndproc(h, msg, wParam, lParam):
                if self._is_locked:
                    if msg == WM_QUERYENDSESSION:
                        write_log("Intento de apagado/cierre de sesión interceptado y bloqueado.")
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
        self.failed_attempts = 0
        self.last_failed_time = None
        self.cooldown_until = 0.0
        self._caps_lock_on = bool(user32.GetKeyState(0x14) & 1)

        self._snapshot_preexisting_processes()
        SystemGuard.engage()
        hide_taskbars()
        self.start_watchdog()

        try:
            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED | ES_AWAYMODE_REQUIRED
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

        if name == "caps lock":
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

        # Pantalla principal interactiva
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

        caps_label = tk.Label(
            center_frame,
            text="Bloq Mayús activado" if self._caps_lock_on else "",
            font=("Segoe UI", 9, "bold"),
            fg="#f0ad4e",
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
                rem = int(self.cooldown_until - now) + 1
                status_label.config(
                    text=f"Demasiados intentos fallidos. Espere {rem}s..."
                )
                return

            entered_pass = unlock_entry.get()
            if hmac.compare_digest(entered_pass, self.unlock_password):
                write_log(
                    f"Contraseña correcta. Desbloqueando (intentos fallidos: {self.failed_attempts})."
                )
                self._unlock_and_exit()
            else:
                self.failed_attempts += 1
                self.last_failed_time = datetime.now().strftime("%H:%M:%S")
                write_log(
                    f"Contraseña incorrecta introducida (intento #{self.failed_attempts})."
                )
                set_entry_text("clear")
                flash_error_border()

                if self.failed_attempts >= 11:
                    delay = 30
                elif self.failed_attempts >= 8:
                    delay = 15
                elif self.failed_attempts >= 5:
                    delay = 5
                else:
                    delay = 0

                if delay > 0:
                    self.cooldown_until = time.time() + delay
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
                            text="Bloq Mayús activado" if payload else ""
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

            delta = int(time.time() - self.lock_start_time)
            d, r = divmod(delta, 86400)
            h, r = divmod(r, 3600)
            m, s = divmod(r, 60)
            parts = (
                (f"{d}d " if d else "")
                + (f"{h}h " if h else "")
                + (f"{m}m " if m else "")
                + f"{s}s"
            )
            duration_label.config(text="Tiempo bloqueado: " + parts)

            now = time.time()
            if now < self.cooldown_until:
                rem = int(self.cooldown_until - now) + 1
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
                        self._monitor_signature = sig
                        p_mon = next((m for m in mons if m["is_primary"]), mons[0])
                        s_mons = [m for m in mons if m != p_mon]
                        current_primary["mon"] = p_mon
                        lock_win.geometry(
                            f"{p_mon['width']}x{p_mon['height']}+{p_mon['left']}+{p_mon['top']}"
                        )
                        self._build_secondary_screens(s_mons)

                # Autorreparación del bloqueo de ratón si se interrumpió
                if not self._mouse_blocker.is_active:
                    self._mouse_blocker.start()

                hide_taskbars()
                self._hide_and_clip_cursor(current_primary["mon"])

                primary_hwnd = (
                    user32.GetParent(lock_win.winfo_id()) or lock_win.winfo_id()
                )
                lock_hwnds = {primary_hwnd}
                for sw in self.secondary_screens:
                    if sw.winfo_exists():
                        lock_hwnds.add(user32.GetParent(sw.winfo_id()) or sw.winfo_id())

                # Ocultar al instante Menú Inicio / Búsqueda / Centro de acciones si roban foco
                fg = user32.GetForegroundWindow()
                if fg and fg not in lock_hwnds:
                    pid = ctypes.wintypes.DWORD(0)
                    user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
                    if pid.value:
                        try:
                            pname = psutil.Process(pid.value).name().lower()
                            if pname in MENU_OVERLAY_PROCESSES:
                                user32.ShowWindow(fg, SW_HIDE)
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

    def _unlock_and_exit(self):
        """Desbloquea el sistema, restaura todas las políticas e informa intentos fallidos."""
        self._is_locked = False
        self.unlock_password = ""

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

        if self.failed_attempts > 0:
            try:
                self.root.attributes("-topmost", True)
                messagebox.showwarning(
                    "Alerta de seguridad - WinLock",
                    f"Se registraron {self.failed_attempts} intento(s) fallido(s) de desbloqueo "
                    f"mientras no estabas.\nÚltimo intento: {self.last_failed_time}",
                    parent=self.root,
                )
            except Exception:
                pass

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


def show_startup_and_check_updates():
    """
    Muestra una ventana de carga mientras comprueba actualizaciones en segundo plano.
    Devuelve True si se inició una actualización y el programa debe salir.
    """
    splash = tk.Tk()
    splash.title("WinLock")
    splash.geometry("390x170")
    splash.resizable(False, False)

    try:
        splash.iconbitmap(resource_path("winlock.ico"))
    except Exception:
        pass

    splash.update_idletasks()
    x = (splash.winfo_screenwidth() // 2) - (390 // 2)
    y = (splash.winfo_screenheight() // 2) - (170 // 2)
    splash.geometry(f"390x170+{x}+{y}")

    style = ttk.Style(splash)
    style.theme_use("clam")

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
        foreground="#666",
    )
    status_label.pack(anchor="w", pady=(5, 10))

    progress = ttk.Progressbar(container, orient="horizontal", mode="indeterminate")
    progress.pack(fill=tk.X)
    progress.start(12)

    state = {"result": None, "done": False, "closed": False, "updating": False}

    def close_splash():
        state["closed"] = True
        try:
            if splash.winfo_exists():
                splash.destroy()
        except Exception:
            pass

    splash.protocol("WM_DELETE_WINDOW", close_splash)

    def check_network():
        try:
            req = urllib.request.Request(
                LATEST_VERSION_JSON, headers={"User-Agent": "WinLock Updater"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                state["result"] = json.loads(response.read().decode("utf-8"))
        except Exception as err:
            write_log(f"Error comprobando actualizaciones: {err}")
            state["result"] = None
        finally:
            state["done"] = True

    threading.Thread(target=check_network, daemon=True).start()

    def run_finalizer_script(old_exe, new_exe, script_path):
        esc_old = old_exe.replace("'", "''")
        esc_new = new_exe.replace("'", "''")
        esc_script = script_path.replace("'", "''")
        exe_name = os.path.basename(old_exe)

        ps_script = f"""
param()
taskkill /f /im "{exe_name}" 2>$null
$maxRetries = 10
for ($i=0; $i -lt $maxRetries; $i++) {{
    try {{
        Remove-Item -LiteralPath '{esc_old}' -Force -ErrorAction Stop
        break
    }} catch {{
        Start-Sleep -Seconds 1
    }}
}}
Move-Item -LiteralPath '{esc_new}' -Destination '{esc_old}' -Force -ErrorAction SilentlyContinue
Start-Process -FilePath '{esc_old}'
Start-Sleep -Seconds 1
Remove-Item -LiteralPath '{esc_script}' -Force -ErrorAction SilentlyContinue
"""
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(ps_script)

        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                script_path,
            ],
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        )

    def prompt_update(latest_info):
        progress.stop()
        progress.destroy()
        remote_tag = latest_info.get("tag_name")
        title_label.config(text="¡Actualización disponible!")
        status_label.config(
            text=f"Versión actual: {LOCAL_VERSION}  →  Disponible: {remote_tag}\n¿Desea actualizar ahora?"
        )

        btn_box = ttk.Frame(container)
        btn_box.pack(fill=tk.X, pady=(10, 0))

        def proceed_download():
            if not getattr(sys, "frozen", False):
                webbrowser.open(UPDATE_URL)
                close_splash()
                return

            for w in container.winfo_children():
                w.destroy()

            ttk.Label(
                container,
                text="Descargando actualización...",
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w")
            pb = ttk.Progressbar(container, orient="horizontal", mode="determinate")
            pb.pack(fill=tk.X, pady=(10, 5))
            st = ttk.Label(container, text="Conectando...", font=("Segoe UI", 8))
            st.pack(anchor="w")

            def update_ui(pct, text):
                if not state["closed"] and splash.winfo_exists():
                    pb["value"] = pct
                    st.config(text=text)

            def finish_install(new_exe, ps_path):
                if state["closed"]:
                    return
                state["updating"] = True
                run_finalizer_script(os.path.abspath(sys.executable), new_exe, ps_path)
                close_splash()

            def download_thread():
                try:
                    temp_dir = os.environ.get("TEMP", ".")
                    new_exe = os.path.join(
                        temp_dir, f"winlock_new_{random.randint(1000, 9999)}.exe"
                    )
                    ps_path = os.path.join(
                        temp_dir, f"updater_{random.randint(1000, 9999)}.ps1"
                    )

                    def reporthook(blocks, block_size, total):
                        if state["closed"]:
                            raise InterruptedError("Descarga cancelada por el usuario")
                        if total > 0:
                            done = min(blocks * block_size, total)
                            pct = int(done * 100 / total)
                            txt = f"{done / 1048576:.1f} MB / {total / 1048576:.1f} MB ({pct}%)"
                            splash.after(0, update_ui, pct, txt)

                    urllib.request.urlretrieve(
                        latest_info["download_url"], new_exe, reporthook
                    )
                    splash.after(0, update_ui, 100, "Instalando y reiniciando...")
                    time.sleep(0.5)
                    splash.after(0, finish_install, new_exe, ps_path)
                except Exception as ex:
                    write_log(f"Error descargando actualización: {ex}")
                    splash.after(0, close_splash)

            threading.Thread(target=download_thread, daemon=True).start()

        ttk.Button(btn_box, text="Actualizar", command=proceed_download).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(btn_box, text="Más tarde", command=close_splash).pack(side=tk.RIGHT)

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
                and str(dl_url).startswith("https://")
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


def full_emergency_restore():
    """Restaura políticas, botones de energía, barras de tareas y cursor."""
    SystemGuard.restore()
    restore_taskbars()
    WinLock._show_system_cursor()
    try:
        kernel32.SetThreadExecutionState(0x80000000)
    except Exception:
        pass
    try:
        keyboard.unhook_all()
    except Exception:
        pass


if __name__ == "__main__":
    # Modo silencioso de recuperación tras corte eléctrico o cierre inesperado
    if "--restore" in sys.argv:
        write_log("Ejecutando recuperación automática (--restore).")
        full_emergency_restore()
        sys.exit(0)

    # Si quedó un estado pendiente de una sesión interrumpida, restaurar primero
    if os.path.exists(RESTORE_STATE_PATH):
        write_log("Detectado estado pendiente de sesión anterior. Restaurando sistema.")
        full_emergency_restore()

    atexit.register(full_emergency_restore)

    mutex_handle, is_first_instance = acquire_single_instance_mutex()
    if not is_first_instance:
        _r = tk.Tk()
        _r.withdraw()
        messagebox.showinfo("WinLock", "WinLock ya se está ejecutando.")
        _r.destroy()
        sys.exit(0)

    write_log(f"\n{'='*50}\nIniciando sesión de WinLock {LOCAL_VERSION}")

    if show_startup_and_check_updates():
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
        sys.exit(0)