param(
    [switch]$Demo,
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

function Invoke-Uv {
    param([string[]]$UvArgs)
    & uv @UvArgs
    if ($LASTEXITCODE -ne 0) { throw "uv command failed: uv $($UvArgs -join ' ')" }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found. Install it from https://docs.astral.sh/uv/getting-started/installation/"
}

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Created .env. Set ARK_API_KEY and SPEECH_API_KEY to enable full live mode."
}

if ($Demo) { $env:VOICE_AGENT_DEMO_MODE = "true" }
Invoke-Uv -UvArgs @("sync", "--extra", "test", "--python", "3.12")
Write-Host "Open http://${HostAddress}:$Port"
Invoke-Uv -UvArgs @("run", "uvicorn", "backend.app.main:app", "--host", $HostAddress, "--port", "$Port")
