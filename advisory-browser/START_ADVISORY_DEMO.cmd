@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; try { $c=Get-Content -LiteralPath 'demo-config.local.json' -Raw | ConvertFrom-Json; $p=Join-Path $c.project_root 'backend/.venv/Scripts/python.exe'; if (-not (Test-Path -LiteralPath $p)) { throw 'PYTHON_ENVIRONMENT_UNAVAILABLE' }; & $p -B launcher.py start; exit $LASTEXITCODE } catch { Write-Host 'HOLD: Copy demo-config.example.json to demo-config.local.json and set project_root to an approved external v5 project with Python 3.12.'; exit 1 }"
set "demo_exit=%errorlevel%"
if not "%demo_exit%"=="0" pause
endlocal & exit /b %demo_exit%
