LOCAL_VERSION = "v0.7"

try:
    import psutil
    import subprocess
    import tkinter as tk
    from tkinter import ttk, messagebox
    import time
    import random
    import sys
    import ctypes
    import ctypes.wintypes
    import keyboard
    import os
    import threading
    import json
    import urllib.request
    import locale
    from datetime import datetime
except ImportError as e:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Instalación fallida - WinLock",
        "Faltan bibliotecas necesarias. Reinstala la aplicación.",
    )
    print(e)
    sys.exit(1)

# Windows DPI Awareness to ensure exact multi-monitor pixel coordinate mapping
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.WinDLL("user32", use_last_error=True)

CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
LOG_FOLDER_NAME = "WinLock"
LOG_FILE_NAME = f"logs-{datetime.now().strftime('%d_%m_%Y-%H_%M_%S')}.txt"
LATEST_VERSION_JSON = (
    "https://raw.githubusercontent.com/enderhacker/WinLock/refs/heads/main/version.json"
)
UPDATE_URL = "https://winlock.labdigital.es"


def get_log_path():
    """Obtiene la ruta para el archivo de logs."""
    try:
        app_data_path = os.environ.get("APPDATA") or os.path.expanduser("~")
        log_dir = os.path.join(app_data_path, LOG_FOLDER_NAME)
        return log_dir
    except Exception:
        return os.path.abspath(".")


