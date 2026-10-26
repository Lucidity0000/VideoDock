#define AppVersion "0.6.1"
[Setup]
AppId={{C46AFA27-8D14-4E76-8F34-D2B6C116A93E}
AppName=VideoDock
AppVersion={#AppVersion}
AppPublisher=VideoDock
DefaultDirName={localappdata}\Programs\VideoDock
DefaultGroupName=VideoDock
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=VideoDock-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\VideoDock.exe
CloseApplications=yes

[Files]
Source: "..\dist\VideoDock-{#AppVersion}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CREDITS.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CITATION.cff"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\DISTRIBUTION.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\RELEASE_VALIDATION.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "dependencies.lock.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "inference-runtime.lock.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements-inference.lock.txt"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Icons]
Name: "{group}\VideoDock"; Filename: "{app}\VideoDock.exe"
Name: "{autodesktop}\VideoDock"; Filename: "{app}\VideoDock.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VideoDock.exe"; Description: "Open VideoDock"; Flags: nowait postinstall skipifsilent

