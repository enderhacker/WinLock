@echo off
setlocal DisableDelayedExpansion
set "WINLOCK_BUILD_FILE=%~f0"
set "WINLOCK_PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\SysNative\WindowsPowerShell\v1.0\powershell.exe" (
    set "WINLOCK_PS_EXE=%SystemRoot%\SysNative\WindowsPowerShell\v1.0\powershell.exe"
)
if not exist "%WINLOCK_PS_EXE%" (
    for %%I in (powershell.exe pwsh.exe) do (
        if not exist "%WINLOCK_PS_EXE%" if not "%%~$PATH:I"=="" set "WINLOCK_PS_EXE=%%~$PATH:I"
    )
)
if not exist "%WINLOCK_PS_EXE%" (
    echo [ERROR] PowerShell was not found on this system. 1>&2
    exit /b 1
)
"%WINLOCK_PS_EXE%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "try { try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}; $file = $env:WINLOCK_BUILD_FILE; if ([string]::IsNullOrWhiteSpace($file) -or -not (Test-Path -LiteralPath $file -PathType Leaf)) { throw 'Build script path could not be resolved.' }; $sections = [IO.File]::ReadAllText($file, [Text.Encoding]::UTF8) -split '(?m)^# PowerShell build[ \t]*\r?$', 2; if ($sections.Count -lt 2) { throw 'PowerShell build section not found.' }; & ([scriptblock]::Create($sections[1])) -ProjectRoot ([IO.Path]::GetDirectoryName($file)) -ScriptFile $file } catch { [Console]::Error.WriteLine('[ERROR] ' + $_.Exception.Message); exit 1 }"
set "WINLOCK_EXIT=%errorlevel%"
endlocal & exit /b %WINLOCK_EXIT%

# PowerShell build
param(
    [string] $ProjectRoot,
    [string] $ScriptFile,
    [string] $LogFile,
    [string] $PreferredPython,
    [string] $ExtraPath,
    [switch] $Elevated
)

$ErrorActionPreference = 'Stop'

try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$logWriter = $null

function Write-InfoLine([string] $Message) {
    [Console]::Out.WriteLine($Message)
    if ($script:logWriter) {
        $script:logWriter.WriteLine($Message)
    }
}

function Write-ErrorLine([string] $Message) {
    [Console]::Error.WriteLine($Message)
    if ($script:logWriter) {
        $script:logWriter.WriteLine($Message)
    }
}

