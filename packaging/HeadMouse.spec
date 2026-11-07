# PyInstaller onedir, Windows x64. Ejecutar desde la raíz del repositorio.
from pathlib import Path
import json
import os,sys
from importlib.metadata import distributions
from runpy import run_path
from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_all,copy_metadata
root=Path(SPECPATH).parent
version=run_path(str(root/'app_paths.py'))['VERSION']
version_file=Path(CONF['workpath'])/'version_info.txt'
version_file.parent.mkdir(parents=True,exist_ok=True)
version_file.write_text((root/'packaging/version_info.txt').read_text(encoding='utf-8')
    .replace('@VERSION@',version).replace('@VERSION_TUPLE@',str(tuple(map(int,version.split('.')))+(0,))),encoding='utf-8')
# Evitar DLL ajenas (p.ej. Poppler/ICU) del PATH del equipo de compilación.
windows=Path(os.environ['SystemRoot'])
os.environ['PATH']=os.pathsep.join([str(Path(sys.executable).parent),sys.base_prefix,str(windows/'System32'),str(windows)])
datas=[(str(root/'desktop/theme.qss'),'desktop'),(str(root/'assets'),'assets'),
       (str(root/'models/face_landmarker.task'),'models'),(str(root/'config.example.json'),'.'),
       (str(root/'docs/Manual.html'),'docs'),(str(root/'docs/WINDOWS_QUICK_START.md'),'docs'),
       (str(root/'docs/WINDOWS_DEPENDENCIES.md'),'docs'),(str(root/'packaging/model_sources.json'),'models'),
       (str(root/'packaging/licenses'),'licenses')]
model_sources=json.loads((root/'packaging/model_sources.json').read_text(encoding='utf-8'))
for model,source in model_sources['whisper'].items():
    for filename in source['files']:
        datas.append((str(root/'models/whisper'/model/filename),'models/whisper/'+model))
for relative in model_sources['other']:
    if relative!='face_landmarker.task':
        datas.append((str(root/'models'/relative),(Path('models')/relative).parent.as_posix()))
for distribution in distributions():
    for entry in distribution.files or ():
        if '..' not in entry.parts and any(part.lower().startswith(('license','copying','notice','third_party')) for part in entry.parts):
            path=distribution.locate_file(entry)
            if path.is_file():
                datas.append((str(path),'licenses/'+distribution.metadata['Name']+'/'+entry.parent.as_posix()))
binaries=[];hidden=[]
for package in ('mediapipe','cv2'):
    d,b,h=collect_all(package);datas+=d;binaries+=b;hidden+=h
# Dictado por voz (requirements-voice.txt): faster-whisper sobre CTranslate2, VAD Silero
# con onnxruntime, micrófono con sounddevice/PortAudio y foco con UI Automation (comtypes).
# Se importan dentro de funciones: collect_all asegura DLL, datos (el VAD .onnx) y submódulos.
# Los modelos Whisper y WeSpeaker se validan antes de congelar la aplicación.
for package in ('faster_whisper','ctranslate2','onnxruntime','av','tokenizers','_sounddevice_data','sherpa_onnx'):
    d,b,h=collect_all(package);datas+=d;binaries+=b;hidden+=h
for distribution in ('mediapipe','opencv-contrib-python','numpy','PySide6','PyAutoGUI',
                     'faster-whisper','ctranslate2','onnxruntime','av','tokenizers','huggingface-hub',
                     'tqdm','sounddevice','comtypes','sherpa-onnx','sherpa-onnx-core'):
    datas+=copy_metadata(distribution)
a=Analysis([str(root/'app.py')],pathex=[str(root)],binaries=binaries,datas=datas,
    hiddenimports=hidden+['PySide6.QtNetwork','PySide6.QtSvg','pyautogui._pyautogui_win',
                          'dictation','speaker','voice_calibration','sounddevice','comtypes.client','comtypes.stream'],
    excludes=['pytest','IPython','PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtPdf'],
    hooksconfig={'matplotlib': {'backends': ['Agg']}},
    noarchive=False)
# Qt usa la API ICU de Windows. No distribuir una icuuc.dll de otra herramienta.
a.binaries=[row for row in a.binaries if Path(row[0]).name.lower() not in ('icuuc.dll','icuin.dll','icudt.dll')]
# Cachés incidentales bajo los directorios de licencias y bibliotecas de enlace de C/C++.
# El código Python está en PYZ; las DLL de sherpa-onnx siguen en el paquete.
a.datas=[row for row in a.datas if "__pycache__" not in Path(row[0]).parts and
         Path(row[0]).suffix.lower() not in (".pyc",".pyo",".lib")]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='HeadMouse',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False,
    icon=str(root/'assets/headmouse.ico'),version=str(version_file))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='HeadMouse')
