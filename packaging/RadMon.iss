#define AppName "RadMon"
#define AppExeName "RadMon.exe"

[Setup]
AppId={{8D9CB0BD-9C4B-4ABF-92B6-89A30B1D936A}
AppName={#AppName}
AppVerName={#AppName}
DefaultDirName={localappdata}\RadMon
DefaultGroupName=RadMon
DisableProgramGroupPage=yes
PrivilegesRequired=admin
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
Source: "packaging\install_server.ps1"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall

[Icons]
Name: "{autoprograms}\RadMon"; Filename: "{app}\app\{#AppExeName}"; Parameters: "--open-web"; WorkingDir: "{app}"
Name: "{autodesktop}\RadMon"; Filename: "{app}\app\{#AppExeName}"; Parameters: "--open-web"; WorkingDir: "{app}"
Name: "{autoprograms}\RadMon Monitoring"; Filename: "{app}\app\{#AppExeName}"; Parameters: "--open-monitoring"; WorkingDir: "{app}"

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{tmp}\install_server.ps1"" -ExePath ""{app}\app\{#AppExeName}"""; StatusMsg: "Registering RadMon 24/7 server..."; Flags: runhidden waituntilterminated
Filename: "{app}\app\{#AppExeName}"; Parameters: "--open-web"; Description: "Buka RadMon Control Plane"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/End /TN ""RadMon Server"""; Flags: runhidden; RunOnceId: "StopRadMonServer"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ""RadMon Server"""; Flags: runhidden; RunOnceId: "DeleteRadMonServer"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""RadMon Web"""; Flags: runhidden; RunOnceId: "DeleteRadMonWebFirewall"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""RadMon Grafana Monitoring"""; Flags: runhidden; RunOnceId: "DeleteRadMonGrafanaFirewall"
