; =====================================================================
; EFL_NEXUS Inno Setup Script (.NET 9 Windows Installer)
; =====================================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.0.9"
#endif
#ifndef MyAppBuild
  #define MyAppBuild "0"
#endif
#ifndef SourceDir
  #define SourceDir "dist\EFL_NEXUS"
#endif
#ifndef OutputDir
  #define OutputDir "dist"
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "EFL_NEXUS_Setup_v" + MyAppVersion
#endif

#define MyAppName "EFL NEXUS"
#define MyAppPublisher "EFL 3PL"
#define MyAppURL "https://github.com/akashjay1/EFL_NEXUS"
#define MyAppExeName "EFL_NEXUS.exe"

[Setup]
AppId={{5D9E2F81-8B39-4E64-918E-6C1C52A2D9D1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\EFL_NEXUS
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
SetupIconFile=icon_2.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#MyAppName} v{#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Base files from distribution staging
; Exclude any developer configuration or personal files just in case
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config.json,*.sqlite3*,*.sqlite,sent_log.xlsx,reconciliation_queue.json,*.log,webview_profile\*,whatsapp_gdn\*"

; Templates & Users: ONLY install if they don't already exist on user's machine (never overwrite existing user data!)
Source: "{#SourceDir}\templates.xlsx"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#SourceDir}\variance_templates.xlsx"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#SourceDir}\efl_users.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon_2.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon_2.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\updater.log"
Type: files; Name: "{app}\website_grabber_browser.log"
Type: files; Name: "{app}\*.old"

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  try
    Exec('taskkill.exe', '/F /IM EFL_NEXUS.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill.exe', '/F /IM updater.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  except
  end;
end;