LOG_DIRECTORY = get_log_path()
LOG_FILE_PATH = os.path.join(LOG_DIRECTORY, LOG_FILE_NAME)

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
    """Obtiene la ruta absoluta para recursos (funciona con PyInstaller)."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def start_explorer_if_not_running():
    """Verifica si explorer.exe se está ejecutando y lo inicia si no es así."""
    write_log("Revisando el estado de explorer.exe.")
    explorer_running = any(
        proc.name().lower() == "explorer.exe"
        for proc in psutil.process_iter(["name"])
    )
    if not explorer_running:
        write_log("explorer.exe no se estaba ejecutando. Intentando iniciarlo.")
        try:
            subprocess.Popen("explorer.exe")
            write_log("Comando para iniciar explorer.exe ejecutado.")
        except Exception as e:
            write_log(f"FALLO al intentar iniciar explorer.exe: {e}")
    else:
        write_log("Verificación completada: explorer.exe ya se está ejecutando.")


def get_monitors_info():
    """Obtiene las coordenadas geométricas reales de todos los monitores conectados."""
    monitors = []

    def _monitor_enum_callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        rect = lprcMonitor.contents
        monitors.append({
            "left": rect.left,
            "top": rect.top,
            "right": rect.right,
            "bottom": rect.bottom,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top,
            "is_primary": (rect.left == 0 and rect.top == 0)
        })
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
        # Fallback si falla el enum
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        monitors.append({
            "left": 0, "top": 0, "right": w, "bottom": h,
            "width": w, "height": h, "is_primary": True
        })
    return monitors


class WinLock:
    def __init__(self, root_window):
        write_log("Inicializando la aplicación WinLock.")
        self.root = root_window
        self.unlock_password = ""
        self.lock_message_optional = ""
        self.lock_start_time = 0
        self._watchdog_thread = None
        self._watchdog_running = False
        self.setup_frame = None
        self.secondary_screens = []
        self.primary_lock_window = None

        try:
            locale.setlocale(locale.LC_TIME, "es_ES.UTF-8")
        except locale.Error:
            try:
                locale.setlocale(locale.LC_TIME, "Spanish_Spain.1252")
            except locale.Error:
                pass

        self.root.title(f"WinLock {LOCAL_VERSION}")
        self.root.geometry("400x340")
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
        """Centra una ventana de tkinter en la pantalla."""
        win.update_idletasks()
        width = win.winfo_width()
        height = win.winfo_height()
        x = (win.winfo_screenwidth() // 2) - (width // 2)
        y = (win.winfo_screenheight() // 2) - (height // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")

    def create_setup_window(self):
        """Crea la ventana inicial para configurar la contraseña."""
        write_log("Creando la ventana de configuración de contraseña.")
        if self.setup_frame:
            self.setup_frame.destroy()

        self.setup_frame = ttk.Frame(self.root, padding="20 20 20 20")
        self.setup_frame.pack(expand=True, fill=tk.BOTH)

        font_style = ("Segoe UI", 10)

        ttk.Label(self.setup_frame, text="Contraseña:", font=font_style).pack(anchor="w")
        self.password_entry = ttk.Entry(self.setup_frame, show="•", width=35, font=font_style)
        self.password_entry.pack(fill=tk.X, pady=(2, 8), ipady=3)

        ttk.Label(self.setup_frame, text="Mensaje (opcional):", font=font_style).pack(anchor="w")
        self.message_text = tk.Text(
            self.setup_frame,
            height=8,
            width=35,
            wrap="word",
            font=font_style
        )
        self.message_text.pack(fill=tk.BOTH, pady=(2, 15))

        self.lock_button = ttk.Button(
            self.setup_frame,
            text="Bloquear",
            command=self.validate_and_confirm,
            style="Lock.TButton"
        )
        self.lock_button.pack(pady=0, ipady=0, fill=tk.X)

        self.root.lift()
        self.root.focus_force()
        self.password_entry.focus_set()
        self.root.bind("<Return>", lambda event: self.validate_and_confirm())

    def validate_and_confirm(self):
        """Valida la entrada y pide confirmación antes de bloquear."""
        pwd = self.password_entry.get()
        if len(pwd) < 1:
            messagebox.showwarning(
                "Atención", "La contraseña no puede estar vacía.", parent=self.root
            )
            return

        msg = self.message_text.get("1.0", tk.END).strip()
        if msg == "":
            self.lock_message_optional = None
        else:
            if len(msg) > 1000:
                messagebox.showwarning(
                    "Atención", "El mensaje no puede superar los 1000 caracteres.", parent=self.root
                )
                return
            self.lock_message_optional = msg

        self.unlock_password = pwd
        self.setup_frame.destroy()

        if messagebox.askokcancel(
            "Confirmar Bloqueo", "¿Está seguro de que desea bloquear este ordenador?"
        ):
            write_log("Confirmado bloqueo por el usuario.")
            self.root.withdraw()
            self.start_locking_process()
        else:
            self.create_setup_window()

    def start_locking_process(self):
        """Inicia el watchdog y cubre todas las pantallas conectadas."""
        write_log("Iniciando proceso de bloqueo completo.")
        self.lock_start_time = time.time()
        self.start_watchdog()
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                0x80000000 | 0x00000001 | 0x00000002
            )
        except Exception as e:
            write_log(f"FALLO al cambiar estado de ejecución: {e}")

        self.create_lock_screen()

    def _kill_target_processes(self):
        """Termina procesos potencialmente peligrosos durante el bloqueo."""
        targets = {
            "explorer.exe",
            "cmd.exe",
            "powershell.exe",
            "pwsh.exe",
            "taskmgr.exe",
            "regedit.exe",
            "msconfig.exe",
        }
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() in targets:
                    proc.kill()
                    write_log(f"Proceso bloqueado eliminado: {proc.info['name']}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                pass

    def _watchdog_loop(self):
        """Loop de control en hilo secundario."""
        while self._watchdog_running:
            self._kill_target_processes()
            time.sleep(0.2)

    def start_watchdog(self):
        if not self._watchdog_running:
            self._watchdog_running = True
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, daemon=True
            )
            self._watchdog_thread.start()

    def stop_watchdog(self):
        self._watchdog_running = False

    @staticmethod
    def _hide_system_cursor():
        """Oculta y ancla el cursor en un punto ciego."""
        try:
            while user32.ShowCursor(False) >= 0:
                pass
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
            while user32.ShowCursor(True) < 0:
                pass
            user32.ClipCursor(None)
        except Exception as e:
            write_log(f"Error restaurando cursor: {e}")

    def create_lock_screen(self):
        """Crea ventanas de bloqueo en TODOS los monitores detectados."""
        write_log("Creando pantallas de bloqueo multi-monitor.")
        self._hide_system_cursor()

        monitors = get_monitors_info()
        primary_mon = next((m for m in monitors if m["is_primary"]), monitors[0])
        secondary_mons = [m for m in monitors if m != primary_mon]

        self.secondary_screens = []

        # 1. Cubrir todos los monitores secundarios con pantallas negras bloqueantes
        for idx, mon in enumerate(secondary_mons):
            sec_win = tk.Toplevel(self.root)
            sec_win.title(f"WinLock Guard {idx}")
            sec_win.overrideredirect(True)
            sec_win.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")
            sec_win.attributes("-topmost", True)
            sec_win.config(cursor="none", bg="#0a0a0a")

            # Indicador discreto en monitores secundarios
            sec_label = tk.Label(
                sec_win,
                text="WinLock - Pantalla protegida",
                font=("Segoe UI", 14),
                fg="#333333",
                bg="#0a0a0a"
            )
            sec_label.pack(expand=True)
            self.secondary_screens.append(sec_win)

        # 2. Pantalla principal interactiva
        self.primary_lock_window = tk.Toplevel(self.root)
        lock_win = self.primary_lock_window
        lock_win.title("WinLock - Bloqueado")
        lock_win.overrideredirect(True)
        lock_win.geometry(f"{primary_mon['width']}x{primary_mon['height']}+{primary_mon['left']}+{primary_mon['top']}")
        lock_win.attributes("-topmost", True)
        lock_win.config(cursor="none", bg="#1c1c1c")
        lock_win.protocol("WM_DELETE_WINDOW", lambda: None)
        lock_win.grab_set()

        NON_PRINTABLE_KEYS = {
            "shift", "right shift", "ctrl", "right ctrl", "alt", "right alt",
            "caps lock", "esc", "tab", "home", "end", "insert", "delete",
            "page up", "page down", "print screen", "scroll lock", "pause",
            "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
            "up", "down", "left", "right", "num lock", "apps", "left windows", "right windows"
        }

        # Header info
        version_label = tk.Label(
            lock_win,
            text=f"WinLock {LOCAL_VERSION} - LabDigital",
            font=("Segoe UI", 10),
            fg="#808080",
            bg="#1c1c1c",
        )
        version_label.place(x=15, y=15, anchor="nw")

        tk.Label(
            lock_win,
            text="WinLock",
            font=("Segoe UI Black", 44),
            fg="white",
            bg="#1c1c1c",
        ).pack(pady=(60, 0))

        time_label = tk.Label(
            lock_win, font=("Segoe UI Light", 64), fg="white", bg="#1c1c1c"
        )
        time_label.pack(pady=(15, 0))

        date_label = tk.Label(
            lock_win, font=("Segoe UI Semilight", 20), fg="#A0A0A0", bg="#1c1c1c"
        )
        date_label.pack()

        duration_label = tk.Label(
            lock_win, font=("Segoe UI", 12), fg="#A0A0A0", bg="#1c1c1c"
        )
        duration_label.pack(pady=10)

        def update_time_and_duration():
            if not lock_win.winfo_exists():
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
            lock_win.after(1000, update_time_and_duration)

        update_time_and_duration()

        center_frame = tk.Frame(lock_win, bg="#1c1c1c")
        center_frame.pack(expand=True)

        tk.Label(
            center_frame,
            text="Contraseña:",
            font=("Segoe UI", 12),
            fg="#cccccc",
            bg="#1c1c1c",
        ).pack(pady=(10, 5))

        entry_frame = tk.Frame(
            center_frame,
            bg="#1c1c1c",
            highlightthickness=1,
            highlightbackground="#333",
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
        )
        unlock_entry.pack(ipady=8)

        status_label = tk.Label(
            center_frame, text="", font=("Segoe UI", 11), fg="#ff3b30", bg="#1c1c1c"
        )
        status_label.pack(pady=4)

        if self.lock_message_optional:
            message_frame = tk.Frame(
                center_frame,
                bg="#252525",
                bd=1,
                relief="solid",
                padx=15,
                pady=10
            )
            message_frame.pack(pady=(15, 0))
            tk.Label(
                message_frame,
                text="Mensaje del propietario:",
                font=("Segoe UI", 11, "bold"),
                fg="#ffffff",
                bg="#252525"
            ).pack()
            tk.Label(
                message_frame,
                text=self.lock_message_optional,
                font=("Segoe UI", 11),
                fg="#cccccc",
                bg="#252525",
                wraplength=600,
                justify="center"
            ).pack(pady=(5, 0))

        bottom_frame = tk.Frame(lock_win, bg="#1c1c1c")
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
        tk.Label(
            bottom_frame,
            text="Este equipo ha sido bloqueado con WinLock.",
            font=("Segoe UI", 10),
            fg="#A0A0A0",
            bg="#1c1c1c",
        ).pack()

        def check_password():
            entered_pass = unlock_entry.get()
            if entered_pass == self.unlock_password:
                write_log("Contraseña correcta. Desbloqueando todas las pantallas.")
                lock_win.destroy()
                for sw in self.secondary_screens:
                    try:
                        sw.destroy()
                    except Exception:
                        pass
                self._quit_app()
            else:
                write_log("Contraseña incorrecta introducida.")
                status_label.config(text="Contraseña incorrecta")
                unlock_entry.config(state="normal")
                unlock_entry.delete(0, tk.END)
                unlock_entry.config(state="readonly")
                status_label.after(2500, lambda: status_label.config(text=""))

        def handle_key_press(event):
            if not lock_win.winfo_exists():
                return False

            key_name = event.name.lower()
            if status_label.cget("text"):
                status_label.config(text="")

            unlock_entry.config(state="normal")

            if key_name == "enter":
                check_password()
                unlock_entry.config(state="readonly")
                return False
            elif key_name == "backspace":
                current_text = unlock_entry.get()
                if current_text:
                    unlock_entry.delete(len(current_text) - 1, tk.END)
                unlock_entry.config(state="readonly")
                return False
            elif len(key_name) == 1 and key_name not in NON_PRINTABLE_KEYS:
                caps_on = user32.GetKeyState(0x14) & 1
                shift_on = keyboard.is_pressed("shift") or keyboard.is_pressed("right shift")
                char = event.name
                if "a" <= key_name <= "z":
                    is_upper = (caps_on and not shift_on) or (not caps_on and shift_on)
                    char = key_name.upper() if is_upper else key_name.lower()

                unlock_entry.insert(tk.END, char)
                unlock_entry.config(state="readonly")
                return False

            unlock_entry.config(state="readonly")
            return False

        keyboard.on_press(handle_key_press, suppress=True)

        def enforce_topmost():
            """Garantiza que ninguna ventana pase al frente en ningún monitor."""
            try:
                if lock_win.winfo_exists():
                    lock_win.attributes("-topmost", True)
                    lock_win.lift()
                    for sw in self.secondary_screens:
                        if sw.winfo_exists():
                            sw.attributes("-topmost", True)
                            sw.lift()
                    lock_win.after(500, enforce_topmost)
            except Exception:
                pass

        enforce_topmost()

    def _quit_app(self):
        """Detiene vigilantes, restaura cursor y finaliza."""
        write_log("Finalizando aplicación y restaurando sistema.")
        self.stop_watchdog()
        self._show_system_cursor()

        try:
            keyboard.unhook_all()
        except Exception:
            pass

        try:
            if hasattr(self, "root") and self.root.winfo_exists():
                self.root.destroy()
        except Exception:
            pass

        start_explorer_if_not_running()

        try:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        except Exception:
            pass

        sys.exit(0)


def show_startup_and_check_updates():
    """
    Muestra INMEDIATAMENTE una ventana elegante de carga para mantener al usuario informado
    mientras comprueba actualizaciones en segundo plano sin congelar la interfaz.
    """
    splash = tk.Tk()
    splash.title("WinLock")
    splash.geometry("380x160")
    splash.resizable(False, False)

    try:
        splash.iconbitmap(resource_path("winlock.ico"))
    except Exception:
        pass

    # Centrar ventana splash
    splash.update_idletasks()
    sw = splash.winfo_screenwidth()
    sh = splash.winfo_screenheight()
    x = (sw // 2) - (380 // 2)
    y = (sh // 2) - (160 // 2)
    splash.geometry(f"380x160+{x}+{y}")

    style = ttk.Style(splash)
    style.theme_use("clam")

    container = ttk.Frame(splash, padding="20 20 20 20")
    container.pack(expand=True, fill=tk.BOTH)

    title_label = ttk.Label(
        container, text="Iniciando WinLock...", font=("Segoe UI", 12, "bold")
    )
    title_label.pack(anchor="w")

    status_label = ttk.Label(
        container, text="Comprobando actualizaciones...", font=("Segoe UI", 9), foreground="#666"
    )
    status_label.pack(anchor="w", pady=(5, 10))

    progress = ttk.Progressbar(container, orient="horizontal", mode="indeterminate")
    progress.pack(fill=tk.X)
    progress.start(12)

    update_info = {"result": None, "done": False}

    def check_network():
        try:
            req = urllib.request.Request(
                LATEST_VERSION_JSON, headers={"User-Agent": "WinLock Updater"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                update_info["result"] = data
        except Exception as err:
            write_log(f"Error comprobando actualizaciones: {err}")
            update_info["result"] = None
        finally:
            update_info["done"] = True

    threading.Thread(target=check_network, daemon=True).start()

    def run_finalizer_script(old_exe, new_exe, script_path):
        ps_script = f"""
