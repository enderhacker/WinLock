:: WINLOCK COMPILER (main.py to WinLock.exe with Nuitka)
@echo off
SETLOCAL

REM --- Relaunch self as admin ---
NET SESSION >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Run as admin!!!
    exit /b
)

REM --- Variables ---
SET EXE_NAME=WinLock.exe
echo [DEBUG] EXE_NAME=%EXE_NAME%

REM --- Step 0: Check if nuitka exists ---
echo [DEBUG] Checking for Nuitka...
python -m nuitka --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Nuitka not found! Try: pip install nuitka
    pause
    exit /b
)

REM --- Step 1: Check required files ---
IF NOT EXIST main.py (
    echo [ERROR] main.py not found!
    pause
    exit /b
)
IF NOT EXIST winlock.ico (
    echo [ERROR] winlock.ico not found!
    pause
    exit /b
)

REM --- Step 2: Clean old builds ---
taskkill /f /im %EXE_NAME% >nul 2>&1
IF EXIST %EXE_NAME% del /f /q %EXE_NAME%
IF EXIST build rmdir /s /q build
IF EXIST dist rmdir /s /q dist
IF EXIST main.build rmdir /s /q main.build
IF EXIST main.dist rmdir /s /q main.dist
IF EXIST main.onefile-build rmdir /s /q main.onefile-build
IF EXIST nuitka-crash-report.xml del /f /q nuitka-crash-report.xml

REM --- Step 3: Nuitka build ---
echo [DEBUG] Running Nuitka compiler...
python -m nuitka ^
    --standalone ^
    --onefile ^
    --msvc=latest ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=winlock.ico ^
    --enable-plugin=tk-inter ^
    --windows-uac-admin ^
    --include-data-file=winlock.ico=winlock.ico ^
    --output-filename=%EXE_NAME% ^
    main.py

IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Nuitka build failed!
    pause
    exit /b
)
REM --- Step 4: Finish ---
IF EXIST %EXE_NAME% (
    echo [DEBUG] Build complete! %EXE_NAME% is ready.

    REM --- Clean up Nuitka build artifacts ---
    IF EXIST main.build rmdir /s /q main.build
    IF EXIST main.dist rmdir /s /q main.dist
    IF EXIST main.onefile-build rmdir /s /q main.onefile-build
    IF EXIST nuitka-crash-report.xml del /f /q nuitka-crash-report.xml

) ELSE (
    echo [ERROR] Could not find final executable!

    REM --- Attempt cleanup anyway ---
    IF EXIST main.build rmdir /s /q main.build
    IF EXIST main.dist rmdir /s /q main.dist
    IF EXIST main.onefile-build rmdir /s /q main.onefile-build
    IF EXIST nuitka-crash-report.xml del /f /q nuitka-crash-report.xml
)

pause
exit
