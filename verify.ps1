param([switch]$LiveSpeech)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

function Invoke-Uv {
    param([string[]]$UvArgs)
    & uv @UvArgs
    if ($LASTEXITCODE -ne 0) { throw "uv command failed: uv $($UvArgs -join ' ')" }
}

Invoke-Uv -UvArgs @("sync", "--extra", "test", "--python", "3.12")
Invoke-Uv -UvArgs @("run", "ruff", "format", "--check", "backend", "travel_mcp", "tests", "scripts")
Invoke-Uv -UvArgs @("run", "ruff", "check", "backend", "travel_mcp", "tests", "scripts")
Invoke-Uv -UvArgs @("run", "pytest", "-q")

if ($LiveSpeech) {
    $env:PYTHONIOENCODING = "utf-8"
    Invoke-Uv -UvArgs @("run", "python", "-m", "scripts.live_speech_smoke")
}
