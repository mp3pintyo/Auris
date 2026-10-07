#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef PackageDir
  #error PackageDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif

[Setup]
AppId={{A1D49FD0-DA40-47D5-BA33-3AE94FBA14AD}
AppName=Auris
AppVersion={#AppVersion}
AppPublisher=mp3pintyo
AppPublisherURL=https://github.com/mp3pintyo/Auris
AppSupportURL=https://github.com/mp3pintyo/Auris/issues
AppUpdatesURL=https://github.com/mp3pintyo/Auris/releases
DefaultDirName={localappdata}\Programs\Auris
DefaultGroupName=Auris
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=Auris-Setup-{#AppVersion}-x64
SetupIconFile={#PackageDir}\Auris.ico
UninstallDisplayIcon={app}\Auris.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=Auris.exe,python.exe
RestartApplications=no
LicenseFile={#PackageDir}\LICENSE
DisableProgramGroupPage=yes
UsePreviousLanguage=yes

[Languages]
Name: "hungarian"; MessagesFile: "compiler:Languages\Hungarian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Asztali ikon létrehozása"; GroupDescription: "Parancsikonok:"; Flags: checkedonce

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "MicrosoftEdgeWebview2Setup.exe"
Source: "{#PackageDir}\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\Auris"; Filename: "{app}\Auris.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Auris"; Filename: "{app}\Auris.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Auris eltávolítása"; Filename: "{uninstallexe}"

[UninstallDelete]
; Python writes __pycache__ beside the bundled code at runtime; the installer
; never recorded those files. Both folders hold program files only: user data
; and the optional GPU runtime live under LocalAppData\Auris.
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\runtime"

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "A WebView2 alkalmazásablak beállítása…"; Check: NeedsWebView2; Flags: waituntilterminated
Filename: "{app}\Auris.exe"; Description: "Auris elindítása"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsWebView2: Boolean;
var
  Version: String;
begin
  Result := not (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
  if Result then
    Result := not (RegQueryStringValue(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

// Only program files belong to the uninstaller. User data under LocalAppData\Auris is retained.
