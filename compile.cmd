@echo off
setlocal DisableDelayedExpansion
set "WINLOCK_BUILD_FILE=%~f0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "try { $file = $env:WINLOCK_BUILD_FILE; $sections = [IO.File]::ReadAllText($file) -split '(?m)^# PowerShell build\r?$', 2; & ([scriptblock]::Create($sections[1])) ([IO.Path]::GetDirectoryName($file)) } catch { [Console]::Error.WriteLine('[ERROR] ' + $_.Exception.Message); exit 1 }"
exit /b %errorlevel%

# PowerShell build
param([string] $ProjectRoot, [switch] $Elevated)

$ErrorActionPreference = 'Stop'

try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        if ($Elevated) {
            throw 'The build did not receive administrator privileges.'
        }

        Write-Host 'Requesting administrator privileges for the build...'
        # Encode the path and script so the UAC relaunch never treats the path as command syntax.
        $encodedRoot = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($ProjectRoot))
        $command = "& {`n$($MyInvocation.MyCommand.ScriptBlock)`n} ([Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('$encodedRoot'))) -Elevated"
        $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
        $process = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') `
            -ArgumentList '-NoProfile', '-NonInteractive', '-EncodedCommand', $encodedCommand `
            -WorkingDirectory $env:SystemRoot -Verb RunAs -Wait -PassThru
        exit $process.ExitCode
    }

    Set-Location -LiteralPath $ProjectRoot
    foreach ($file in 'main.py', 'winlock.ico') {
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $file) -PathType Leaf)) {
            throw "$file not found in $ProjectRoot."
        }
    }

    $python = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $python) {
        throw 'Python was not found on PATH.'
    }

    $nuitkaArguments = @(
        '--onefile'
        '--msvc=latest'
        '--windows-console-mode=disable'
        '--windows-icon-from-ico=winlock.ico'
        '--enable-plugin=tk-inter'
        '--windows-uac-admin'
        '--include-data-files=winlock.ico=winlock.ico'
        '--output-filename=WinLock.exe'
        '--remove-output'
        'main.py'
    )

    & $python.Source -m nuitka @nuitkaArguments
    if ($LASTEXITCODE -ne 0) {
        [Console]::Error.WriteLine('[ERROR] Nuitka build failed.')
        exit $LASTEXITCODE
    }
    $output = Join-Path $ProjectRoot 'WinLock.exe'
    if (-not (Test-Path -LiteralPath $output -PathType Leaf)) {
        throw 'Nuitka finished without producing WinLock.exe.'
    }

    Write-Host "Build complete: $output"
    exit 0
} catch {
    [Console]::Error.WriteLine('[ERROR] ' + $_.Exception.Message)
    exit 1
}
