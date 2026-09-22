param([string]$OutputRoot = 'E:\0\laobaiSave')
$ErrorActionPreference = 'Stop'
$Py = Join-Path $OutputRoot '_tool\.venv\Scripts\python.exe'
$Original = Join-Path $OutputRoot '_tool\download-laobai.py'
if (-not (Test-Path -LiteralPath $Py -PathType Leaf)) { throw 'Python environment not found. Run setup.ps1 first.' }
if (-not (Test-Path -LiteralPath $Original -PathType Leaf)) { throw 'Local checker not found. Run setup.ps1 first.' }
& $Py $Original --check
exit $LASTEXITCODE
