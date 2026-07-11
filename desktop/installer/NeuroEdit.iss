; Inno Setup script for the NeuroEdit Windows alpha installer.
; Compile with: ISCC.exe /DMyAppVersion=alpha-001 installer\NeuroEdit.iss
; Produces a friendly double-click Setup.exe wizard for non-technical testers:
; installs per-user (no admin / UAC prompt), adds a Start-menu shortcut, and
; registers an uninstaller in "Apps & features".

#define MyAppName "NeuroEdit"
#ifndef MyAppVersion
  #define MyAppVersion "0.5.5-alpha"
#endif
#define MyAppPublisher "NeuroEdit"
#define MyAppExeName "NeuroEdit.exe"

[Setup]
; Stable AppId so upgrades replace the same install instead of stacking copies.
AppId={{B8E7A1C2-3F4D-4A5B-9C6E-7D8F90A1B2C3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install -> no administrator rights required (friendlier for testers).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\NeuroEdit
DefaultGroupName=NeuroEdit
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=NeuroEdit-{#MyAppVersion}-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\src\neuroedit_desktop\resources\NeuroEdit.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName} {#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
; The whole PyInstaller COLLECT folder produced by NeuroEdit.spec.
Source: "..\dist\NeuroEdit\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\NeuroEdit"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall NeuroEdit"; Filename: "{uninstallexe}"
Name: "{userdesktop}\NeuroEdit"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch NeuroEdit now"; Flags: nowait postinstall skipifsilent
