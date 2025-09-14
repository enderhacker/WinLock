try:
    import psutil
    import subprocess
    import tkinter as tk
    from tkinter import ttk, messagebox
    import time
    import ctypes
    import ctypes.wintypes
    import keyboard
    import os
    import sys
    import threading
    import json
    import urllib.request
    import webbrowser
    import locale
    from datetime import datetime
except ImportError:
    # This part runs if essential libraries are missing. Logging is not available yet.
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Instalación fallida - WinLock",
        "Faltan bibliotecas necesarias. Reinstala la aplicación.",
    )
    sys.exit(1)

# --- CONFIGURACIÓN DEL SISTEMA DE LOGS ---

LOG_FOLDER_NAME = "WinLock"
LOG_FILE_NAME = f"logs-{datetime.now().strftime('%d_%m_%Y-%H_%M_%S')}.txt"
LOCAL_VERSION = "v0.4"
LATEST_VERSION_JSON = (
    "https://raw.githubusercontent.com/enderhacker/WinLock/refs/heads/main/version.json"
)
UPDATE_URL = "https://winlock.labdigital.es"


def get_log_path():
    """Obtiene la ruta para el archivo de logs en una carpeta que no requiere permisos."""
    try:
        # APPDATA es la ubicación estándar y preferida para datos de aplicación.
        app_data_path = os.environ.get("APPDATA")
        if not app_data_path:
            # Si APPDATA no está disponible, usar el directorio home del usuario como alternativa.
            app_data_path = os.path.expanduser("~")

        log_dir = os.path.join(app_data_path, LOG_FOLDER_NAME)
        return log_dir
    except Exception:
        # Como último recurso, usar el directorio del script.
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
    """Get absolute path to resource, works for dev and PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def start_explorer_if_not_running():
    """Verifica si explorer.exe se está ejecutando y lo inicia si no es así."""
    write_log("Revisando el estado de explorer.exe.")
    explorer_running = any(
        proc.name().lower() == "explorer.exe" for proc in psutil.process_iter()
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


user32 = ctypes.WinDLL("user32", use_last_error=True)


class WinLock:
    """
    WinLock: Una aplicación para bloquear de forma segura y profesional una pantalla de Windows.
    """

    def __init__(self, root_window):
        write_log("Inicializando la aplicación WinLock.")
        self.root = root_window
        self.unlock_password = ""
        self.lock_start_time = 0
        self._watchdog_thread = None
        self._watchdog_running = False
        self.setup_frame = None
        try:
            locale.setlocale(locale.LC_TIME, "es_ES.UTF-8")
            write_log("Locale configurado a 'es_ES.UTF-8'.")
        except locale.Error:
            try:
                locale.setlocale(locale.LC_TIME, "Spanish_Spain.1252")
                write_log("Locale configurado a 'Spanish_Spain.1252'.")
            except locale.Error as e:
                write_log(
                    f"ADVERTENCIA: No se pudo configurar el locale en español: {e}"
                )

        # --- Configurar la ventana principal ---
        self.root.title(f"WinLock {LOCAL_VERSION}")
        self.root.geometry("350x200")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._quit_app)
        try:
            self.root.iconbitmap(resource_path("winlock.ico"))
            write_log("Icono 'winlock.ico' cargado para la ventana principal.")
        except Exception as e:
            write_log(f"ADVERTENCIA: No se pudo cargar el icono 'winlock.ico': {e}")

        self.center_window(self.root)

        # --- Configuración de estilo ---
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
        write_log("Estilos de la interfaz gráfica configurados.")

        self.create_setup_window()

    def center_window(self, win):
        """Centra una ventana de tkinter en la pantalla."""
        win.update_idletasks()
        width = win.winfo_width()
        height = win.winfo_height()
        x = (win.winfo_screenwidth() // 2) - (width // 2)
        y = (win.winfo_screenheight() // 2) - (height // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
        write_log(f"Ventana centrada en {x},{y} con tamaño {width}x{height}.")

    def create_setup_window(self):
        """Crea la ventana inicial para establecer la contraseña."""
        write_log("Creando la ventana de configuración de contraseña.")
        if self.setup_frame:
            self.setup_frame.destroy()

        self.setup_frame = ttk.Frame(self.root, padding="20 20 20 20")
        self.setup_frame.pack(expand=True, fill=tk.BOTH)

        ttk.Label(self.setup_frame, text="Contraseña:").pack(anchor="w")
        self.password_entry = ttk.Entry(self.setup_frame, show="•", width=35)
        self.password_entry.pack(fill=tk.X, pady=(2, 8), ipady=3)

        ttk.Label(self.setup_frame, text="Repetir Contraseña:").pack(anchor="w")
        self.confirm_entry = ttk.Entry(self.setup_frame, show="•", width=35)
        self.confirm_entry.pack(fill=tk.X, pady=(2, 15), ipady=3)

        self.lock_button = ttk.Button(
            self.setup_frame,
            text="Bloquear",
            command=self.validate_and_confirm,
            style="Lock.TButton",
        )
        self.lock_button.pack(pady=0, ipady=0, fill=tk.X)

        self.root.lift()
        self.root.focus_force()
        self.password_entry.focus_set()

        self.root.bind("<Return>", lambda event: self.validate_and_confirm())
        write_log("Ventana de configuración de contraseña creada y visible.")

    def validate_and_confirm(self):
        """Valida las contraseñas y pide confirmación al usuario antes de bloquear."""
        write_log("Iniciando validación de contraseña.")
        pwd = self.password_entry.get()
        confirm_pwd = self.confirm_entry.get()

        if len(pwd) < 1:
            write_log("Validación fallida: la contraseña está vacía.")
            messagebox.showwarning(
                "Atención",
                "La contraseña no puede estar vacía.",
                parent=self.root,
            )
            return

        if pwd != confirm_pwd:
            write_log("Validación fallida: las contraseñas no coinciden.")
            messagebox.showerror(
                "Error",
                "Las contraseñas no coinciden. Por favor, inténtalo de nuevo.",
                parent=self.root,
            )
            self.password_entry.delete(0, tk.END)
            self.confirm_entry.delete(0, tk.END)
            self.password_entry.focus_set()
            return

        write_log("Validación de contraseña exitosa.")
        self.unlock_password = pwd
        self.setup_frame.destroy()

        if messagebox.askokcancel(
            "Confirmar Bloqueo", "¿Está seguro de que desea bloquear este ordenador?"
        ):
            write_log("Usuario confirmó el bloqueo del ordenador.")
            self.root.withdraw()
            self.start_locking_process()
        else:
            write_log(
                "Usuario canceló el bloqueo del ordenador. Mostrando de nuevo la configuración."
            )
            self.create_setup_window()

    def start_locking_process(self):
        """Inicia el watchdog y crea la pantalla de bloqueo."""
        write_log("Iniciando proceso de bloqueo.")
        self.lock_start_time = time.time()
        self.start_watchdog()
        try:
            # Previene que el sistema entre en modo de suspensión
            ctypes.windll.kernel32.SetThreadExecutionState(
                0x80000000 | 0x00000001 | 0x00000002
            )
            write_log("Estado de ejecución del hilo cambiado para prevenir suspensión.")
        except Exception as e:
            write_log(f"FALLO al cambiar estado de ejecución del hilo: {e}")
        self.create_lock_screen()

    def _kill_target_processes(self):
        """Cierra los procesos que podrían usarse para eludir el bloqueo."""
        targets = [
            "explorer.exe",
            "cmd.exe",
            "powershell.exe",
            "taskmgr.exe",
            "regedit.exe",
            "msconfig.exe",
        ]
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() in targets:
                    proc_name = proc.info["name"]
                    proc.kill()
                    write_log(
                        f"Proceso objetivo terminado por el watchdog: {proc_name} (PID: {proc.info['pid']})"
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception as e:
                write_log(
                    f"Error inesperado en watchdog al intentar matar proceso: {e}"
                )

    def _watchdog_loop(self):
        """Se ejecuta continuamente en un hilo para matar procesos no deseados."""
        write_log("Bucle del watchdog iniciado.")
        while self._watchdog_running:
            self._kill_target_processes()
            time.sleep(0.2)
        write_log("Bucle del watchdog finalizado.")

    def start_watchdog(self):
        """Inicia el hilo de eliminación de procesos en segundo plano."""
        if not self._watchdog_running:
            self._watchdog_running = True
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, daemon=True
            )
            self._watchdog_thread.start()
            write_log("Hilo del watchdog iniciado.")

    def stop_watchdog(self):
        """Detiene el hilo en segundo plano."""
        if self._watchdog_running:
            self._watchdog_running = False
            write_log("Señal de detención enviada al watchdog.")

    @staticmethod
    def _hide_system_cursor():
        """Oculta el cursor del ratón y bloquea clicks/movimiento."""
        try:
            while user32.ShowCursor(False) >= 0:
                pass
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(
                ctypes.windll.user32.GetDesktopWindow(), ctypes.byref(rect)
            )
            ctypes.windll.user32.ClipCursor(ctypes.byref(rect))
            write_log("Cursor del sistema ocultado y confinado.")
        except Exception as e:
            write_log(f"FALLO al ocultar el cursor: {e}")

    @staticmethod
    def _show_system_cursor():
        """Muestra el cursor del ratón y permite clicks/movimiento."""
        try:
            while user32.ShowCursor(True) < 0:
                pass
            ctypes.windll.user32.ClipCursor(None)
            write_log("Cursor del sistema restaurado.")
        except Exception as e:
            write_log(f"FALLO al restaurar el cursor: {e}")

    def create_lock_screen(self):
        """
        Crea una ventana de pantalla de bloqueo de alta seguridad con un hook de teclado
        global que captura y suprime todas las teclas para máxima robustez.
        """
        write_log("Iniciando la creación de la pantalla de bloqueo de alta seguridad.")
        user32 = ctypes.windll.user32

        # --- Constantes para el estado de las teclas ---
        VK_CAPITAL = 0x14  # Caps Lock

        self._hide_system_cursor()
        lock_window = tk.Toplevel(self.root)

        # Lista de teclas que no producen caracteres y deben ser ignoradas.
        NON_PRINTABLE_KEYS = [
            "shift",
            "right shift",
            "ctrl",
            "right ctrl",
            "alt",
            "right alt",
            "caps lock",
            "esc",
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
            "apps",
            "left windows",
            "right windows",
        ]

        try:
            # --- Configuración de ventana ---
            lock_window.title("WinLock - Bloqueado")
            lock_window.attributes("-fullscreen", True)
            lock_window.attributes("-topmost", True)
            lock_window.config(cursor="none", bg="#1c1c1c")
            lock_window.overrideredirect(True)
            lock_window.protocol("WM_DELETE_WINDOW", lambda: None)
            lock_window.grab_set()
            write_log("Ventana configurada y grab_set() activado.")

            # --- Contenido UI ---
            version_label = tk.Label(
                lock_window,
                text=f"WinLock {LOCAL_VERSION} - https://winlock.labdigital.es",
                font=("Segoe UI", 10),
                fg="#808080",
                bg="#1c1c1c",
            )
            version_label.place(x=10, y=10, anchor="nw")

            tk.Label(
                lock_window,
                text="WinLock",
                font=("Segoe UI Black", 48),
                fg="white",
                bg="#1c1c1c",
            ).pack(pady=(80, 0))
            time_label = tk.Label(
                lock_window, font=("Segoe UI Light", 72), fg="white", bg="#1c1c1c"
            )
            time_label.pack(pady=(30, 0))
            date_label = tk.Label(
                lock_window, font=("Segoe UI Semilight", 22), fg="#A0A0A0", bg="#1c1c1c"
            )
            date_label.pack()
            duration_label = tk.Label(
                lock_window, font=("Segoe UI", 12), fg="#A0A0A0", bg="#1c1c1c"
            )
            duration_label.pack(pady=10)

            def update_time_and_duration():
                if not lock_window.winfo_exists():
                    return
                time_label.config(text=time.strftime("%H:%M"))
                date_str = time.strftime("%A, %d de %B de %Y").capitalize()
                date_label.config(text=date_str)
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
                lock_window.after(1000, update_time_and_duration)

            update_time_and_duration()

            center_frame = tk.Frame(lock_window, bg="#1c1c1c")
            center_frame.pack(expand=True)

            password_label = tk.Label(
                center_frame,
                text="Contraseña:",
                font=("Segoe UI", 12),
                fg="#cccccc",
                bg="#1c1c1c",
            )
            password_label.pack(pady=(20, 5))

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
            unlock_entry.pack(ipady=10)

            status_label = tk.Label(
                center_frame, text="", font=("Segoe UI", 11), fg="#ff3b30", bg="#1c1c1c"
            )
            status_label.pack(pady=5)

            bottom_frame = tk.Frame(lock_window, bg="#1c1c1c")
            bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
            tk.Label(
                bottom_frame,
                text="El dueño de este ordenador ha bloqueado el ordenador",
                font=("Segoe UI", 10),
                fg="#A0A0A0",
                bg="#1c1c1c",
            ).pack()
            tk.Label(
                bottom_frame,
                text="Escribe la contraseña y pulsa ENTER para desbloquearlo",
                font=("Segoe UI", 10),
                fg="#A0A0A0",
                bg="#1c1c1c",
            ).pack()

            def check_password():
                entered_pass = unlock_entry.get()
                write_log(f"Intento de desbloqueo ejecutado.")
                if entered_pass == self.unlock_password:
                    write_log("Contraseña correcta. Desbloqueando.")
                    lock_window.destroy()
                    self._quit_app()
                else:
                    write_log("Contraseña incorrecta.")
                    status_label.config(text="Contraseña incorrecta")
                    unlock_entry.config(state="normal")
                    unlock_entry.delete(0, tk.END)
                    unlock_entry.config(state="readonly")
                    status_label.after(3000, lambda: status_label.config(text=""))

            def handle_key_press(event):
                # --- LOGGING ---
                if not lock_window.winfo_exists():
                    write_log("Ventana no existe. Ignorando pulsación.")
                    unlock_entry.config(state="readonly")
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
                    caps_on = user32.GetKeyState(VK_CAPITAL) & 1
                    shift_on = keyboard.is_pressed("shift") or keyboard.is_pressed(
                        "right shift"
                    )
                    char = event.name
                    if "a" <= key_name <= "z":
                        is_upper = (caps_on and not shift_on) or (
                            not caps_on and shift_on
                        )
                        char = key_name.upper() if is_upper else key_name.lower()

                    unlock_entry.insert(tk.END, char)
                    unlock_entry.config(state="readonly")
                    return False

                unlock_entry.config(state="readonly")

            # --- Keyboard Hooking ---
            keyboard.on_press(handle_key_press, suppress=True)
            write_log("Hook de teclado global con supresión activado.")

            def center_cursor():
                try:
                    if lock_window.winfo_exists():
                        user32.SetCursorPos(
                            user32.GetSystemMetrics(0) // 2,
                            user32.GetSystemMetrics(1) // 2,
                        )
                        lock_window.after(250, center_cursor)
                except Exception:
                    pass

            center_cursor()

            write_log("Pantalla de bloqueo creada y visible.")

        except Exception as e:
            write_log(f"ERROR CRÍTICO al crear la pantalla de bloqueo: {e}. Saliendo.")
            self._quit_app()

    def _quit_app(self):
        """Detiene todos los procesos y cierra la aplicación de forma segura."""
        write_log("Iniciando secuencia de salida de la aplicación.")
        self.stop_watchdog()
        self._show_system_cursor()

        try:
            if hasattr(self, "root") and self.root.winfo_exists():
                write_log("Destruyendo la ventana raíz de tkinter.")
                self.root.destroy()
        except Exception as e:
            write_log(f"FALLO al intentar destruir la ventana raíz: {e}")

        start_explorer_if_not_running()

        try:
            # Restaurar el estado de ejecución normal del hilo
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            write_log("Estado de ejecución del hilo restaurado a la normalidad.")
        except Exception as e:
            write_log(f"FALLO al restaurar estado de ejecución del hilo: {e}")

        keyboard.unhook_all()
        write_log("Todos los hooks de teclado han sido desactivados.")
        write_log("Salida de la aplicación completada. sys.exit(0).")
        sys.exit(0)


def check_latest_version():
    write_log("Comprobando la última versión disponible...")
    try:
        with urllib.request.urlopen(LATEST_VERSION_JSON, timeout=5) as response:
            data = response.read()
            latest_info = json.loads(data)
            latest_tag = latest_info.get("tag_name", LOCAL_VERSION)
            write_log(f"Versión local: {LOCAL_VERSION}, Versión remota: {latest_tag}")

            if latest_tag != LOCAL_VERSION:
                write_log(
                    "Existe una nueva versión disponible, preguntando al usuario..."
                )
                root = tk.Tk()
                root.withdraw()
                try:
                    root.iconbitmap(resource_path("winlock.ico"))
                except Exception as e:
                    write_log(f"No se pudo establecer el icono de el actualizador: {e}")
                result = messagebox.askquestion(
                    "Nueva versión disponible",
                    f"Tu versión: {LOCAL_VERSION}\nÚltima versión: {latest_tag}\n\n¿Deseas actualizar WinLock?",
                    icon="warning",
                )
                if result == "yes":
                    write_log(f"Usuario eligió actualizar. Abriendo {UPDATE_URL}")
                    webbrowser.open(UPDATE_URL)
                    sys.exit(0)
                else:
                    write_log("Usuario eligió continuar con la versión actual.")
                root.destroy()
            else:
                write_log("La versión local está actualizada.")

    except Exception as e:
        write_log(f"No se pudo verificar la última versión: {e}")


if __name__ == "__main__":
    write_log("\n" + "=" * 50 + "\nIniciando nueva sesión de WinLock " + LOCAL_VERSION)
    check_latest_version()
    app_instance = None
    try:
        root = tk.Tk()
        app_instance = WinLock(root)
        write_log("Bucle principal de la aplicación (mainloop) iniciado.")
        root.mainloop()
    except (KeyboardInterrupt, SystemExit):
        write_log("La aplicación fue interrumpida (KeyboardInterrupt/SystemExit).")
    except Exception as e:
        write_log(f"ERROR NO CONTROLADO en el hilo principal: {e}")
    finally:
        write_log("Bloque 'finally' alcanzado, asegurando una salida limpia.")
        if app_instance:
            app_instance._quit_app()
            write_log("Aplicación finalizada.\n" + "=" * 50 + "\n")
        else:
            # En caso de que la app falle antes de instanciarse.
            write_log(
                "La instancia de la aplicación no existía, ejecutando limpieza manual."
            )
            WinLock._show_system_cursor()
            start_explorer_if_not_running()
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            except Exception:
                pass
            keyboard.unhook_all()
            write_log("Todos los hooks de teclado han sido desactivados.")
            write_log("Aplicación finalizada.\n" + "=" * 50 + "\n")
            sys.exit(0)
