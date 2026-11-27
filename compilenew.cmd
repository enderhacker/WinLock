@echo off
setlocal
pushd "%~dp0" || exit /b 1

set "BUILD_PYTHON=%WINLOCK_PYTHON%"
if not defined BUILD_PYTHON set "BUILD_PYTHON=.venv\Scripts\python.exe"

"%BUILD_PYTHON%" -c "import struct, sys, tkinter; from importlib.metadata import version; assert sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') == 8, 'Use CPython 3.14.7 (64-bit)'; assert version('Nuitka') == '4.2.1', 'Install requirements-build.txt'"
if errorlevel 1 (
    echo Build environment not ready. See README.md for setup.
    popd
    exit /b 1
)

"%BUILD_PYTHON%" -m nuitka ^
    --onefile ^
    --msvc=14.3 ^
    --assume-yes-for-downloads ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=winlock.ico ^
    --enable-plugin=tk-inter ^
    --include-data-files=winlock.ico=winlock.ico ^
    --output-dir=build ^
    --output-filename=WinLock.exe ^
    main.py
if errorlevel 1 (
    popd
    exit /b 1
)

REM Publish only after a successful build. Do not stop running copies.
"%BUILD_PYTHON%" -c "from pathlib import Path; dist=Path('dist'); dist.mkdir(exist_ok=True); Path('build/WinLock.exe').replace(dist / 'WinLock.exe')"
if errorlevel 1 (
    echo Could not publish to dist\WinLock.exe. The new build remains in build\WinLock.exe.
    popd
    exit /b 1
)
echo Build complete: dist\WinLock.exe
popd
exit /b 0
