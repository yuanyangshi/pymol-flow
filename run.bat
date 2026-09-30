@echo off
setlocal enabledelayedexpansion

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

if defined PYMOL_EXE (
    if exist "%PYMOL_EXE%" (
        goto :launch
    )
)

if defined PYMOL_PATH (
    if exist "%PYMOL_PATH%" (
        set "PYMOL_EXE=%PYMOL_PATH%"
        goto :launch
    )
    if exist "%PYMOL_PATH%\pymol.exe" (
        set "PYMOL_EXE=%PYMOL_PATH%\pymol.exe"
        goto :launch
    )
)

:: Check PATH for pymol.exe
for /f "tokens=*" %%i in ('where pymol.exe 2^>nul') do (
    set "PYMOL_EXE=%%i"
    goto :launch
)

:: Check common Windows installation locations
set "CANDIDATES[0]=C:\Program Files\PyMOL\PyMOL.exe"
set "CANDIDATES[1]=C:\Program Files (x86)\PyMOL\PyMOL.exe"
set "CANDIDATES[2]=%LOCALAPPDATA%\Programs\PyMOL\PyMOL.exe"

for /l %%k in (0,1,2) do (
    call set "TEST_PATH=%%CANDIDATES[%%k]%%"
    if exist "!TEST_PATH!" (
        set "PYMOL_EXE=!TEST_PATH!"
        goto :launch
    )
)

:: Dynamically search virtual environments on current drive and user profile
if exist "%~d0\.virtualenvs" (
    for /d %%e in ("%~d0\.virtualenvs\*") do (
        if exist "%%e\Scripts\pymol.exe" (
            set "PYMOL_EXE=%%e\Scripts\pymol.exe"
            goto :launch
        )
    )
)
if exist "%USERPROFILE%\.virtualenvs" (
    for /d %%e in ("%USERPROFILE%\.virtualenvs\*") do (
        if exist "%%e\Scripts\pymol.exe" (
            set "PYMOL_EXE=%%e\Scripts\pymol.exe"
            goto :launch
        )
    )
)

:: Search Schrödinger installations if any
for /d %%d in ("C:\Program Files\Schrodinger*") do (
    if exist "%%d\pymol.exe" (
        set "PYMOL_EXE=%%d\pymol.exe"
        goto :launch
    )
)

echo [Error] PyMOL executable was not found on your system. >&2
echo Please install PyMOL or set PYMOL_PATH to your PyMOL executable location. >&2
echo Example: set PYMOL_PATH=C:\Program Files\PyMOL\PyMOL.exe >&2
if "%~1"=="" pause
exit /b 1

:launch
echo Launching PyMOL Flow using: "%PYMOL_EXE%"
"%PYMOL_EXE%" -x -r "%PROJECT_DIR%\launch_plugin.py" %*
exit /b %errorlevel%
