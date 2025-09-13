@echo off
SETLOCAL

REM --- Variables ---
SET PYARMOR_PATH=C:\Users\Nitropc\AppData\Roaming\Python\Python313\Scripts\pyarmor.exe
SET EXE_NAME=WinLock.exe

REM --- Step 1: Check required files ---
IF NOT EXIST main.py (
    echo ERROR: main.py not found!
    pause
    exit /b
)
IF NOT EXIST winlock.ico (
    echo ERROR: winlock.ico not found!
    pause
    exit /b
)

REM --- Step 2: Delete old dist folder ---
IF EXIST dist (
    echo Deleting old dist folder...
    rmdir /s /q dist
)
IF EXIST build (
    echo Deleting old build folder...
    rmdir /s /q build
)

REM --- Step 3: PyArmor generate runtime ---
echo Running PyArmor...
"%PYARMOR_PATH%" gen --enable-jit .\main.py
IF %ERRORLEVEL% NEQ 0 (
    echo PyArmor failed!
    pause
    exit /b
)

REM --- Step 4: PyInstaller build ---
echo Running PyInstaller...
pyinstaller --onefile --windowed --name WinLock --uac-admin --icon=winlock.ico ^
--add-data "winlock.ico;." ^
--add-data "dist\pyarmor_runtime_000000;pyarmor_runtime_000000" ^
--hidden-import psutil ^
--hidden-import subprocess ^
--hidden-import threading ^
--hidden-import tkinter ^
--hidden-import tkinter.ttk ^
--hidden-import tkinter.messagebox ^
--hidden-import locale ^
--hidden-import ctypes ^
--hidden-import ctypes.wintypes ^
--hidden-import os ^
--hidden-import sys ^
--hidden-import time ^
--clean dist\main.py

IF %ERRORLEVEL% NEQ 0 (
    echo PyInstaller failed!
    pause
    exit /b
)

REM --- Step 5: Move exe to root and clean up ---
IF EXIST dist\%EXE_NAME% (
    echo Moving executable to root folder...
    move /Y dist\%EXE_NAME% .\%EXE_NAME%
)

echo Cleaning up dist, build & PyInstaller dust files...
rmdir /s /q dist
rmdir /s /q build
IF EXIST WinLock.spec del /f /q WinLock.spec
echo.
echo Build complete! %EXE_NAME% is ready.
echo.
pause
exit