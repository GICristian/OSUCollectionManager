; Inno Setup 6 — installer Windows (opțional). Instalare per-utilizator, fără admin.
; 1) Rulează .\build_exe.ps1
; 2) Deschide acest fișier în Inno Setup Compiler și actualizează #define MyAppVersion
;    la același număr ca în osc_collector/version.py, apoi Build → Compile.
; Ieșire: installer\Output\OSC_<versiune>_Setup.exe — poți atașa manual la GitHub Release.

#define MyAppName "OSC"
#define MyAppVersion "0.4.2"
#define MyAppPublisher "OSC"
#define MyAppExeName "OSC.exe"

[Setup]
AppId={{A7B8C9D0-E1F2-4A5B-8C9D-0E1F2A3B4C5D}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=OSC_{#MyAppVersion}_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\OSC\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
