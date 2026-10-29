param([string]$Iscc = "${env:LOCALAPPDATA}\Programs\Inno Setup 7\ISCC.exe")
$ErrorActionPreference='Stop'
$taskProjectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $taskProjectRoot
try {
    $taskPython=Join-Path $taskProjectRoot '.venv\Scripts\python.exe'
    & $taskPython packaging/build_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el icono' }
    & $taskPython packaging/build_manual.py
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el manual' }
    & $taskPython -m PyInstaller --noconfirm --distpath dist --workpath build/pyinstaller packaging/HeadMouse.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller falló' }
    if (-not (Test-Path -LiteralPath $Iscc)) { throw "Indicar -Iscc con la ruta de ISCC.exe" }
    & $Iscc packaging/HeadMouse.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup falló' }
    Get-FileHash -Algorithm SHA256 dist/HeadMouse/HeadMouse.exe,dist/installer/HeadMouse-Setup-0.4.0-win64.exe
} finally { Pop-Location }
