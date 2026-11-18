#ifndef AppVersion
  #error AppVersion is required. Run build_windows.ps1.
#endif
#ifndef AppDist
  #error AppDist is required. Run build_windows.ps1.
#endif
[Setup]
; Mismo AppId que HeadMouse: una instalación anterior se actualiza a CONFA en lugar de duplicarse.
AppId={{D8CA3B99-415A-4FA9-90D4-94E3E66B9D67}
AppName=CONFA
AppVerName=CONFA {#AppVersion}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
VersionInfoDescription=Instalador CONFA - Controlador Facial y Asistente de voz
AppPublisher=Bloj Gustavo Ivan, Domfrocht Julian Davico, Petrelli Maximo Francesco, Valdez Manuel Ricardo
DefaultDirName={localappdata}\Programs\CONFA
DefaultGroupName=CONFA
; Al actualizar desde HeadMouse se conserva la carpeta de programa, pero el menú Inicio pasa a CONFA.
UsePreviousGroup=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir=..\dist\installer
OutputBaseFilename=CONFA-Setup-{#AppVersion}-win64
SetupIconFile=..\assets\confa.ico
UninstallDisplayIcon={app}\CONFA.exe
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
[InstallDelete]
; Restos de HeadMouse (nombre anterior): ejecutable y accesos directos viejos.
Type: files; Name: "{app}\HeadMouse.exe"
Type: files; Name: "{group}\HeadMouse.lnk"
Type: files; Name: "{group}\Desinstalar HeadMouse.lnk"
Type: files; Name: "{group}\Manual de HeadMouse.lnk"
Type: filesandordirs; Name: "{autoprograms}\HeadMouse"
Type: files; Name: "{autodesktop}\HeadMouse.lnk"
[Files]
Source: "{#AppDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\WINDOWS_USER_MANUAL.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\WINDOWS_QUICK_START.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\Manual.html"; DestDir: "{app}\docs"; Flags: ignoreversion
[Icons]
Name: "{group}\CONFA"; Filename: "{app}\CONFA.exe"
Name: "{group}\Desinstalar CONFA"; Filename: "{uninstallexe}"
Name: "{group}\Manual de CONFA"; Filename: "{app}\docs\Manual.html"
Name: "{autodesktop}\CONFA"; Filename: "{app}\CONFA.exe"; Tasks: desktopicon
[Registry]
; No crea ni activa Run al instalar. La app registra CONFA sólo si se elige.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "CONFA"; Flags: uninsdeletevalue
; Quien había elegido "Iniciar HeadMouse con Windows" lo conserva: la entrada vieja apuntaba a
; HeadMouse.exe (que se borra arriba), así que se registra CONFA.exe y se quita la anterior.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "CONFA"; ValueData: """{app}\CONFA.exe"" --autostart"; Check: HadLegacyStartup
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "HeadMouse"; Flags: deletevalue uninsdeletevalue
[Run]
Filename: "{app}\CONFA.exe"; Description: "Abrir CONFA"; Flags: nowait postinstall skipifsilent unchecked
; No se elimina %LOCALAPPDATA%\CONFA: conserva perfiles y preferencias. La app renombra
; %LOCALAPPDATA%\HeadMouse a CONFA la primera vez que se abre.
; Una actualización en la misma carpeta conserva Run. Si cambia la ruta,
; el usuario puede elegir la nueva ubicación desde Inicio y accesibilidad.
[Code]
function HadLegacyStartup: Boolean;
begin
  Result := RegValueExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'HeadMouse');
end;
