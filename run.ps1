param([string]$OutputRoot = 'E:\0\laobaiSave')
$ErrorActionPreference = 'Stop'
$Py = Join-Path $OutputRoot '_tool\.venv\Scripts\python.exe'
$Runner = Join-Path $OutputRoot '_tool\laobai-browser-v23.py'
if (-not (Test-Path -LiteralPath $Py -PathType Leaf)) { throw "Python environment not found. Run setup.ps1 first: $Py" }
if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) { throw "v2.3 runner not found. Run setup.ps1 first: $Runner" }
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; $env:NO_COLOR='1'; $env:TERM='dumb'
& $Py -u $Runner
exit $LASTEXITCODE
