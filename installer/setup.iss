; Inno Setup script: installs AlaEhBackup.exe per-user (no admin rights needed).
; ExeName / AppIdGuid can be overridden (/DExeName=... /DAppIdGuid=...) to test an install without touching a real one.
#ifndef AppVersion
  #define AppVersion "1.3.2"
#endif
#ifndef ExeName
  #define ExeName "AlaEhBackup.exe"
#endif
#ifndef AppIdGuid
  #define AppIdGuid "6F0B7C0E-3D1A-4C6B-9A55-0A1AE4BACC01"
#endif

[Setup]
AppId={{{#AppIdGuid}}
AppName=Ala Eh! File Backup
AppVersion={#AppVersion}
AppPublisher=Ala Eh
DefaultDirName={autopf}\Ala Eh File Backup
DefaultGroupName=Ala Eh File Backup
PrivilegesRequired=lowest
OutputDir=out
OutputBaseFilename=AlaEhBackup-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#ExeName}
CloseApplications=yes

[Files]
Source: "out\{#ExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Ala Eh! File Backup"; Filename: "{app}\{#ExeName}"
Name: "{autodesktop}\Ala Eh! File Backup"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
; After a silent self-update (started from inside the app) reopen the app; a normal install shows the checkbox below.
Filename: "{app}\{#ExeName}"; Flags: nowait; Check: WizardSilent
Filename: "{app}\{#ExeName}"; Description: "Open Ala Eh! File Backup now"; Flags: nowait postinstall skipifsilent

[Code]
// The packaged exe is a wrapper process plus the app, and an old copy that did not close (or an older updater that
// could not close it) locks the file this installer replaces. Stop every running copy first, whatever started this.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "{#ExeName}"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(2000);
  Result := '';
end;
