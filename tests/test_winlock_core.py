import io
import json
import threading
import unittest

from winlock_core import LockCycle, MAX_MANIFEST_BYTES, UpdateCheck, find_update


class FakeSession:
    def __init__(self):
        self.calls = []
        self.events = []
        self.lock_error = False
        self.power_error = None

    def take_events(self):
        events, self.events = self.events, []
        return events

    def set_awake(self, enabled):
        self.calls.append(("awake", enabled))
        if self.power_error is enabled:
            raise OSError("power request failed")

    def lock(self):
        self.calls.append(("lock",))
        if self.lock_error:
            raise OSError("lock failed")


class LockCycleTest(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.now = 0
        self.cycle = LockCycle(self.session, clock=lambda: self.now)

    def test_keeps_awake_until_native_unlock(self):
        self.cycle.start()
        self.session.events.append("lock")
        self.now = 30
        self.assertIsNone(self.cycle.poll())
        self.assertEqual(self.cycle.state, "locked")
        self.assertTrue(self.cycle.awake)
        self.session.events.append("unlock")
        self.assertEqual(self.cycle.poll(), "unlocked")
        self.assertEqual(self.session.calls, [("awake", True), ("lock",), ("awake", False)])
        self.assertFalse(self.cycle.awake)

    def test_rolls_back_failed_lock(self):
        self.session.lock_error = True
        with self.assertRaises(OSError):
            self.cycle.start()
        self.assertEqual(self.session.calls[-1], ("awake", False))
        self.assertEqual(self.cycle.state, "idle")
        self.assertFalse(self.cycle.awake)

    def test_does_not_lock_when_power_request_fails(self):
        self.session.power_error = True
        with self.assertRaises(OSError):
            self.cycle.start()
        self.assertEqual(self.session.calls, [("awake", True)])
        self.assertEqual(self.cycle.state, "idle")

    def test_releases_if_windows_does_not_confirm_lock(self):
        self.session.events.append("lock")  # Stale notification.
        self.cycle.start()
        self.now = 11
        self.assertEqual(self.cycle.poll(), "not_confirmed")
        self.assertFalse(self.cycle.awake)

    def test_close_can_retry_failed_power_release(self):
        self.cycle.start()
        self.session.power_error = False
        self.session.events.append("unlock")
        with self.assertRaises(OSError):
            self.cycle.poll()
        self.assertTrue(self.cycle.awake)
        self.session.power_error = None
        self.cycle.stop()
        self.cycle.stop()
        self.assertFalse(self.cycle.awake)
        self.assertEqual(self.session.calls.count(("awake", False)), 2)


class UpdateTest(unittest.TestCase):
    @staticmethod
    def fetch(payload):
        return find_update("v0.7", open_url=lambda *_args, **_kwargs: io.BytesIO(payload))

    def test_only_offers_strictly_newer_numeric_versions(self):
        for version, expected in [("v0.6", None), ("v0.7.0", None), ("v0.10", "v0.10")]:
            with self.subTest(version=version):
                self.assertEqual(self.fetch(json.dumps({"tag_name": version}).encode()), expected)

    def test_rejects_bad_and_oversized_manifests(self):
        for payload in (b"[]", b'{"tag_name": 7}', b"not JSON", b" " * (MAX_MANIFEST_BYTES + 1)):
            with self.subTest(length=len(payload)):
                with self.assertRaises(ValueError):
                    self.fetch(payload)

    def test_stalled_lookup_has_deadline(self):
        release_worker = threading.Event()
        now = 0

        def lookup(_current):
            release_worker.wait(5)
            return "v0.8"

        try:
            check = UpdateCheck("v0.7", lookup=lookup, clock=lambda: now)
            self.assertIsNone(check.poll())
            now = 6
            status, error = check.poll()
            self.assertEqual(status, "error")
            self.assertIsInstance(error, TimeoutError)
            self.assertEqual(check.poll(), (status, error))
        finally:
            release_worker.set()
