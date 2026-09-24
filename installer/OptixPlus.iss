; Installateur OptixPlus (Inno Setup 6).
; Ne pas compiler directement : « python tools\build.py » fournit les définitions ci-dessous
; (AppVersion, AppVersionNumeric, SourceDir, OutputDir) après la construction PyInstaller.
;
; - installation dans C:\Program Files\OptixPlus pour tous les utilisateurs (droits administrateur) ;
;   démarrage avec Windows, reprise des anciens outils et premier lancement restent propres
;   à l'utilisateur qui installe (exécutés sous son identité, pas celle de l'administrateur) ;
; - une ancienne installation 1.0.0 dans le profil est désinstallée d'abord (réglages gardés) ;
; - langue de l'assistant : français si Windows est en français, anglais sinon ;
; - « Démarrer avec Windows » cochée ; reprise des anciens outils proposée, décochée,
;   et seulement si l'un d'eux est détecté ; OptixPlus l'exécute lui-même (--migrer=…) ;
; - la désinstallation retire le démarrage automatique et demande avant d'effacer les réglages.

#ifndef AppVersion
  #error "Compiler avec tools\build.py (AppVersion manquant)"
#endif

#define AppName "OptixPlus"
#define AppExe "OptixPlus.exe"
#define AppPublisher "OptixPlus"
; Même identifiant que celui fixé par OptixPlus au démarrage (version.APP_ID) : Windows
; affiche le nom et l'icône du raccourci dans l'en-tête des notifications.
#define AppUserModelID "OptixPlus"
#define AppUrl "https://github.com/jeanbrowaeyspro/OptixPlus"
#define RunKey "Software\Microsoft\Windows\CurrentVersion\Run"
#define AppMutexName "Local\OptixPlus_SingleInstance"
#define AppGuid "{6E1B6F4C-3C2B-4E7A-9C5D-0B7F2A1D8E43}"

