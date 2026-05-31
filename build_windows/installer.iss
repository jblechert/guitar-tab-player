; Inno Setup script for Guitar Tab Player
; Compile with Inno Setup 6+: https://jrsoftware.org/isinfo.php
;
; Run build_windows.ps1 first – it calls PyInstaller and then this script.

#define AppName    "Guitar Tab Player"
#define AppVersion "1.0.0"
#define AppPublisher "Guitar Tab Player Contributors"
#define AppURL     "https://github.com/your-repo/guitar-generator"
#define AppExeName "GuitarTabPlayer.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
; Installer output goes to dist/
OutputDir=..\dist
OutputBaseFilename=GuitarTabPlayer-Setup
; Compression
Compression=lzma2/ultra64
SolidCompression=yes
; Require admin for Program Files, fall back to user dir
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
WizardStyle=modern
; Icon
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german";  MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon";  Description: "{cm:CreateDesktopIcon}";  GroupDescription: "{cm:AdditionalIcons}"
Name: "startmenuicon"; Description: "Create Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; PyInstaller output folder (one-folder mode)
Source: "..\dist\GuitarTabPlayer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";   Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[Code]
// Show a friendly message if FluidSynth DLL is missing from the bundle
// (shouldn't happen with the build script, but just in case)
procedure CurStepChanged(CurStep: TSetupStep);
var
  DllPath: string;
begin
  if CurStep = ssPostInstall then begin
    DllPath := ExpandConstant('{app}\fluidsynth.dll');
    if not FileExists(DllPath) then begin
      MsgBox(
        'Note: fluidsynth.dll was not found in the installation folder.' + #13#10 +
        'Audio playback may be silent. You can install FluidSynth manually ' +
        'from https://github.com/FluidSynth/fluidsynth/releases and copy ' +
        'fluidsynth.dll into: ' + ExpandConstant('{app}'),
        mbInformation, MB_OK
      );
    end;
  end;
end;
