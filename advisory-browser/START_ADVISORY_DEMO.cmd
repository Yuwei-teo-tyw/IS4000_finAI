@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; try { $c=Get-Content -LiteralPath 'demo-config.json' -Raw | ConvertFrom-Json; $p=Join-Path $c.project_root 'backend/.venv/Scripts/python.exe'; if (-not (Test-Path -LiteralPath $p)) { throw 'PYTHON_ENVIRONMENT_UNAVAILABLE' }; & $p -B launcher.py start; exit $LASTEXITCODE } catch { Write-Host 'HOLD: Demo configuration or environment unavailable.'; exit 1 }"
set "demo_exit=%errorlevel%"
if not "%demo_exit%"=="0" pause
endlocal & exit /b %demo_exit%
