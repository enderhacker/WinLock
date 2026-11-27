# WinLock

## Run and verify

- Run the desktop app from the repo root with `python main.py` on Windows with Tcl/Tk. Runtime is standard-library only; `requirements-build.txt` is for packaging. For GUI failures in the console-free executable, check `%LOCALAPPDATA%\WinLock\WinLock.log`.
- Run `python -m unittest discover -s tests -v`; for just the lock state machine, add `-k LockCycle`. Tests fake Windows session events and networking. Verify real lock → stay awake → unlock behavior separately on an interactive Windows session.
- Build with `.\compilenew.cmd` after the [README setup](README.md#compilar-desde-un-clon-limpio). The script requires exactly CPython 3.14.7 x64 and Nuitka 4.2.1 with VS 2022 C++ tools. It defaults to `.venv\Scripts\python.exe`; use `$env:WINLOCK_PYTHON = (Get-Command python).Source` to select an already configured interpreter. `build\` and `dist\WinLock.exe` are generated and ignored.

## Desktop and release boundaries

- `main.py` owns the Spanish Tk UI; Windows owns the actual lock screen and authentication. `windows_session.py` subscribes to WTS notifications on the Tk window. Keep power request acquisition and release on the Tk thread: `SetThreadExecutionState` is thread-scoped. Test lock-cycle changes through `LockCycle` in `winlock_core.py` with a fake session.
- The desktop checks for updates off the UI thread and opens the WinLock website in a browser. The site reads the same `version.json` and links to `download_url`, which older desktop clients also need.
- `python -m scripts.release pending-version` validates `LOCAL_VERSION`, the README title, and the website’s `navVersion` badge. A push to `main` triggers the [release workflow](.github/workflows/release.yml), which commits `downloads/<version>/WinLock.exe` and `version.json` together when the source version is newer. Keep published download paths intact.
