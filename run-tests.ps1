param(
    [switch]$VerboseTests = $true
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$pythonCandidates = @()

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $pythonCandidates += $venvPython
}

$localPythonBin = Join-Path $env:LOCALAPPDATA "Python\bin\python.exe"
if (Test-Path $localPythonBin) {
    $pythonCandidates += $localPythonBin
}

$pythonCandidates += "python"

$pythonExe = $null
foreach ($candidate in $pythonCandidates) {
    try {
        if ($candidate -eq "python") {
            $pythonCommand = Get-Command python -ErrorAction Stop
            if ($pythonCommand.Source -like "*WindowsApps*") {
                continue
            }
        }

        & $candidate -V *> $null
        $pythonExe = $candidate
        break
    } catch {
        continue
    }
}

if (-not $pythonExe) {
    Write-Error "Kein nutzbarer Python-Interpreter gefunden. Installiere Python oder erstelle .venv."
    exit 1
}

Write-Host "Python: $pythonExe"

$testArgs = @("-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py")
if ($VerboseTests) {
    $testArgs += "-v"
}

& $pythonExe @testArgs
exit $LASTEXITCODE