function Invoke-NativeQuiet {
    param([scriptblock] $Action)
    $prevEap = $ErrorActionPreference
    $hasNativePref = (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) -ne $null
    if ($hasNativePref) {
        $prevNative = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    $ErrorActionPreference = 'Continue'
    try {
        & $Action
    } finally {
        $ErrorActionPreference = $prevEap
        if ($hasNativePref) {
            $PSNativeCommandUseErrorActionPreference = $prevNative
        }
    }
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-MappedDrivePath([string] $PathValue) {
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $PathValue
    }
    if ($PathValue -match '^([A-Za-z]):(.*)$') {
        $drive = Get-PSDrive -Name $Matches[1] -PSProvider FileSystem -ErrorAction SilentlyContinue
        if ($drive -and -not [string]::IsNullOrWhiteSpace($drive.DisplayRoot)) {
            return ($drive.DisplayRoot.TrimEnd('\') + $Matches[2])
        }
    }
    return $PathValue
}

function Test-PythonExecutable([string] $Candidate) {
    if ([string]::IsNullOrWhiteSpace($Candidate)) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
        return $false
    }

    $probe = $null
    $code = 1
    Invoke-NativeQuiet {
        try {
            $script:probeResult = & $Candidate -c "import sys; print('__WINLOCK_PY__=' + sys.executable)" 2>$null
            $script:probeCode = $LASTEXITCODE
        } catch {
            $script:probeResult = $null
            $script:probeCode = 1
        }
    }
    $probe = $script:probeResult
    $code = $script:probeCode

    if ($code -ne 0 -or -not $probe) {
        return $false
    }

    return [bool](($probe | Where-Object { $_ -match '^__WINLOCK_PY__=.+$' } | Select-Object -First 1))
}

function Test-PythonModule([string] $PythonExe, [string] $ModuleName) {
    $script:modCode = 1
    Invoke-NativeQuiet {
        try {
            & $PythonExe -c "import $ModuleName" 2>$null | Out-Null
            $script:modCode = $LASTEXITCODE
        } catch {
            $script:modCode = 1
        }
    }
    return ($script:modCode -eq 0)
}

function Get-PythonMinorVersion([string] $PythonExe) {
    $script:pyVer = $null
    Invoke-NativeQuiet {
        try {
            $out = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                $script:pyVer = [version](($out | Select-Object -First 1).Trim())
            }
        } catch {
            $script:pyVer = $null
        }
    }
    return $script:pyVer
}

function Test-NuitkaSupportsConsoleMode([string] $PythonExe) {
    $script:supportsConsoleMode = $true
    Invoke-NativeQuiet {
        try {
            $verLine = (& $PythonExe -m nuitka --version 2>$null | Select-Object -First 1)
            if ($LASTEXITCODE -eq 0 -and $verLine -match '(\d+)\.(\d+)') {
                $v = [version]"$($Matches[1]).$($Matches[2])"
                $script:supportsConsoleMode = ($v -ge [version]'2.1')
            }
        } catch {
        }
    }
    return $script:supportsConsoleMode
}

function Find-BuildPython([string] $RootPath, [string] $FirstChoice) {
    $candidates = New-Object System.Collections.Generic.List[string]
    $seen = New-Object System.Collections.Generic.HashSet[string] ([StringComparer]::OrdinalIgnoreCase)

    $addCandidate = {
        param([string] $PathItem)
        if ([string]::IsNullOrWhiteSpace($PathItem)) { return }
        try {
            $full = [IO.Path]::GetFullPath($PathItem.Trim('"'))
        } catch {
            return
        }
        if ($seen.Add($full)) {
            [void]$candidates.Add($full)
        }
    }

    & $addCandidate $FirstChoice

    if (-not [string]::IsNullOrWhiteSpace($env:VIRTUAL_ENV)) {
        & $addCandidate (Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe')
    }
    if (-not [string]::IsNullOrWhiteSpace($env:CONDA_PREFIX)) {
        & $addCandidate (Join-Path $env:CONDA_PREFIX 'python.exe')
    }

    foreach ($venvDir in '.venv', 'venv', '.env', 'env') {
        & $addCandidate (Join-Path (Join-Path $RootPath $venvDir) 'Scripts\python.exe')
    }

    foreach ($cmdName in 'python.exe', 'python3.exe') {
        $cmds = Get-Command $cmdName -All -CommandType Application -ErrorAction SilentlyContinue
        foreach ($cmd in $cmds) {
            & $addCandidate $cmd.Source
        }
    }

    $pyLauncher = Get-Command 'py.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $pyExe = if ($pyLauncher) { $pyLauncher.Source } elseif (Test-Path -LiteralPath (Join-Path $env:SystemRoot 'py.exe') -PathType Leaf) { Join-Path $env:SystemRoot 'py.exe' } else { $null }
    if ($pyExe) {
        Invoke-NativeQuiet {
            try {
                $pyDefault = & $pyExe -3 -c "import sys; print('__WINLOCK_PY__=' + sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $pyDefault) {
                    foreach ($line in $pyDefault) {
                        if ($line -match '^__WINLOCK_PY__=(.+)$') {
                            & $addCandidate $Matches[1]
                        }
                    }
                }
                $pyList = & $pyExe -0p 2>$null
                if ($LASTEXITCODE -eq 0 -and $pyList) {
                    foreach ($line in $pyList) {
                        if ($line -match '([A-Za-z]:\\[^\r\n*?<>|"]+?python\.exe)') {
                            & $addCandidate $Matches[1]
                        }
                    }
                }
            } catch {
            }
        }
    }

    foreach ($regPath in @(
        'HKCU:\Software\Python\PythonCore\*\InstallPath',
        'HKLM:\Software\Python\PythonCore\*\InstallPath',
        'HKLM:\Software\WOW6432Node\Python\PythonCore\*\InstallPath'
    )) {
        $keys = Get-Item -Path $regPath -ErrorAction SilentlyContinue
        foreach ($key in $keys) {
            $exeProp = $key.GetValue('ExecutablePath')
            if ($exeProp) { & $addCandidate ([string]$exeProp) }
            $dirProp = $key.GetValue('')
            if ($dirProp) { & $addCandidate (Join-Path ([string]$dirProp) 'python.exe') }
        }
    }

    foreach ($glob in @(
        (Join-Path $env:LocalAppData 'Programs\Python\Python*\python.exe'),
        (Join-Path $env:ProgramFiles 'Python*\python.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Python*\python.exe'),
        (Join-Path $env:SystemDrive 'Python*\python.exe')
    )) {
        if (-not [string]::IsNullOrWhiteSpace($glob)) {
            foreach ($item in (Get-Item -Path $glob -ErrorAction SilentlyContinue)) {
                & $addCandidate $item.FullName
            }
        }
    }

    $workingWithoutNuitka = $null
    foreach ($candidate in $candidates) {
        if (Test-PythonExecutable $candidate) {
            if (Test-PythonModule $candidate 'nuitka') {
                return [PSCustomObject]@{
                    Python    = $candidate
                    HasNuitka = $true
                }
            }
            if (-not $workingWithoutNuitka) {
                $workingWithoutNuitka = $candidate
            }
        }
    }

    return [PSCustomObject]@{
        Python    = $workingWithoutNuitka
        HasNuitka = $false
    }
}

function Test-MsvcInstalled {
    if (Get-Command 'cl.exe' -CommandType Application -ErrorAction SilentlyContinue) {
        return $true
    }
    foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if ([string]::IsNullOrWhiteSpace($base)) { continue }
        $vswhere = Join-Path $base 'Microsoft Visual Studio\Installer\vswhere.exe'
        if (Test-Path -LiteralPath $vswhere -PathType Leaf) {
            $script:foundVs = $null
            Invoke-NativeQuiet {
                try {
                    $script:foundVs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
                    if (-not $script:foundVs) {
                        $script:foundVs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.ARM64 -property installationPath 2>$null
                    }
                } catch {
                    $script:foundVs = $null
                }
            }
            if ($script:foundVs) { return $true }
        }
    }
    return $false
}

