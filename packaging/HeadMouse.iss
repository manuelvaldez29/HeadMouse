#ifndef AppVersion
  #error AppVersion is required. Run build_windows.ps1.
#endif
#ifndef AppDist
  #error AppDist is required. Run build_windows.ps1.
#endif
[Setup]
AppId={{D8CA3B99-415A-4FA9-90D4-94E3E66B9D67}
AppName=HeadMouse
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
VersionInfoDescription=Instalador HeadMouse
AppPublisher=HeadMouse — UNSTA
DefaultDirName={localappdata}\Programs\HeadMouse
DefaultGroupName=HeadMouse
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir=..\dist\installer
OutputBaseFilename=HeadMouse-Setup-{#AppVersion}-win64
SetupIconFile=..\assets\headmouse.ico
UninstallDisplayIcon={app}\HeadMouse.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; Flags: unchecked
[Files]
Source: "{#AppDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\WINDOWS_USER_MANUAL.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\WINDOWS_QUICK_START.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\Manual.html"; DestDir: "{app}\docs"; Flags: ignoreversion
[Icons]
Name: "{group}\HeadMouse"; Filename: "{app}\HeadMouse.exe"
Name: "{group}\Desinstalar HeadMouse"; Filename: "{uninstallexe}"
Name: "{group}\Manual de HeadMouse"; Filename: "{app}\docs\Manual.html"
Name: "{autodesktop}\HeadMouse"; Filename: "{app}\HeadMouse.exe"; Tasks: desktopicon
[Registry]
; No crea ni activa Run al instalar. La app registra HeadMouse sólo si se elige.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "HeadMouse"; Flags: uninsdeletevalue
[Run]
Filename: "{app}\HeadMouse.exe"; Description: "Abrir HeadMouse"; Flags: nowait postinstall skipifsilent unchecked
; No se elimina %LOCALAPPDATA%\HeadMouse: conserva perfiles y preferencias.
; Una actualización en la misma carpeta conserva Run. Si cambia la ruta,
; el usuario puede elegir la nueva ubicación desde Inicio y accesibilidad.
