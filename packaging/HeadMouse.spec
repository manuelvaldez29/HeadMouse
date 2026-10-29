# PyInstaller onedir, Windows x64. Ejecutar desde la raíz del repositorio.
from pathlib import Path
import os,sys
from PyInstaller.utils.hooks import collect_all,copy_metadata
root=Path(SPECPATH).parent
# Evitar DLL ajenas (p.ej. Poppler/ICU) del PATH del equipo de compilación.
windows=Path(os.environ['SystemRoot'])
os.environ['PATH']=os.pathsep.join([str(Path(sys.executable).parent),sys.base_prefix,str(windows/'System32'),str(windows)])
datas=[(str(root/'desktop/theme.qss'),'desktop'),(str(root/'assets'),'assets'),
       (str(root/'models/face_landmarker.task'),'models')]
binaries=[];hidden=[]
for package in ('mediapipe','cv2'):
    d,b,h=collect_all(package);datas+=d;binaries+=b;hidden+=h
for distribution in ('mediapipe','opencv-contrib-python','numpy','PySide6','PyAutoGUI'):
    datas+=copy_metadata(distribution)
a=Analysis([str(root/'app.py')],pathex=[str(root)],binaries=binaries,datas=datas,
    hiddenimports=hidden+['PySide6.QtNetwork','PySide6.QtSvg','pyautogui._pyautogui_win'],
    excludes=['pytest','IPython','PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtPdf'],
    hooksconfig={'matplotlib': {'backends': ['Agg']}},
    noarchive=False)
# Qt usa la API ICU de Windows. No distribuir una icuuc.dll de otra herramienta.
a.binaries=[row for row in a.binaries if Path(row[0]).name.lower() not in ('icuuc.dll','icuin.dll','icudt.dll')]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='HeadMouse',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False,
    icon=str(root/'assets/headmouse.ico'),version=str(root/'packaging/version_info.txt'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='HeadMouse')
