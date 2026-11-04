param(
    [string]$Iscc = "${env:LOCALAPPDATA}\Programs\Inno Setup 7\ISCC.exe",
    [string]$Python = '.venv\Scripts\python.exe'
)
$ErrorActionPreference='Stop'
$taskProjectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $taskProjectRoot
try {
    $taskPython=(Resolve-Path -LiteralPath $Python).Path
    if (-not (Test-Path -LiteralPath $Iscc)) { throw "Indicar -Iscc con la ruta de ISCC.exe" }
    $taskIscc=(Resolve-Path -LiteralPath $Iscc).Path
    $taskVersion=& $taskPython -c 'from app_paths import VERSION; print(VERSION)'
    if ($LASTEXITCODE -ne 0 -or $taskVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Versión inválida' }
    $taskDist="dist/windows-$taskVersion"
    & $taskPython packaging/prepare_models.py
    if ($LASTEXITCODE -ne 0) { throw 'Falló la preparación de modelos' }
    & $taskPython packaging/build_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el icono' }
    & $taskPython packaging/build_manual.py
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el manual' }
    & $taskPython -m PyInstaller --noconfirm --distpath $taskDist --workpath "build/pyinstaller-$taskVersion" packaging/HeadMouse.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller falló' }
    & $taskIscc "/DAppVersion=$taskVersion" "/DAppDist=$taskProjectRoot\$taskDist\HeadMouse" packaging/HeadMouse.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup falló' }
    & $taskPython packaging/write_manifest.py
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo generar el manifiesto de distribución' }
    Get-Content "dist/SHA256SUMS-$taskVersion.txt"
} finally { Pop-Location }
