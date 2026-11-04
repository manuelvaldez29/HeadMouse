"""Ensayo real de instalación/actualización/desinstalación en build, sin webcam.

Rechaza una instalación de HeadMouse fuera de la carpeta de ensayo o una entrada
Run preexistente. No usa ni modifica perfiles personales. Ejecutar con .venv.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import winreg

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app_paths import VERSION, data_root
from profiles import ProfileStore
from startup_preferences import WindowsStartup,StartupPreferences
from config import DEFAULT_THRESHOLDS
from user_storage import write_json

RUN_ID=uuid.uuid4().hex[:8]
TARGET=(ROOT/('build/installation-verification-'+RUN_ID)).resolve()
DATA=(ROOT/('build/installation-verification-data-'+RUN_ID)).resolve()
assert TARGET.is_relative_to((ROOT/'build').resolve()) and DATA.is_relative_to((ROOT/'build').resolve())
INSTALLER=ROOT/f'dist/installer/HeadMouse-Setup-{VERSION}-win64.exe'
PORTABLE=ROOT/f'dist/windows-{VERSION}/HeadMouse/HeadMouse.exe'
KEY=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{D8CA3B99-415A-4FA9-90D4-94E3E66B9D67}_is1'


def installed_path():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as k:return winreg.QueryValueEx(k,'InstallLocation')[0]
    except FileNotFoundError:return None


def hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*.json') if 'logs' not in p.parts}

def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


class TestRegistry:
    """Keep a real consent record in test data without registering startup."""
    command=None
    def read(self):
        return self.command
    def set(self,command):
        self.command=command


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous',type=Path,required=True,help='Instalador anterior, 0.4.0')
    parser.add_argument('--audio-fixture',type=Path,help='WAV sintético, mono PCM16 a 16 kHz')
    args=parser.parse_args()
    existing=installed_path()
    if existing and Path(existing).resolve()!=TARGET:raise RuntimeError('Existe HeadMouse instalado fuera de build; no se modifica')
    if WindowsStartup().read() is not None:raise RuntimeError('Existe inicio automático real; no se modifica en este ensayo')
    if DATA.exists():raise RuntimeError('El directorio de datos de ensayo ya existe: usar una ejecución nueva y conservar evidencia anterior')
    previous=args.previous.resolve(strict=True)
    assert INSTALLER.is_file() and PORTABLE.is_file() and previous!=INSTALLER
    personal=data_root();before_personal=hashes(personal)
    env=os.environ.copy();env['HEADMOUSE_DATA_DIR']=str(DATA)
    env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
    env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None)
    if args.audio_fixture:
        env['HEADMOUSE_VERIFY_AUDIO']=str(args.audio_fixture.resolve(strict=True))
    group='HeadMouse Verification '+uuid.uuid4().hex[:8]
    group_path=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs'/group
    report=dict(version=VERSION,data_dir=str(DATA),installer_sha256=sha256(INSTALLER),
                previous_installer_sha256=sha256(previous),portable_sha256=sha256(PORTABLE),steps=[])
    def run(command,seconds=600):
        p=subprocess.run([str(v) for v in command],env=env,cwd=ROOT/'build',timeout=seconds,capture_output=True)
        report['steps'].append(dict(command=Path(str(command[0])).name,args=list(map(str,command[1:])),exit=p.returncode))
        print(report['steps'][-1],flush=True)
        if p.returncode:raise RuntimeError('Falló proceso: '+str(command[0]))
    options=['/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',f'/DIR={TARGET}',f'/GROUP={group}','/TASKS=']
    uninstall_options=['/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART']
    run([INSTALLER,*options,'/LOG='+str(ROOT/f'build/installer-{RUN_ID}-clean.txt')])
    assert sha256(TARGET/'HeadMouse.exe')==report['portable_sha256']
    run([TARGET/'HeadMouse.exe','--check-resident'],60)
    assert not list((DATA/'profiles').glob('*.json')) and WindowsStartup().read() is None
    run([TARGET/'unins000.exe',*uninstall_options])
    assert not (TARGET/'HeadMouse.exe').exists() and installed_path() is None
    run([previous,*options,'/LOG='+str(ROOT/f'build/installer-{RUN_ID}-first.txt')])
    assert (TARGET/'HeadMouse.exe').is_file()
    assert (group_path/'HeadMouse.lnk').is_file()
    assert (group_path/'Manual de HeadMouse.lnk').is_file()
    assert installed_path() and Path(installed_path()).resolve()==TARGET
    run([TARGET/'HeadMouse.exe','--check'],60)
    assert not list((DATA/'profiles').glob('*.json'))
    profile=dict(user_id='installation_verification',display_name='Ensayo automatizado',status='calibrated',
        thresholds=DEFAULT_THRESHOLDS.copy(),neutral_nose_x=.5,neutral_nose_y=.5,
        settings={'voice':{'enabled':False,'model':'small'}},validation=dict(passed=True))
    store=ProfileStore(DATA/'profiles')
    store.save(profile)
    (DATA/'last_profile.json').write_text(json.dumps(dict(user_id=profile['user_id'])),encoding='utf-8')
    consent=StartupPreferences(DATA/'startup.json',TestRegistry())
    consent.save(True,True,False,store.load(profile['user_id']),confirmed=True)
    legacy_log=DATA/'logs'/'legacy-session.log'
    legacy_log.write_text('Registro sintético de 0.4.0\n',encoding='utf-8')
    legacy_log_sha=sha256(legacy_log)
    before=hashes(DATA)
    run([INSTALLER,*options,'/LOG='+str(ROOT/f'build/installer-{RUN_ID}-update.txt')])
    assert hashes(DATA)==before
    assert sha256(TARGET/'HeadMouse.exe')==report['portable_sha256']
    run([TARGET/'HeadMouse.exe','--check'],60)
    run([TARGET/'HeadMouse.exe','--verify-runtime'],300)
    runtime=json.loads((DATA/'logs/distribution-check.json').read_text(encoding='utf-8'))
    assert runtime['version']==VERSION and runtime['python_network_blocked']
    assert runtime['camera_opened'] is False and runtime['physical_actions']==0
    assert runtime['voice']['speaker_model'] and not runtime['voice']['microphone_opened']
    from config import WHISPER_MODELS
    assert set(runtime['voice']['models'])==set(WHISPER_MODELS)
    run([TARGET/'HeadMouse.exe','--check-resident'],60)
    assert hashes(DATA)==before
    assert consent.authorized(consent.load(),store.load(profile['user_id']))
    assert WindowsStartup().read() is None
    run([TARGET/'unins000.exe',*uninstall_options,'/LOG='+str(ROOT/f'build/installer-{RUN_ID}-uninstall.txt')])
    deadline=time.monotonic()+20
    while (TARGET/'HeadMouse.exe').exists() and time.monotonic()<deadline:time.sleep(.2)
    assert not (TARGET/'HeadMouse.exe').exists()
    assert installed_path() is None and WindowsStartup().read() is None
    assert hashes(DATA)==before and hashes(personal)==before_personal
    assert sha256(legacy_log)==legacy_log_sha
    assert not (group_path/'HeadMouse.lnk').exists()
    report.update(result='passed',profile_preserved=True,preferences_preserved=True,personal_data_unchanged=True,
        shortcuts_verified=True,uninstaller_verified=True,autostart_enabled=False,camera_opened=False,physical_actions=0,
        isolated_python_path=True,clean_machine=False,consent_preserved=True,
        existing_log_preserved=True,fresh_install=True,runtime=runtime)
    write_json(ROOT/f'build/installer-verification-{VERSION}.json',report)
    print('PASS: actual 0.4.0 upgrade, voice runtime, shortcuts, uninstall; data preserved',flush=True)


if __name__=='__main__':main()
