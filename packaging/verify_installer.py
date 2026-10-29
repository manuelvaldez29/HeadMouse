"""Ensayo real de instalación/actualización/desinstalación en build, sin webcam.

Rechaza una instalación de HeadMouse fuera de la carpeta de ensayo o una entrada
Run preexistente. No usa ni modifica perfiles personales. Ejecutar con .venv.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import winreg

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app_paths import data_root
from profiles import ProfileStore
from startup_preferences import WindowsStartup,DEFAULTS
from config import DEFAULT_THRESHOLDS
from user_storage import write_json

RUN_ID=uuid.uuid4().hex[:8]
TARGET=(ROOT/('build/installation-verification-'+RUN_ID)).resolve()
DATA=(ROOT/('build/installation-verification-data-'+RUN_ID)).resolve()
assert TARGET.is_relative_to((ROOT/'build').resolve()) and DATA.is_relative_to((ROOT/'build').resolve())
INSTALLER=ROOT/'dist/installer/HeadMouse-Setup-0.4.0-win64.exe'
KEY=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{D8CA3B99-415A-4FA9-90D4-94E3E66B9D67}_is1'


def installed_path():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as k:return winreg.QueryValueEx(k,'InstallLocation')[0]
    except FileNotFoundError:return None


def hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*.json') if 'logs' not in p.parts}


def main():
    existing=installed_path()
    if existing and Path(existing).resolve()!=TARGET:raise RuntimeError('Existe HeadMouse instalado fuera de build; no se modifica')
    if WindowsStartup().read() is not None:raise RuntimeError('Existe inicio automático real; no se modifica en este ensayo')
    if DATA.exists():raise RuntimeError('El directorio de datos de ensayo ya existe: usar una ejecución nueva y conservar evidencia anterior')
    assert INSTALLER.is_file()
    personal=data_root();before_personal=hashes(personal)
    env=os.environ.copy();env['HEADMOUSE_DATA_DIR']=str(DATA)
    env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
    env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None)
    group='HeadMouse Verification '+uuid.uuid4().hex[:8]
    group_path=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs'/group
    report=dict(installer_sha256=hashlib.sha256(INSTALLER.read_bytes()).hexdigest(),steps=[])
    def run(command,seconds=180):
        p=subprocess.run([str(v) for v in command],env=env,cwd=ROOT/'build',timeout=seconds,capture_output=True)
        report['steps'].append(dict(command=Path(str(command[0])).name,args=list(map(str,command[1:])),exit=p.returncode))
        print(report['steps'][-1],flush=True)
        if p.returncode:raise RuntimeError('Falló proceso: '+str(command[0]))
    options=['/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',f'/DIR={TARGET}',f'/GROUP={group}','/TASKS=']
    run([INSTALLER,*options,'/LOG='+str(ROOT/'data/logs/installer-first-install.txt')])
    assert (TARGET/'HeadMouse.exe').is_file()
    assert (group_path/'HeadMouse.lnk').is_file()
    assert (group_path/'Manual de HeadMouse.lnk').is_file()
    assert installed_path() and Path(installed_path()).resolve()==TARGET
    for flag in ('--check','--verify-runtime','--check-resident'):run([TARGET/'HeadMouse.exe',flag],60)
    assert not list((DATA/'profiles').glob('*.json'))
    runtime=json.loads((DATA/'logs/distribution-check.json').read_text(encoding='utf-8'))
    assert runtime['camera_opened'] is False and runtime['physical_actions']==0
    profile=dict(user_id='installation_verification',display_name='Ensayo automatizado',status='calibrated',
        thresholds=DEFAULT_THRESHOLDS.copy(),neutral_nose_x=.5,neutral_nose_y=.5,settings={},validation=dict(passed=True))
    ProfileStore(DATA/'profiles').save(profile)
    (DATA/'last_profile.json').write_text(json.dumps(dict(user_id=profile['user_id'])),encoding='utf-8')
    write_json(DATA/'startup.json',dict(DEFAULTS,prompted=True,profile_id=profile['user_id']))
    before=hashes(DATA)
    run([INSTALLER,*options,'/LOG='+str(ROOT/'data/logs/installer-update.txt')])
    assert hashes(DATA)==before
    run([TARGET/'HeadMouse.exe','--check-resident'],60)
    assert hashes(DATA)==before
    assert WindowsStartup().read() is None
    run([TARGET/'unins000.exe','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/LOG='+str(ROOT/'data/logs/installer-uninstall.txt')])
    deadline=time.monotonic()+20
    while (TARGET/'HeadMouse.exe').exists() and time.monotonic()<deadline:time.sleep(.2)
    assert not (TARGET/'HeadMouse.exe').exists()
    assert installed_path() is None and WindowsStartup().read() is None
    assert hashes(DATA)==before and hashes(personal)==before_personal
    assert not (group_path/'HeadMouse.lnk').exists()
    report.update(result='passed',profile_preserved=True,preferences_preserved=True,personal_data_unchanged=True,
        shortcuts_verified=True,uninstaller_verified=True,autostart_enabled=False,camera_opened=False,physical_actions=0,
        isolated_python_path=True,clean_machine=False)
    write_json(ROOT/'build/installer-verification.json',report)
    print('PASS: real install, runtime, update, shortcuts, uninstall; user data preserved',flush=True)


if __name__=='__main__':main()