param()
taskkill /f /im WinLock.exe 2>$null
$maxRetries = 10
for ($i=0; $i -lt $maxRetries; $i++) {{
    try {{
        Remove-Item -LiteralPath '{old_exe}' -Force -ErrorAction Stop
        break
    }} catch {{
        Start-Sleep -Seconds 1
    }}
}}
Move-Item -LiteralPath '{new_exe}' -Destination '{old_exe}' -Force -ErrorAction SilentlyContinue
Start-Process -FilePath '{old_exe}'
Start-Sleep -Seconds 1
Remove-Item -LiteralPath '{script_path}' -Force -ErrorAction SilentlyContinue
"""
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(ps_script)

        subprocess.Popen([
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-File", script_path
        ])
        sys.exit(0)

    def prompt_update(latest_info):
        progress.stop()
        progress.destroy()
        title_label.config(text="¡Actualización disponible!")
        status_label.config(
            text=f"Versión disponible: {latest_info.get('tag_name')}\n¿Desea actualizar ahora?"
        )

        btn_box = ttk.Frame(container)
        btn_box.pack(fill=tk.X, pady=(10, 0))

        def proceed_download():
            for w in container.winfo_children():
                w.destroy()

            l1 = ttk.Label(container, text="Descargando actualización...", font=("Segoe UI", 10, "bold"))
            l1.pack(anchor="w")
            pb = ttk.Progressbar(container, orient="horizontal", mode="determinate")
            pb.pack(fill=tk.X, pady=(10, 5))
            st = ttk.Label(container, text="Conectando...", font=("Segoe UI", 8))
            st.pack(anchor="w")

            def download_thread():
                try:
                    temp_dir = os.environ.get("TEMP", ".")
                    new_exe = os.path.join(temp_dir, f"winlock_new_{random.randint(1000, 9999)}.exe")
                    ps_path = os.path.join(temp_dir, f"updater_{random.randint(1000, 9999)}.ps1")

                    def reporthook(blocks, block_size, total):
                        if total > 0:
                            done = blocks * block_size
                            pct = int(done * 100 / total)
                            pb["value"] = pct
                            st.config(text=f"{done // 1048576}MB / {total // 1048576}MB")

                    urllib.request.urlretrieve(latest_info["download_url"], new_exe, reporthook)
                    st.config(text="Instalando y reiniciando...")
                    time.sleep(1)
                    run_finalizer_script(os.path.abspath(sys.executable), new_exe, ps_path)
                except Exception as ex:
                    write_log(f"Error descargando actualización: {ex}")
                    splash.destroy()

            threading.Thread(target=download_thread, daemon=True).start()

        ttk.Button(btn_box, text="Actualizar", command=proceed_download).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="Más tarde", command=splash.destroy).pack(side=tk.RIGHT)

    def monitor_progress():
        if update_info["done"]:
            info = update_info["result"]
            if info and info.get("tag_name") and info.get("tag_name") != LOCAL_VERSION and info.get("download_url"):
                prompt_update(info)
            else:
                splash.destroy()
        else:
            splash.after(100, monitor_progress)

    splash.after(100, monitor_progress)
    splash.mainloop()


if __name__ == "__main__":
    write_log(f"\n{'='*50}\nIniciando sesión de WinLock {LOCAL_VERSION}")
    
    # Muestra el feedback de carga y comprueba updates
    show_startup_and_check_updates()

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
            WinLock._show_system_cursor()
            start_explorer_if_not_running()
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            except Exception:
                pass
            try:
                keyboard.unhook_all()
            except Exception:
                pass
            sys.exit(0)
