# WinLock

## Run and verify

- Run the desktop app from the repo root with `python main.py` on Windows with Tcl/Tk. Runtime is standard-library only; `requirements-build.txt` is for packaging. For GUI failures in the console-free executable, check `%LOCALAPPDATA%\WinLock\WinLock.log`.
- Run `python -m unittest discover -s tests -v`; for just the lock state machine, add `-k LockCycle`. Tests fake Windows session events and networking. Verify real lock → stay awake → unlock behavior separately on an interactive Windows session.
- Build with `.\compilenew.cmd` after the [README setup](README.md#compilar-desde-un-clon-limpio). The script requires exactly CPython 3.14.7 x64 and Nuitka 4.2.1 with VS 2022 C++ tools. It defaults to `.venv\Scripts\python.exe`; use `$env:WINLOCK_PYTHON = (Get-Command python).Source` to select an already configured interpreter. `build\` and `dist\WinLock.exe` are generated and ignored.

## Desktop and release boundaries

- `main.py` owns the Spanish Tk UI; Windows owns the actual lock screen and authentication. `windows_session.py` subscribes to WTS notifications on the Tk window. Keep power request acquisition and release on the Tk thread: `SetThreadExecutionState` is thread-scoped. Test lock-cycle changes through `LockCycle` in `winlock_core.py` with a fake session.
- The desktop checks for updates off the UI thread and opens GitHub Releases in a browser. The static site (`website/index.html`) reads the same manifest but links to the executable. `version.json` describes the **published** release; preserve `download_url` for older clients and update it only after the asset is published.
- Before pushing a release tag, run `python -m scripts.release check-source vX.Y` to check `main.py`’s `LOCAL_VERSION`, the README title, and the website’s `navVersion` badge. The [release workflow](.github/workflows/release.yml) requires the tag commit to be on `main`; it publishes `WinLock.exe` before committing the manifest back to `main`.
