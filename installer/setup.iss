; Inno Setup script: installs AlaEhBackup.exe per-user (no admin rights needed).
; ExeName / AppIdGuid can be overridden (/DExeName=... /DAppIdGuid=...) to test an install without touching a real one.
#ifndef AppVersion
  #define AppVersion "1.8.0"
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
WizardSizePercent=110
; Black + yellow artwork drawn from app.ico by installer/make_images.py (several sizes for high-DPI screens).
WizardImageFile=assets\side.bmp,assets\side-125.bmp,assets\side-150.bmp,assets\side-200.bmp
WizardSmallImageFile=assets\small.bmp,assets\small-125.bmp,assets\small-150.bmp,assets\small-200.bmp
; Short flow: Welcome -> Installing -> Finish. The folder, Start Menu group and "ready" pages are skipped
; (an existing install keeps its own folder, so updates still land in the right place).
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableWelcomePage=no
DisableReadyPage=yes
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#ExeName}
CloseApplications=yes

[Files]
Source: "out\{#ExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Ala Eh! File Backup"; Filename: "{app}\{#ExeName}"
Name: "{autodesktop}\Ala Eh! File Backup"; Filename: "{app}\{#ExeName}"

[Messages]
WelcomeLabel1=Welcome to Ala Eh! File Backup
WelcomeLabel2=Keep your important files safe with a few clicks.%n%nThis will install Ala Eh! File Backup {#AppVersion} on your PC. It takes less than a minute and needs no administrator rights.
ClickNext=Click Install to get started, or Cancel to exit Setup.
ButtonNext=&Install
FinishedHeadingLabel=You're all set!
FinishedLabel=Ala Eh! File Backup is installed, with shortcuts on your desktop and Start menu.%n%nOpen it now to choose your folders and make your first backup.

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
