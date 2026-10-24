; Writing Parrot installer (Inno Setup 6). Built by .github/workflows/release.yml after PyInstaller:
;   iscc /DMyAppVersion=0.1.0 packaging/installer.iss        ->  dist/WritingParrot-Setup-0.1.0.exe
; Persian comes from packaging/Persian.isl (vendored, see its header); without that file it builds English only.
; Saved as UTF-8 with a BOM so Inno reads the Persian messages correctly.

#ifndef MyAppVersion
  #error Pass the version: iscc /DMyAppVersion=0.1.0 packaging/installer.iss
#endif
#if FileExists(AddBackslash(SourcePath) + "Persian.isl")
  #define HavePersian
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
#ifdef HavePersian
Name: "persian"; MessagesFile: "Persian.isl"
#endif

[CustomMessages]
english.DeleteDownloads=Also delete the downloaded speech and AI files (%1) at %2?%n%nYour settings and recent list are removed too; your saved name lists are kept. Choose No to keep everything, so a later reinstall doesn't need to download again.
english.DeleteSettings=Also delete Writing Parrot's settings, recent list and logs?%n%nYour saved name lists are kept.
english.SizeGB=%1 GB
english.SizeMB=%1 MB
#ifdef HavePersian
persian.DeleteDownloads=فایل‌های گفتار و هوش مصنوعیِ دانلودشده (%1) در %2 هم پاک شوند؟%n%nتنظیمات و فهرست فایل‌های اخیر هم پاک می‌شوند، ولی فهرست‌های نامی که ذخیره کرده‌اید می‌مانند. اگر «خیر» را بزنید همه‌چیز می‌ماند تا اگر دوباره نصب کردید، لازم نباشد از نو دانلود کنید.
persian.DeleteSettings=تنظیمات، فهرست فایل‌های اخیر و گزارش‌های کار طوطی‌نویس هم پاک شوند؟%n%nفهرست‌های نامی که ذخیره کرده‌اید می‌مانند.
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

{ The app folder: settings, recents, logs and the helper's pid file. The name lists stay. }
procedure DeleteAppData(const AppData: String);
begin
  DeleteFile(AppData + '\settings.json');
  DeleteFile(AppData + '\recents.json');
  DelTree(AppData + '\logs', True, True, True);
  DeleteFile(AppData + '\llm\server.pid');
  RemoveDir(AppData + '\llm');
  DeleteFile(AppData + '\' + Marker);           { when it was the downloads folder too }
  RemoveDir(AppData);                           { only goes when empty }
  RegDeleteKeyIncludingSubkeys(HKCU, RegKey);
end;

procedure DeleteDownloads(const Downloads: String);
begin
  DelTree(AddBackslash(Downloads) + 'models', True, True, True);
  DelTree(AddBackslash(Downloads) + 'gpu', True, True, True);
  DelTree(AddBackslash(Downloads) + 'llm', True, True, True);
  DeleteFile(AddBackslash(Downloads) + Marker);
  RemoveDir(Downloads);                         { only goes when empty }
end;

function Ask(const Text: String): Boolean;
begin
  Result := SuppressibleMsgBox(Text, mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
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

  Found := False;
  Size := 0;
  { A folder elsewhere is ours only with the marker the app writes there, so a stray value can't empty someone's models\.
    A missing folder (an unplugged drive) is left alone. }
  if DirExists(Downloads) and
     ((CompareText(Downloads, AppData) = 0) or FileExists(AddBackslash(Downloads) + Marker)) then
    Size := TreeSize(AddBackslash(Downloads) + 'models', Found) + TreeSize(AddBackslash(Downloads) + 'gpu', Found)
            + TreeSize(AddBackslash(Downloads) + 'llm', Found);

  if Found then
  begin
    if Ask(FmtMessage(CustomMessage('DeleteDownloads'), [SizeText(Size), Downloads])) then
    begin
      DeleteDownloads(Downloads);
      DeleteAppData(AppData);
    end;
  end
  else if FileExists(AppData + '\settings.json') or FileExists(AppData + '\recents.json') or DirExists(AppData + '\logs') then
  begin
    { Nothing downloaded to ask about (or its folder is gone): still offer to clear the app folder. }
    if Ask(CustomMessage('DeleteSettings')) then
      DeleteAppData(AppData);
  end;
end;
