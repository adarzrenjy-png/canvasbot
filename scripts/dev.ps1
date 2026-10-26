# Start Jig in development mode (Windows PowerShell). Same as: py scripts\jig.py dev
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path (Join-Path $root "scripts") "jig.py"
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { & py -3 $launcher dev @args } else { & python $launcher dev @args }
exit $LASTEXITCODE
