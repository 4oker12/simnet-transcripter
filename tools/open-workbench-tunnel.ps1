param(
    [Parameter(Mandatory = $true)][string]$Server,
    [Parameter(Mandatory = $true)][int]$Port,
    [string]$User = "root",
    [string]$KeyPath = "$HOME/.ssh/id_ed25519",
    [int]$LocalPort = 8000,
    [int]$RemotePort = 8000
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $KeyPath)) {
    throw "SSH key not found: $KeyPath"
}

Write-Host "Workbench tunnel: http://127.0.0.1:$LocalPort -> $Server`:127.0.0.1:$RemotePort"
Write-Host "Keep this window open while Workbench uses transcription."

& ssh `
    -N `
    -o ExitOnForwardFailure=yes `
    -o ServerAliveInterval=30 `
    -o ServerAliveCountMax=3 `
    -i $KeyPath `
    -p $Port `
    -L "$LocalPort`:127.0.0.1`:$RemotePort" `
    "$User@$Server"

if ($LASTEXITCODE -ne 0) {
    throw "SSH tunnel exited with code $LASTEXITCODE"
}
