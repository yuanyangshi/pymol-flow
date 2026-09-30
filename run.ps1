<#
.SYNOPSIS
    Launches PyMOL with the PyMOL Flow plugin on Windows.
.DESCRIPTION
    Automatically locates pymol.exe from environment variables, PATH,
    or standard Windows installation directories, and executes launch_plugin.py.
#>

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PyMOLArgs
)

$ErrorActionPreference = "Stop"
$ProjectDir = $PSScriptRoot

function Find-PyMOL {
    if ($env:PYMOL_EXE -and (Test-Path $env:PYMOL_EXE)) {
        return $env:PYMOL_EXE
    }
    if ($env:PYMOL_PATH) {
        if (Test-Path $env:PYMOL_PATH) {
            if ((Get-Item $env:PYMOL_PATH).PSIsContainer) {
                $sub = Join-Path $env:PYMOL_PATH "pymol.exe"
                if (Test-Path $sub) { return $sub }
            } else {
                return $env:PYMOL_PATH
            }
        }
    }

    $cmd = Get-Command "pymol.exe" -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $candidates = @(
        "C:\Program Files\PyMOL\PyMOL.exe",
        "C:\Program Files (x86)\PyMOL\PyMOL.exe",
        "$env:LOCALAPPDATA\Programs\PyMOL\PyMOL.exe"
    )
    foreach ($cand in $candidates) {
        if (Test-Path $cand) {
            return $cand
        }
    }

    # Dynamically search virtual environments on current drive and user profile
    $driveRoot = Split-Path (Get-Location) -Qualifier
    $venvRoots = @("$driveRoot\.virtualenvs", "$env:USERPROFILE\.virtualenvs")
    foreach ($vr in $venvRoots) {
        if (Test-Path $vr) {
            $venvDirs = Get-ChildItem -Path $vr -Directory -ErrorAction SilentlyContinue
            foreach ($vd in $venvDirs) {
                $cand = Join-Path $vd.FullName "Scripts\pymol.exe"
                if (Test-Path $cand) {
                    return $cand
                }
            }
        }
    }

    $schrodinger = Get-ChildItem "C:\Program Files\Schrodinger*" -ErrorAction SilentlyContinue
    foreach ($dir in $schrodinger) {
        $cand = Join-Path $dir.FullName "pymol.exe"
        if (Test-Path $cand) {
            return $cand
        }
    }

    return $null
}

$PyMOLExe = Find-PyMOL

if (-not $PyMOLExe) {
    Write-Error @"
[Error] PyMOL executable was not found on your system.
Please install PyMOL or set the PYMOL_PATH environment variable.
Example: `$env:PYMOL_PATH = 'C:\Program Files\PyMOL\PyMOL.exe'
"@
    exit 1
}

$LauncherScript = Join-Path $ProjectDir "launch_plugin.py"
Write-Host "Launching PyMOL Flow using: $PyMOLExe"

$allArgs = @("-x", "-r", $LauncherScript) + $PyMOLArgs
& $PyMOLExe $allArgs
exit $LASTEXITCODE
