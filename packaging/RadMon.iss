#define AppName "RadMon"
#define AppExeName "RadMon.exe"

[Setup]
AppId={{8D9CB0BD-9C4B-4ABF-92B6-89A30B1D936A}
AppName={#AppName}
DefaultDirName={localappdata}\RadMon
DefaultGroupName=RadMon
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
SourceDir=..
OutputDir=installer
OutputBaseFilename=RadMon-Setup
UninstallDisplayIcon={app}\app\{#AppExeName}

[InstallDelete]
Type: filesandordirs; Name: "{app}\app"

[Dirs]
Name: "{app}\config"; Flags: uninsneveruninstall
Name: "{app}\runtime"; Flags: uninsneveruninstall
Name: "{app}\archives"; Flags: uninsneveruninstall
Name: "{app}\reports"; Flags: uninsneveruninstall

[Files]
Source: "portable\RadMon\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "portable\RadMon\config\.env.example"; DestDir: "{app}\config"; Flags: ignoreversion onlyifdoesntexist
Source: "portable\RadMon\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "portable\RadMon\SHA256SUMS.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\RadMon"; Filename: "{app}\app\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\RadMon"; Filename: "{app}\app\{#AppExeName}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\app\{#AppExeName}"; Description: "Jalankan RadMon"; Flags: nowait postinstall skipifsilent
