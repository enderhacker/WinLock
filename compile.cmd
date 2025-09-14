:: WINLOCK COMPILER (main.py to winlock.exe)

@echo off
SETLOCAL

REM --- Variables ---
SET EXE_NAME=WinLock.exe
echo [DEBUG] EXE_NAME=%EXE_NAME%

REM --- Step 0: Check if pyarmor and pyinstaller exists ---
echo [DEBUG] Checking for PyArmor...
pyarmor -h >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] pyarmor not found! Try: pip install pyarmor
    pause
    exit /b
)
echo [DEBUG] Checking for PyInstaller...
pyinstaller -h >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] pyinstaller not found! Try: pip install pyinstaller
    pause
    exit /b
)

REM --- Step 1: Check required files ---
echo [DEBUG] Checking required files...
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

REM --- Step 2: Delete old dist/build ---
IF EXIST dist (
    echo [DEBUG] Deleting old dist folder...
    rmdir /s /q dist
)
IF EXIST build (
    echo [DEBUG] Deleting old build folder...
    rmdir /s /q build
)
IF EXIST WinLock.spec (
    echo [DEBUG] Deleting old WinLock.spec...
    del /f /q WinLock.spec
)

REM --- Step 3: PyArmor generate runtime ---
echo [DEBUG] Running PyArmor...
pyarmor gen --enable-jit .\main.py
echo [DEBUG] PyArmor exited with code %ERRORLEVEL%
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyArmor failed!
    pause
    exit /b
)

REM --- Step 4: PyInstaller build ---
echo [DEBUG] Running PyInstaller...
pyinstaller --onefile --windowed --name WinLock --uac-admin --icon=winlock.ico ^
--add-data "winlock.ico;." ^
--add-data "dist\pyarmor_runtime_000000;pyarmor_runtime_000000" ^
--hidden-import psutil ^
--hidden-import subprocess ^
--hidden-import threading ^
--hidden-import tkinter ^
--hidden-import tkinter.ttk ^
--hidden-import tkinter.messagebox ^
--hidden-import tkinter.simpledialog ^
--hidden-import tkinter.filedialog ^
--hidden-import locale ^
--hidden-import keyboard ^
--hidden-import ctypes ^
--hidden-import ctypes.wintypes ^
--hidden-import os ^
--hidden-import sys ^
--hidden-import time ^
--hidden-import json ^
--hidden-import urllib.request ^
--hidden-import webbrowser ^
--hidden-import datetime ^
--clean dist\main.py

echo [DEBUG] PyInstaller exited with code %ERRORLEVEL%
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller failed!
    pause
    exit /b
)

REM --- Step 5: Move exe to root and clean up ---
IF EXIST dist\%EXE_NAME% (
    echo [DEBUG] Moving executable to root folder...
    move /Y dist\%EXE_NAME% .\%EXE_NAME%
)

echo [DEBUG] Cleaning up dist, build & PyInstaller dust files...
IF EXIST dist (
    rmdir /s /q dist
)
IF EXIST build (
    rmdir /s /q build
)
IF EXIST WinLock.spec del /f /q WinLock.spec
echo.
echo [DEBUG] Build complete! %EXE_NAME% is ready.
echo.
pause
exit
