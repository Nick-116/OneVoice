; Inno Setup script for the Windows installer (built in CI: .github/workflows/release.yml).
#define AppName "OneVoice Sender"
#ifndef AppVersion
  #define AppVersion "1.2.1"
#endif

[Setup]
AppId={{8C2F6A63-1D9E-4B7A-9E43-0E5B7C1D2A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=OneVoice
AppPublisherURL=https://github.com/Nick-116/OneVoice
DefaultDirName={autopf}\OneVoice Sender
DefaultGroupName=OneVoice
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=OneVoiceSender-{#AppVersion}-Windows-Setup
SetupIconFile=..\assets\OneVoice.ico
UninstallDisplayIcon={app}\OneVoiceSender.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\OneVoiceSender\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\OneVoice Sender"; Filename: "{app}\OneVoiceSender.exe"
Name: "{autodesktop}\OneVoice Sender"; Filename: "{app}\OneVoiceSender.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OneVoiceSender.exe"; Description: "Launch OneVoice Sender"; Flags: nowait postinstall skipifsilent
