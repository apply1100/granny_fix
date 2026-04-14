$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonwPath = Join-Path $projectRoot ".venv312\Scripts\pythonw.exe"

New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot "memory") | Out-Null
Set-Location $projectRoot

$existing = Get-Process python, pythonw -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like "$projectRoot\.venv312\Scripts\python*.exe"
}

if ($existing) {
    $existing | Stop-Process -Force
    Start-Sleep -Seconds 1
}

Start-Process -FilePath $pythonwPath -ArgumentList "bot.py" -WorkingDirectory $projectRoot -WindowStyle Hidden
