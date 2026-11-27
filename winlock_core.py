import json
import queue
import re
import threading
import time
import urllib.request


RELEASES_URL = "https://github.com/enderhacker/WinLock/releases/latest"
MANIFEST_URL = (
    "https://raw.githubusercontent.com/enderhacker/WinLock/refs/heads/main/version.json"
)
MAX_MANIFEST_BYTES = 16_384


def version_key(version):
    if not isinstance(version, str) or not re.fullmatch(r"v[0-9]{1,9}(?:\.[0-9]{1,9}){1,2}", version):
        raise ValueError("Formato de versión no válido.")
    parts = tuple(map(int, version[1:].split(".")))
    return parts + (0,) * (3 - len(parts))


def find_update(current, open_url=urllib.request.urlopen):
    request = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "WinLock"})
    with open_url(request, timeout=4) as response:
        raw = response.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("El manifiesto de la versión es demasiado grande.")
    manifest = json.loads(raw)
    if not isinstance(manifest, dict):
        raise ValueError("El manifiesto de la versión no es válido.")
    latest = manifest.get("tag_name")
    return latest if version_key(latest) > version_key(current) else None


class UpdateCheck:
    """The UI polls a queue; a slow or stalled network cannot block the UI."""

    def __init__(self, current, lookup=find_update, clock=time.monotonic):
        self._clock = clock
        self._deadline = clock() + 6
        self._results = queue.Queue()
        self._outcome = None

        def run():
            try:
                self._results.put(("ok", lookup(current)))
            except Exception as error:
                self._results.put(("error", error))

        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        if self._outcome is None:
            try:
                self._outcome = self._results.get_nowait()
            except queue.Empty:
                if self._clock() >= self._deadline:
                    self._outcome = ("error", TimeoutError("Tiempo de espera agotado."))
        return self._outcome


class LockCycle:
    """Own the sleep-inhibiting request only for one native lock/unlock cycle."""

    def __init__(self, session, clock=time.monotonic):
        self.session = session
        self.clock = clock
        self.state = "idle"
        self.awake = False
        self._deadline = 0

    def start(self):
        if self.state != "idle" or self.awake:
            raise RuntimeError("Ya hay un bloqueo en curso.")
        self.session.take_events()
        self._deadline = self.clock() + 10
        self.session.set_awake(True)
        self.awake = True
        self.state = "waiting"
        try:
            self.session.lock()
        except BaseException:
            self.stop()
            raise

    def stop(self):
        self.state = "idle"
        if self.awake:
            self.session.set_awake(False)
            self.awake = False

    def poll(self):
        for event in self.session.take_events():
            if event == "lock" and self.state == "waiting":
                self.state = "locked"
            elif event == "unlock" and self.state != "idle":
                self.stop()
                return "unlocked"
        if self.state == "waiting" and self.clock() >= self._deadline:
            self.stop()
            return "not_confirmed"
        return None
