$ErrorActionPreference = "Stop"

$repo   = "24R0qu3/Hive"
$binary = "hive-windows-latest.exe"
$installDir = "$env:USERPROFILE\bin"
$url  = "https://github.com/$repo/releases/latest/download/$binary"
$dest = "$installDir\hive.exe"

Write-Host "Downloading hive..."
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Invoke-WebRequest -Uri $url -OutFile $dest

$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$installDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$installDir;$userPath", "User")
    Write-Host "Added $installDir to your user PATH. Restart your terminal to apply."
}

Write-Host "Installed to $dest"