function Wait-IfDoubleClicked {
    try {
        if ($env:CI -or $env:GITHUB_ACTIONS -or $env:TF_BUILD -or $env:JENKINS_URL) { return }
        if ([Console]::IsOutputRedirected -or [Console]::IsInputRedirected) { return }
        if ($env:CMDCMDLINE -match '(?i)/c\s+""') {
            Write-Host ''
            Write-Host 'Press any key to exit...'
            $null = [Console]::ReadKey($true)
        }
    } catch {
    }
}

$exitCode = 0

try {
    if ([string]::IsNullOrWhiteSpace($ScriptFile)) {
        $ScriptFile = $env:WINLOCK_BUILD_FILE
    }
    if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
        $ProjectRoot = if ($ScriptFile) { Split-Path -Parent $ScriptFile } else { (Get-Location).Path }
    }

    if (-not (Test-IsAdministrator)) {
        if ($Elevated) {
            throw 'The build did not receive administrator privileges.'
        }

        foreach ($file in 'main.py', 'winlock.ico') {
            $itemPath = Join-Path $ProjectRoot $file
            if (-not (Test-Path -LiteralPath $itemPath -PathType Leaf)) {
                throw "$file not found in $ProjectRoot."
            }
            if ((Get-Item -LiteralPath $itemPath).Length -le 0) {
                throw "$file in $ProjectRoot is empty."
            }
        }

        $resolvedRoot = Resolve-MappedDrivePath $ProjectRoot
        $resolvedScript = Resolve-MappedDrivePath $ScriptFile

        $prePythonResult = Find-BuildPython -RootPath $ProjectRoot -FirstChoice ''
        $prePython = if ($prePythonResult.Python) { $prePythonResult.Python } else { '' }

        $extraDirs = New-Object System.Collections.Generic.List[string]
        if (-not [string]::IsNullOrWhiteSpace($env:VIRTUAL_ENV)) {
            $extraDirs.Add((Join-Path $env:VIRTUAL_ENV 'Scripts'))
        }
        if (-not [string]::IsNullOrWhiteSpace($env:CONDA_PREFIX)) {
            $extraDirs.Add($env:CONDA_PREFIX)
            $extraDirs.Add((Join-Path $env:CONDA_PREFIX 'Scripts'))
        }
        if (-not [string]::IsNullOrWhiteSpace($prePython)) {
            $pyDir = Split-Path -Parent $prePython
            $extraDirs.Add($pyDir)
            $extraDirs.Add((Join-Path $pyDir 'Scripts'))
        }
        $preExtraPath = ($extraDirs | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) } | Select-Object -Unique) -join ';'

        $tempLog = Join-Path ([IO.Path]::GetTempPath()) ('winlock-build-' + [Guid]::NewGuid().ToString('N') + '.log')
        $null = New-Item -ItemType File -Path $tempLog -Force
        try {
            $acl = Get-Acl -LiteralPath $tempLog
            $adminSid = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($adminSid, 'Modify', 'Allow')
            $acl.SetAccessRule($rule)
            Set-Acl -LiteralPath $tempLog -AclObject $acl
        } catch {
        }

        Write-Host 'Requesting administrator privileges for the build...'

        $ctx = [ordered]@{
            r = $resolvedRoot
            s = $resolvedScript
            l = $tempLog
            p = $prePython
            x = $preExtraPath
        } | ConvertTo-Json -Compress
        $ctxB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($ctx))

        $bootstrap = '$ErrorActionPreference = ''Stop''; $c = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(''__CTX__'')) | ConvertFrom-Json; try { $s = [IO.File]::ReadAllText($c.s, [Text.Encoding]::UTF8) -split ''(?m)^# PowerShell build[ \t]*\r?$'', 2; if ($s.Count -lt 2) { throw ''PowerShell build section not found.'' }; & ([scriptblock]::Create($s[1])) -ProjectRoot $c.r -ScriptFile $c.s -LogFile $c.l -PreferredPython $c.p -ExtraPath $c.x -Elevated } catch { try { [IO.File]::AppendAllText($c.l, ''[ERROR] '' + $_.Exception.Message + [Environment]::NewLine, [Text.Encoding]::UTF8) } catch {}; exit 1 }'.Replace('__CTX__', $ctxB64)
        $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($bootstrap))

        $psExe = Join-Path $PSHOME 'powershell.exe'
        if (-not (Test-Path -LiteralPath $psExe -PathType Leaf)) {
            $psExe = Join-Path $PSHOME 'pwsh.exe'
        }
        if (-not (Test-Path -LiteralPath $psExe -PathType Leaf)) {
            $psExe = (Get-Process -Id $PID).Path
        }

        try {
            $process = $null
            try {
                $process = Start-Process -FilePath $psExe `
                    -ArgumentList '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encodedCommand `
                    -WorkingDirectory $env:SystemRoot -Verb RunAs -Wait -PassThru
            } catch [System.ComponentModel.Win32Exception] {
                if ($_.Exception.NativeErrorCode -eq 1223) {
                    throw 'Administrator elevation was canceled by the user.'
                }
                throw
            } catch {
                if ($_.Exception.InnerException -is [System.ComponentModel.Win32Exception] -and $_.Exception.InnerException.NativeErrorCode -eq 1223) {
                    throw 'Administrator elevation was canceled by the user.'
                }
                throw
            }

            $elevatedExit = if ($null -eq $process -or $null -eq $process.ExitCode) { 1 } else { [int]$process.ExitCode }

            $hasOutput = $false
            if (Test-Path -LiteralPath $tempLog -PathType Leaf) {
                $lines = [IO.File]::ReadAllLines($tempLog, [Text.Encoding]::UTF8)
                foreach ($line in $lines) {
                    $hasOutput = $true
                    if ($line.StartsWith('[ERROR]')) {
                        [Console]::Error.WriteLine($line)
                    } else {
                        [Console]::Out.WriteLine($line)
                    }
                }
            }

            if ($elevatedExit -ne 0 -and -not $hasOutput) {
                [Console]::Error.WriteLine("[ERROR] Elevated build process failed with exit code $elevatedExit.")
            }

            $exitCode = $elevatedExit
        } finally {
            if (Test-Path -LiteralPath $tempLog -PathType Leaf) {
                Remove-Item -LiteralPath $tempLog -Force -ErrorAction SilentlyContinue
            }
        }
    } else {
        if (-not [string]::IsNullOrWhiteSpace($LogFile)) {
            $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            $logWriter = New-Object System.IO.StreamWriter($LogFile, $false, $utf8NoBom)
            $logWriter.AutoFlush = $true
        }

        if (-not [string]::IsNullOrWhiteSpace($ExtraPath)) {
            $currentParts = New-Object System.Collections.Generic.HashSet[string] ([StringComparer]::OrdinalIgnoreCase)
            foreach ($p in ($env:PATH -split ';')) {
                if (-not [string]::IsNullOrWhiteSpace($p)) { [void]$currentParts.Add($p.TrimEnd('\')) }
            }
            $prepend = New-Object System.Collections.Generic.List[string]
            foreach ($p in ($ExtraPath -split ';')) {
                if (-not [string]::IsNullOrWhiteSpace($p) -and (Test-Path -LiteralPath $p -PathType Container)) {
                    if ($currentParts.Add($p.TrimEnd('\'))) {
                        $prepend.Add($p)
                    }
                }
            }
            if ($prepend.Count -gt 0) {
                $env:PATH = ($prepend -join ';') + ';' + $env:PATH
            }
        }

        if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
            throw "Project directory not found: $ProjectRoot"
        }

        Set-Location -LiteralPath $ProjectRoot

        if ($ProjectRoot.StartsWith('\\')) {
            Write-InfoLine "[INFO] Building from UNC path ($ProjectRoot). If MSVC/SCons fails, move the project to a local drive."
        }

        foreach ($file in 'main.py', 'winlock.ico') {
            $itemPath = Join-Path $ProjectRoot $file
            if (-not (Test-Path -LiteralPath $itemPath -PathType Leaf)) {
                throw "$file not found in $ProjectRoot."
            }
            if ((Get-Item -LiteralPath $itemPath).Length -le 0) {
                throw "$file in $ProjectRoot is empty."
            }
        }

        $output = Join-Path $ProjectRoot 'WinLock.exe'
        if (Test-Path -LiteralPath $output -PathType Leaf) {
            try {
                $fs = [IO.File]::Open($output, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
                $fs.Close()
            } catch {
                throw "Cannot overwrite $output because it is currently running, locked, or read-only."
            }
        }

        $pyResult = Find-BuildPython -RootPath $ProjectRoot -FirstChoice $PreferredPython
        if (-not $pyResult.Python) {
            throw 'No working Python installation was found (checked virtual environments, PATH, py launcher, and Windows Registry).'
        }
        if (-not $pyResult.HasNuitka) {
            throw "Nuitka is not installed in '$($pyResult.Python)'. Install it with: `"$($pyResult.Python)`" -m pip install nuitka"
        }

        $pythonExe = $pyResult.Python
        if (-not (Test-PythonModule $pythonExe 'tkinter')) {
            throw "The selected Python ('$pythonExe') does not have tkinter installed, which is required by --enable-plugin=tk-inter."
        }

        $pyVer = Get-PythonMinorVersion $pythonExe
        $hasMsvc = Test-MsvcInstalled
        $consoleFlag = if (Test-NuitkaSupportsConsoleMode $pythonExe) { '--windows-console-mode=disable' } else { '--disable-console' }

        Write-InfoLine "[INFO] Using Python: $pythonExe"

        $nuitkaArguments = New-Object System.Collections.Generic.List[string]
        [void]$nuitkaArguments.Add('--onefile')
        if ($hasMsvc) {
            [void]$nuitkaArguments.Add('--msvc=latest')
        } elseif ($pyVer -and $pyVer -ge [version]'3.13') {
            Write-InfoLine '[WARN] Visual Studio C++ Build Tools (MSVC) were not detected. Python 3.13+ on Windows generally requires MSVC.'
        } else {
            Write-InfoLine '[INFO] MSVC not detected; letting Nuitka select/download MinGW64 automatically.'
        }
        [void]$nuitkaArguments.Add('--assume-yes-for-downloads')
        [void]$nuitkaArguments.Add($consoleFlag)
        [void]$nuitkaArguments.Add('--windows-icon-from-ico=winlock.ico')
        [void]$nuitkaArguments.Add('--enable-plugin=tk-inter')
        [void]$nuitkaArguments.Add('--include-data-files=winlock.ico=winlock.ico')
        [void]$nuitkaArguments.Add("--output-dir=$ProjectRoot")
        [void]$nuitkaArguments.Add('--output-filename=WinLock.exe')
        [void]$nuitkaArguments.Add('--remove-output')
        [void]$nuitkaArguments.Add('main.py')

        $script:nuitkaExit = 1
        Invoke-NativeQuiet {
            if ($logWriter) {
                & $pythonExe -m nuitka @nuitkaArguments 2>&1 | ForEach-Object {
                    $text = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" }
                    Write-InfoLine $text
                }
            } else {
                & $pythonExe -m nuitka @nuitkaArguments
            }
            $script:nuitkaExit = $LASTEXITCODE
        }

        if ($script:nuitkaExit -ne 0) {
            if (-not $hasMsvc) {
                Write-ErrorLine '[ERROR] Nuitka build failed. Ensure Visual Studio Build Tools with "Desktop development with C++" is installed (especially for Python 3.13+).'
            } else {
                Write-ErrorLine "[ERROR] Nuitka build failed (exit code $($script:nuitkaExit))."
            }
            $exitCode = if ($script:nuitkaExit) { $script:nuitkaExit } else { 1 }
        } elseif (-not (Test-Path -LiteralPath $output -PathType Leaf) -or (Get-Item -LiteralPath $output).Length -le 0) {
            throw 'Nuitka finished without producing a valid WinLock.exe.'
        } else {
            Write-InfoLine "Build complete: $output"
            $exitCode = 0
        }
    }
} catch {
    Write-ErrorLine ('[ERROR] ' + $_.Exception.Message)
    $exitCode = 1
} finally {
    if ($logWriter) {
        try { $logWriter.Flush(); $logWriter.Dispose() } catch {}
    }
    if (-not $Elevated) {
        Wait-IfDoubleClicked
    }
}

exit $exitCode