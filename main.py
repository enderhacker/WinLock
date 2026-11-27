import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import font, ttk
import webbrowser

from windows_session import WindowsSession
from winlock_core import LockCycle, RELEASES_URL, UpdateCheck


LOCAL_VERSION = "v0.8"
LOG = logging.getLogger("winlock")


class WinLock:
    def __init__(self, root):
        self.root = root
        self.session = None
        self.cycle = None
        self.update_check = None
        self.poll_id = None

        root.title(f"WinLock {LOCAL_VERSION}")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", root.quit)
        try:
            root.iconbitmap(str(Path(__file__).with_name("winlock.ico")))
        except tk.TclError:
            LOG.warning("No se pudo cargar el icono de WinLock.")

        body_font = font.nametofont("TkDefaultFont")
        self.heading_font = body_font.copy()
        self.heading_font.configure(size=14, weight="bold")
        self.section_font = body_font.copy()
        self.section_font.configure(weight="bold")
        style = ttk.Style(root)
        style.configure("Heading.TLabel", font=self.heading_font)
        style.configure("Section.TLabel", font=self.section_font)
        style.configure("Action.TButton", padding=(10, 6))

        text_width = body_font.measure("0") * 62
        status_height = body_font.metrics("linespace") * 3 + 4
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1, minsize=text_width)
        frame.rowconfigure(3, minsize=status_height)
        frame.rowconfigure(7, minsize=status_height)

        ttk.Label(frame, text="Bloquear sin suspender", style="Heading.TLabel").grid(row=0, sticky="w")
        ttk.Label(
            frame,
            text="Windows bloqueará tu sesión. WinLock solicitará que el equipo no entre en "
            "suspensión automática hasta que vuelvas a iniciar sesión. Usa tu PIN, contraseña "
            "o Windows Hello para desbloquear.",
            wraplength=text_width,
            justify="left",
        ).grid(row=1, sticky="w", pady=(6, 12))

        self.lock_button = ttk.Button(frame, text="Bloquear ahora", style="Action.TButton", command=self.lock)
        self.lock_button.grid(row=2, sticky="w")
        self.lock_status = tk.StringVar(value="Listo para bloquear la sesión.")
        ttk.Label(frame, textvariable=self.lock_status, wraplength=text_width, justify="left").grid(
            row=3, sticky="nw", pady=(4, 0)
        )

        ttk.Separator(frame).grid(row=4, sticky="ew", pady=(4, 12))
        ttk.Label(frame, text="Actualizaciones", style="Section.TLabel").grid(row=5, sticky="w", pady=(0, 6))
        buttons = ttk.Frame(frame)
        buttons.grid(row=6, sticky="w")
        self.check_button = ttk.Button(
            buttons, text="Buscar actualizaciones", style="Action.TButton", command=self.check_updates
        )
        self.check_button.pack(side="left", padx=(0, 8))
        ttk.Button(
            buttons, text="Ver descargas oficiales", style="Action.TButton", command=self.open_releases
        ).pack(side="left")
        self.update_status = tk.StringVar()
        ttk.Label(frame, textvariable=self.update_status, wraplength=text_width, justify="left").grid(
            row=7, sticky="nw", pady=(4, 0)
        )

        self.lock_button.focus_set()
        self.check_updates()
        self.poll_id = root.after(200, self.poll)

    def lock(self):
        try:
            if self.session is None:
                self.session = WindowsSession(self.root.winfo_id())
                self.cycle = LockCycle(self.session)
            self.session.subscribe()
            self.cycle.start()
        except (OSError, RuntimeError):
            LOG.exception("No se pudo iniciar el bloqueo.")
            self.show_lock_failure("No se pudo iniciar el bloqueo. Puedes usar Windows + L.")
        else:
            self.lock_button.state(["disabled"])
            self.lock_status.set("Esperando a que Windows bloquee la sesión…")

    def show_lock_failure(self, message):
        if self.cycle is not None and self.cycle.awake:
            self.lock_button.state(["disabled"])
            message = "No se pudo restablecer la suspensión. Cierra WinLock para liberarla."
        else:
            self.lock_button.state(["!disabled"])
        self.lock_status.set(message)

    def check_updates(self):
        self.update_check = UpdateCheck(LOCAL_VERSION)
        self.check_button.state(["disabled"])
        self.update_status.set("Comprobando actualizaciones…")

    def open_releases(self):
        try:
            if not webbrowser.open(RELEASES_URL):
                raise OSError("No hay un navegador disponible.")
        except (OSError, webbrowser.Error):
            LOG.exception("No se pudo abrir la página de versiones.")
            self.update_status.set(f"No se pudo abrir el navegador. Visita: {RELEASES_URL}")

    def poll(self):
        if self.cycle is not None:
            try:
                result = self.cycle.poll()
            except OSError:
                LOG.exception("No se pudo restablecer la suspensión.")
                self.show_lock_failure("No se pudo completar el bloqueo.")
            else:
                if result == "unlocked":
                    self.lock_button.state(["!disabled"])
                    self.lock_status.set("Sesión desbloqueada. Se ha restablecido la suspensión automática.")
                elif result == "not_confirmed":
                    LOG.warning("Windows no confirmó el bloqueo de la sesión.")
                    self.show_lock_failure("Windows no confirmó el bloqueo. Puedes usar Windows + L.")
                elif self.cycle.state == "locked":
                    self.lock_status.set("Sesión bloqueada.")

        if self.update_check is not None:
            outcome = self.update_check.poll()
            if outcome is not None:
                self.update_check = None
                self.check_button.state(["!disabled"])
                status, value = outcome
                if status == "error":
                    LOG.warning("Error comprobando actualizaciones: %s", value)
                    self.update_status.set("No se pudo comprobar la versión. WinLock está listo para usar.")
                elif value:
                    self.update_status.set(f"Disponible: {value}. Consulta las descargas oficiales.")
                else:
                    self.update_status.set("No hay una versión más reciente.")

        self.poll_id = self.root.after(200, self.poll)

    def close(self):
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        try:
            if self.cycle is not None:
                self.cycle.stop()
        except OSError:
            LOG.exception("No se pudo liberar la solicitud de energía al cerrar.")
        finally:
            if self.session is not None:
                try:
                    self.session.close()
                except OSError:
                    LOG.exception("No se pudo cancelar la suscripción a eventos de Windows.")


def configure_logging():
    directory = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WinLock"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / "WinLock.log", maxBytes=256_000, backupCount=2, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler() if sys.stderr is not None else logging.NullHandler()
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")


def main():
    if sys.platform != "win32":
        print("WinLock solo es compatible con Windows.", file=sys.stderr)
        return 1
    configure_logging()
    root = tk.Tk()
    app = None
    try:
        app = WinLock(root)
        root.mainloop()
    finally:
        try:
            if app is not None:
                app.close()
        finally:
            root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
