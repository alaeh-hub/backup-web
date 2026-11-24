; Inno Setup script: installs AlaEhBackup.exe per-user (no admin rights needed).
[Setup]
AppId={{6F0B7C0E-3D1A-4C6B-9A55-0A1AE4BACC01}
AppName=Ala Eh! File Backup
AppVersion=1.0.0
AppPublisher=Ala Eh
DefaultDirName={autopf}\Ala Eh File Backup
DefaultGroupName=Ala Eh File Backup
PrivilegesRequired=lowest
OutputDir=out
OutputBaseFilename=AlaEhBackup-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\AlaEhBackup.exe

[Files]
Source: "out\AlaEhBackup.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Ala Eh! File Backup"; Filename: "{app}\AlaEhBackup.exe"
Name: "{autodesktop}\Ala Eh! File Backup"; Filename: "{app}\AlaEhBackup.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\AlaEhBackup.exe"; Description: "Open Ala Eh! File Backup now"; Flags: nowait postinstall skipifsilent