[Setup]
AppId={{#AppGuid}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersionNumeric}
VersionInfoProductVersion={#AppVersionNumeric}
PrivilegesRequired=admin
DefaultDirName={autopf}\{#AppName}
DisableDirPage=auto
DisableProgramGroupPage=yes
UsedUserAreasWarning=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\src\optixplus\resources\icons\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; Ferme OptixPlus s'il tourne (gestionnaire de redémarrage de Windows).
CloseApplications=force
RestartApplications=no
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage

[Languages]
; La première langue sert quand celle de Windows n'est pas proposée : l'anglais.
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[CustomMessages]
en.GroupOptions=Options:
fr.GroupOptions=Options :
en.TaskStartup=Start OptixPlus with Windows
fr.TaskStartup=Démarrer OptixPlus avec Windows
en.GroupMigration=Former tools (nothing is deleted from them):
fr.GroupMigration=Anciens outils (rien n'y est supprimé) :
en.TaskMigrateSettings=Import the settings of Log Reader, Link Checker, Compare and Auto Validate
fr.TaskMigrateSettings=Importer les réglages de Log Reader, Link Checker, Compare et Auto Validate
en.TaskMigrateAutoValidate=Stop starting the former OptixAutoValidate with Windows (OptixPlus replaces it)
fr.TaskMigrateAutoValidate=Ne plus démarrer l'ancien OptixAutoValidate avec Windows (OptixPlus le remplace)
en.DeleteSettings=Also delete the OptixPlus settings and logs?%n%n%1
fr.DeleteSettings=Supprimer aussi les réglages et journaux d'OptixPlus ?%n%n%1

[Tasks]
Name: "startup"; Description: "{cm:TaskStartup}"; GroupDescription: "{cm:GroupOptions}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "migratesettings"; Description: "{cm:TaskMigrateSettings}"; GroupDescription: "{cm:GroupMigration}"; Flags: unchecked; Check: LegacySettingsFound
Name: "migrateautovalidate"; Description: "{cm:TaskMigrateAutoValidate}"; GroupDescription: "{cm:GroupMigration}"; Flags: unchecked; Check: LegacyAutoValidateFound

[InstallDelete]
; Une mise à jour remplace entièrement les bibliothèques embarquées.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
; Dossier d'installation : OptixPlus s'y reconnaît « installé » (tray, surveillance, mises à jour).
Root: HKLM; Subkey: "Software\{#AppName}"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "{#RunKey}"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" ""--demarrage"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
; Reprise des anciens outils : OptixPlus l'exécute lui-même au premier lancement.
Filename: "{app}\{#AppExe}"; Parameters: "--installe --migrer={code:MigrationTasks}"; Flags: nowait runasoriginaluser; Check: MigrationRequested
Filename: "{app}\{#AppExe}"; Parameters: "--installe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser; Check: not MigrationRequested
; Mise à jour silencieuse lancée par OptixPlus : relance, puis Nouveautés.
Filename: "{app}\{#AppExe}"; Parameters: "--installe --apres-maj"; Flags: nowait runasoriginaluser; Check: WizardSilent

[Code]
function LegacyCompareOrLinkCheckFound(): Boolean;
var
  Publishers: TArrayOfString;
  I: Integer;
begin
  Result := False;
  if RegGetSubkeyNames(HKCU, 'Software', Publishers) then
    for I := 0 to GetArrayLength(Publishers) - 1 do
      if RegKeyExists(HKCU, 'Software\' + Publishers[I] + '\FTOCompare') or
         RegKeyExists(HKCU, 'Software\' + Publishers[I] + '\OptixLinkCheck') then
      begin
        Result := True;
        Exit;
      end;
end;

function LegacySettingsFound(): Boolean;
begin
  Result := FileExists(ExpandConstant('{userappdata}\pyFTOLogReader\settings.json')) or
            FileExists(ExpandConstant('{userappdata}\OptixAutoValidate\config.json')) or
            LegacyCompareOrLinkCheckFound();
end;

function LegacyAutoValidateFound(): Boolean;
begin
  Result := RegValueExists(HKCU, '{#RunKey}', 'OptixAutoValidate');
end;

function MigrationTasks(Param: String): String;
begin
  Result := '';
  if WizardIsTaskSelected('migratesettings') then
    Result := 'reglages';
  if WizardIsTaskSelected('migrateautovalidate') then
  begin
    if Result <> '' then
      Result := Result + ',';
    Result := Result + 'autovalidate';
  end;
end;

function MigrationRequested(): Boolean;
begin
  Result := (not WizardSilent()) and (MigrationTasks('') <> '');
end;

// Ancienne installation 1.0.0, par utilisateur (%LOCALAPPDATA%\Programs) : désinstallée
// silencieusement avant d'installer dans Program Files. Les réglages restent (%APPDATA%).
procedure RemovePerUserInstall();
var
  Uninstaller: String;
  Code: Integer;
begin
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppGuid}_is1',
                         'UninstallString', Uninstaller) then
  begin
    Uninstaller := RemoveQuotes(Uninstaller);
    if FileExists(Uninstaller) then
      Exec(Uninstaller, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  RemovePerUserInstall();
  Result := '';
end;

function InitializeSetup(): Boolean;
var
  Waited: Integer;
begin
  // Mise à jour lancée depuis OptixPlus : lui laisser le temps de se fermer.
  Waited := 0;
  while CheckForMutexes('{#AppMutexName}') and (Waited < 15000) do
  begin
    Sleep(250);
    Waited := Waited + 250;
  end;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // Le démarrage automatique a pu être activé depuis les Paramètres d'OptixPlus.
    RegDeleteValue(HKCU, '{#RunKey}', '{#AppName}');
    DataDir := ExpandConstant('{userappdata}\{#AppName}');
    if DirExists(DataDir) and not UninstallSilent() then
      if MsgBox(FmtMessage(CustomMessage('DeleteSettings'), [DataDir]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
