; Writing Parrot installer (Inno Setup 6). Built by .github/workflows/release.yml after PyInstaller:
;   iscc /DMyAppVersion=0.1.0 packaging/installer.iss        ->  dist/WritingParrot-Setup-0.1.0.exe
; Add /DNoPersian when the Inno install has no Languages\Persian.isl.
; Saved as UTF-8 with a BOM so Inno reads the Persian messages correctly.

#ifndef MyAppVersion
  #error Pass the version: iscc /DMyAppVersion=0.1.0 packaging/installer.iss
#endif

[Setup]
; Fixed forever: Windows matches upgrades and the uninstaller by this id.
AppId={{F4918BC6-5A0E-484D-85DD-5E0BABF3A2C3}
AppName=Writing Parrot
AppVersion={#MyAppVersion}
AppVerName=Writing Parrot {#MyAppVersion}
DefaultDirName={localappdata}\Programs\Writing Parrot
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=WritingParrot-Setup-{#MyAppVersion}
SetupIconFile=..\booktranscriber\assets\icon.ico
UninstallDisplayIcon={app}\WritingParrot.exe
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
#ifndef NoPersian
Name: "persian"; MessagesFile: "compiler:Languages\Persian.isl"
#endif

[CustomMessages]
english.DeleteDownloads=Also delete the downloads (%1)?%n%nThese are the speech model, the graphics-card support and the AI helper. Choose No to keep them, so a later reinstall doesn't need to download them again.
english.SizeGB=%1 GB
english.SizeMB=%1 MB
#ifndef NoPersian
persian.DeleteDownloads=فایل‌های دانلودشده (%1) هم پاک شوند؟%n%nاین‌ها مدل گفتار، پشتیبانی کارت گرافیک و دستیار هوش مصنوعی‌اند. اگر «خیر» را بزنید می‌مانند تا اگر دوباره نصب کردید، لازم نباشد از نو دانلودشان کنید.
persian.SizeGB=%1 گیگابایت
persian.SizeMB=%1 مگابایت
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\WritingParrot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Writing Parrot"; Filename: "{app}\WritingParrot.exe"
Name: "{autodesktop}\Writing Parrot"; Filename: "{app}\WritingParrot.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\WritingParrot.exe"; Description: "{cm:LaunchProgram,Writing Parrot}"; Flags: postinstall nowait skipifsilent

[Code]
const
  RegKey = 'Software\WritingParrot';
  Marker = '.writingparrot';
  ReparsePoint = $400;    { FILE_ATTRIBUTE_REPARSE_POINT: never follow links out of the folder }

{ Total bytes of the files under Dir; Found turns True when it holds any file. A stale server.pid is not a download. }
function TreeSize(const Dir: String; var Found: Boolean): Int64;
var
  FindRec: TFindRec;
  Path: String;
begin
  Result := 0;
  if FindFirst(AddBackslash(Dir) + '*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          Path := AddBackslash(Dir) + FindRec.Name;
          if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          begin
            if (FindRec.Attributes and ReparsePoint) = 0 then
              Result := Result + TreeSize(Path, Found);
          end
          else if CompareText(FindRec.Name, 'server.pid') <> 0 then
          begin
            Found := True;
            Result := Result + (Int64(FindRec.SizeHigh) shl 32) + FindRec.SizeLow;
          end;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

{ "4.8 GB" or "350 MB", in the uninstaller's language. }
function SizeText(Bytes: Int64): String;
var
  MB: Int64;
begin
  MB := Bytes div (1024 * 1024);
  if MB >= 1024 then
    Result := FmtMessage(CustomMessage('SizeGB'), [IntToStr(MB div 1024) + '.' + IntToStr((MB mod 1024) * 10 div 1024)])
  else
    Result := FmtMessage(CustomMessage('SizeMB'), [IntToStr(MB)]);
end;

procedure DeleteDownloads(const Downloads, AppData: String);
begin
  DelTree(Downloads + '\models', True, True, True);
  DelTree(Downloads + '\gpu', True, True, True);
  DelTree(Downloads + '\llm', True, True, True);
  DeleteFile(Downloads + '\' + Marker);
  RemoveDir(Downloads);                         { only goes when empty }

  { The app folder: settings, recents, logs and the helper's pid file. The name lists stay. }
  DeleteFile(AppData + '\settings.json');
  DeleteFile(AppData + '\recents.json');
  DelTree(AppData + '\logs', True, True, True);
  DeleteFile(AppData + '\llm\server.pid');
  RemoveDir(AppData + '\llm');
  DeleteFile(AppData + '\' + Marker);           { when it was the downloads folder too }
  RemoveDir(AppData);                           { only goes when empty }

  RegDeleteKeyIncludingSubkeys(HKCU, RegKey);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Downloads, AppData: String;
  Size: Int64;
  Found: Boolean;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  AppData := ExpandConstant('{localappdata}\WritingParrot');
  { No value on a default install: the downloads are in the app folder until setup sets one. }
  if not RegQueryStringValue(HKCU, RegKey, 'DownloadsDir', Downloads) or (Trim(Downloads) = '') then
    Downloads := AppData;
  Downloads := RemoveBackslashUnlessRoot(Trim(Downloads));
  if not DirExists(Downloads) then
    Exit;
  { A folder elsewhere is ours only with the marker the app writes there, so a stray value can't empty someone's models\. }
  if (CompareText(Downloads, AppData) <> 0) and not FileExists(Downloads + '\' + Marker) then
    Exit;

  Found := False;
  Size := TreeSize(Downloads + '\models', Found) + TreeSize(Downloads + '\gpu', Found) + TreeSize(Downloads + '\llm', Found);
  if not Found then
    Exit;     { nothing to ask about }

  if SuppressibleMsgBox(FmtMessage(CustomMessage('DeleteDownloads'), [SizeText(Size)]),
                        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
    DeleteDownloads(Downloads, AppData);
end;
