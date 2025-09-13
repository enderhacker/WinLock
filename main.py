try:
    import psutil
    import subprocess
    import tkinter as tk
    from tkinter import ttk, messagebox
    import time
    import ctypes
    import ctypes.wintypes
    import os
    import sys
    import threading
    import locale
    from datetime import datetime
except ImportError:
    # This part runs if essential libraries are missing. Logging is not available yet.
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Error de Instalación - WinLock",
        "Faltan bibliotecas necesarias. Reinstala la aplicación.",
    )
    sys.exit(1)

# --- CONFIGURACIÓN DEL SISTEMA DE LOGS ---

LOG_FOLDER_NAME = "WinLock"
LOG_FILE_NAME = "logs.txt"


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

# Crear el directorio de logs si no existe.
try:
    os.makedirs(LOG_DIRECTORY, exist_ok=True)
except OSError:
    # Si falla la creación del directorio, no se podrán guardar logs.
    # Se podría mostrar un error, pero se opta por un fallo silencioso para no interrumpir la app.
    pass


def write_log(message):
    """Escribe un mensaje detallado con timestamp en el archivo de logs."""
    try:
        # Formato de timestamp: Año-Mes-Día Hora:Minuto:Segundo,Milisegundo
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        log_entry = f"[{timestamp}] - {message}\n"

        with open(LOG_FILE_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(log_entry)
    except Exception as e:
        # Si la escritura del log falla, se imprime en la consola para no crashear la app.
        print(f"Error al escribir en el log: {e}", file=sys.stderr)


# --- CÓDIGO DE LA APLICACIÓN (con logging integrado) ---


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def start_explorer_if_not_running():
    """Verifica si explorer.exe se está ejecutando y lo inicia si no es así."""
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
        self.root.title("WinLock")
        self.root.geometry("350x200")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._quit_app)
        try:
            self.root.iconbitmap(resource_path("winlock.ico"))
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
        self.password_entry.focus_set()

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
                "La contraseña debe tener al menos 1 caracter.",
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
            write_log("Usuario canceló el bloqueo del ordenador.")
            self.create_setup_window()

    def start_locking_process(self):
        """Inicia el watchdog y crea la pantalla de bloqueo."""
        write_log("Iniciando proceso de bloqueo.")
        self.lock_start_time = time.time()
        self.start_watchdog()
        try:
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
                        f"Proceso objetivo terminado por el watchdog: {proc_name}"
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
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
        """Crea la ventana de la pantalla de bloqueo de alta seguridad."""
        write_log("Creando la pantalla de bloqueo.")
        user32 = ctypes.windll.user32

        self._hide_system_cursor()
        lock_window = tk.Toplevel(self.root)
        try:
            lock_window.iconbitmap(resource_path("winlock.ico"))
        except Exception as e:
            write_log(
                f"ADVERTENCIA: No se pudo cargar el icono 'winlock.ico' para la ventana de bloqueo: {e}"
            )

        try:
            # --- Configuración de ventana ---
            lock_window.title("WinLock - Bloqueado")
            lock_window.attributes("-fullscreen", True)
            lock_window.attributes("-topmost", True)
            lock_window.config(cursor="none", bg="#1c1c1c")
            lock_window.overrideredirect(True)
            lock_window.protocol("WM_DELETE_WINDOW", lambda: None)
            lock_window.focus_set()
            lock_window.grab_set()

            def allow_only_typing_and_enter(event):
                allowed_keys = (
                    "Return",
                    "BackSpace",
                    "Delete",
                    "Insert",
                    "Left",
                    "Right",
                    "Up",
                    "Down",
                )
                if event.keysym in allowed_keys:
                    return
                if len(event.char) == 1 and event.char.isprintable():
                    return
                return "break"

            # --- Contenido UI ---
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
                time_label.config(text=time.strftime("%H:%M"))
                date_str = time.strftime("%A, %d de %B de %Y").capitalize()
                date_label.config(text=date_str)

                delta = int(time.time() - self.lock_start_time)
                days, rem = divmod(delta, 86400)
                hours, rem = divmod(rem, 3600)
                minutes, seconds = divmod(rem, 60)
                parts = []
                if days > 0:
                    parts.append(f"{days}d")
                if hours > 0:
                    parts.append(f"{hours}h")
                if minutes > 0:
                    parts.append(f"{minutes}m")
                parts.append(f"{seconds}s")
                duration_label.config(text="Tiempo bloqueado: " + " ".join(parts))

                lock_window.after(1000, update_time_and_duration)

            update_time_and_duration()

            center_frame = tk.Frame(lock_window, bg="#1c1c1c")
            center_frame.pack(expand=True)

            unlock_entry = tk.Entry(
                center_frame,
                show="•",
                font=("Segoe UI", 16),
                bg="#2b2b2b",
                fg="white",
                insertbackground="white",
                justify="center",
                bd=0,
                width=25,
            )
            unlock_entry.pack(pady=(15, 8), ipady=10)
            unlock_entry.focus_force()

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
            tk.Label(
                bottom_frame,
                text="Aplicación 'WinLock' creada por Jaime Muñiz García - https://winlock.labdigital.es",
                font=("Segoe UI", 10),
                fg="#A0A0A0",
                bg="#1c1c1c",
            ).pack(pady=(5, 0))

            def check_password(event=None):
                if unlock_entry.get() == self.unlock_password:
                    write_log("Contraseña correcta introducida. Desbloqueando.")
                    lock_window.destroy()
                    self._quit_app()
                else:
                    write_log("Intento de desbloqueo con contraseña incorrecta.")
                    status_label.config(text="Contraseña incorrecta")
                    unlock_entry.delete(0, tk.END)
                    status_label.after(3000, lambda: status_label.config(text=""))

            def redirect_keys(event):
                try:
                    unlock_entry.focus_set()
                except:
                    pass
                return "break"

            lock_window.bind_all("<Key>", redirect_keys)
            unlock_entry.bind("<Key>", allow_only_typing_and_enter)
            lock_window.bind("<Return>", check_password)

            def refocus_on_click(event=None):
                try:
                    unlock_entry.focus_set()
                except:
                    pass

            lock_window.bind_all("<Button-1>", refocus_on_click)
            lock_window.bind_all("<Button-2>", refocus_on_click)
            lock_window.bind_all("<Button-3>", refocus_on_click)
            lock_window.bind_all("<MouseWheel>", refocus_on_click)

            cx, cy = user32.GetSystemMetrics(0) // 2, user32.GetSystemMetrics(1) // 2
            lock_window.bind_all("<Motion>", lambda e: user32.SetCursorPos(cx, cy))
            write_log(
                "Pantalla de bloqueo creada y visible. Control de ratón y teclado activado."
            )

        except Exception as e:
            write_log(
                f"ERROR CRÍTICO al crear la pantalla de bloqueo: {e}. Saliendo para proteger al usuario."
            )
            self._quit_app()

    def _quit_app(self):
        """Detiene todos los procesos y cierra la aplicación de forma segura."""
        write_log("Iniciando secuencia de salida de la aplicación.")
        self.stop_watchdog()
        self._show_system_cursor()

        # Solo destruir si sigue existiendo
        try:
            if hasattr(self, "root") and self.root.winfo_exists():
                try:
                    self.root.destroy()
                except Exception as e:
                    write_log(f"FALLO al destruir root: {e}")
        except Exception as e:
            write_log(f"FALLO al destruir root antes de comprobar: {e}")

        start_explorer_if_not_running()

        try:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            write_log("Estado de ejecución del hilo restaurado a la normalidad.")
        except Exception as e:
            write_log(f"FALLO al restaurar estado de ejecución del hilo: {e}")

        sys.exit(0)


if __name__ == "__main__":
    write_log("\n" + "=" * 50 + "\nIniciando nueva sesión de WinLock.")
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
        else:
            # En caso de que la app falle antes de instanciarse.
            WinLock._show_system_cursor()
            start_explorer_if_not_running()
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            write_log("Aplicación finalizada.\n" + "=" * 50 + "\n")
            sys.exit(0)
