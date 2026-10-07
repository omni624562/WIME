;
;	Copyright (C) 2013 - 2016 Hong Jen Yee (PCMan) <pcman.tw@gmail.com>
;
;	This library is free software; you can redistribute it and/or
;	modify it under the terms of the GNU Library General Public
;	License as published by the Free Software Foundation; either
;	version 2 of the License, or (at your option) any later version.
;
;	This library is distributed in the hope that it will be useful,
;	but WITHOUT ANY WARRANTY; without even the implied warranty of
;	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
;	Library General Public License for more details.
;
;	You should have received a copy of the GNU Library General Public
;	License along with this library; if not, write to the
;	Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
;	Boston, MA  02110-1301, USA.
;

!include "MUI2.nsh" ; modern UI
!include "x64.nsh" ; NSIS plugin used to detect 64 bit Windows
!include "Winver.nsh" ; Windows version detection
!include "LogicLib.nsh" ; for ${If}, ${Switch} commands
!include "Sections.nsh" ; for selecting sections in silent installs
!include "FileFunc.nsh" ; for ${GetSize}

; We need the StdUtils plugin
!addincludedir "StdUtils.2015-11-16\Include"
!addplugindir /x86-unicode "StdUtils.2015-11-16\Plugins\Release_Unicode"
!include "StdUtils.nsh" ; for ExecShellAsUser()

; We need the MD5 plugin
!addplugindir /x86-unicode "md5dll\UNICODE"

Unicode true ; turn on Unicode (This requires NSIS 3.0)
SetCompressor /SOLID lzma ; use LZMA for best compression ratio
SetCompressorDictSize 16 ; larger dictionary size for better compression ratio
AllowSkipFiles off ; cannot skip a file

; icons of the generated installer and uninstaller
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\orange-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\orange-uninstall.ico"

!define /file PRODUCT_VERSION "..\version.txt"
!include "version.nsh" ; VI_VERSION, e.g. 1.3.0.14 for 1.3.0-beta14

; Version resource of the setup program (Properties > Details; without it the file
; showed no name, description or version). The per-language keys are set by LANG_LOAD.
VIProductVersion "${VI_VERSION}"
VIFileVersion "${VI_VERSION}"

!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\PIME"
!define HOMEPAGE_URL "https://github.com/omni624562/WIME"
; The Start-menu folder, in the all-users Start menu like the rest of the install
; (Program Files, HKLM). A fixed name rather than $(PRODUCT_NAME): the uninstaller does
; not know the language picked in the installer, so it removed the other language's
; folder and left this one behind.
!define START_MENU_FOLDER "WIME"

Name "$(PRODUCT_NAME)"
BrandingText "$(PRODUCT_NAME)"

!ifdef ONLY_DAYI_CHEWING_CHECJ
OutFile "WIME-${PRODUCT_VERSION}-dayi-chewing-checj-setup.exe" ; Limited installer for Dayi, Chewing, and New Cangjie
!else
OutFile "WIME-${PRODUCT_VERSION}-setup.exe" ; The generated installer file name
!endif

; We install everything to C:\Program Files (x86)
InstallDir "$PROGRAMFILES32\PIME"

;Request application privileges (need administrator to install)
RequestExecutionLevel admin
!define MUI_ABORTWARNING

;Pages
; license page
!insertmacro MUI_PAGE_LICENSE "..\LGPL-2.0.txt" ; for PIME
!insertmacro MUI_PAGE_LICENSE "..\PSF.txt" ; for python

; !insertmacro MUI_PAGE_COMPONENTS
!define MUI_COMPONENTSPAGE_SMALLDESC
!insertmacro MUI_PAGE_COMPONENTS

; installation progress page
!insertmacro MUI_PAGE_INSTFILES

; finish page
; Nothing else tells a new user how to reach the keyboards or the settings tools. The
; hint also covers PCs without the 中文 (台灣) language, where the keyboards (all
; registered under zh-Hant-TW) do not show up at all.
!define MUI_FINISHPAGE_TEXT "$(FINISH_TEXT)"
!define MUI_FINISHPAGE_LINK_LOCATION "${HOMEPAGE_URL}"
!define MUI_FINISHPAGE_LINK "$(PRODUCT_PAGE) ${MUI_FINISHPAGE_LINK_LOCATION}"
!insertmacro MUI_PAGE_FINISH

; uninstallation pages
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
;--------------------------------

!macro LANG_LOAD LANGLOAD
  !insertmacro MUI_LANGUAGE "${LANGLOAD}"
  !include "locale\${LANGLOAD}.nsh"
  ; the version keys that need no translation (the locale file sets ProductName,
  ; CompanyName and FileDescription)
  VIAddVersionKey /LANG=${LANG_${LANG}} "FileVersion" "${VI_VERSION}"
  VIAddVersionKey /LANG=${LANG_${LANG}} "ProductVersion" "${PRODUCT_VERSION}"
  VIAddVersionKey /LANG=${LANG_${LANG}} "LegalCopyright" "Copyright (C) 2013-2016 PIME developers, WIME development team"
  !undef LANG
!macroend

!macro LANG_STRING NAME VALUE
  LangString "${NAME}" "${LANG_${LANG}}" "${VALUE}"
!macroend

!macro LANG_VERSION_KEY NAME VALUE
  VIAddVersionKey /LANG=${LANG_${LANG}} "${NAME}" "${VALUE}"
!macroend

!macro LANG_UNSTRING NAME VALUE
  !insertmacro LANG_STRING "un.${NAME}" "${VALUE}"
!macroend

!insertmacro LANG_LOAD "TradChinese" ; Traditional Chinese
!ifndef ONLY_DAYI_CHEWING_CHECJ
!ifndef NO_SIMP_CHINESE
!insertmacro LANG_LOAD "SimpChinese" ; Simplified Chinese
!endif
!endif
!insertmacro LANG_LOAD "English" ; English

var UPDATEX86DLL
var UPDATEX64DLL
var UPDATEARM64DLL

; "True" once the user agreed to replace the installed version (see askRemoveOldVersion)
var REMOVE_OLD_VERSION

var INST_PYTHON
var INST_CINBASE
var INST_DAYI_RUST

; The table file of Liu input method
!ifndef ONLY_DAYI_CHEWING_CHECJ
var LIU_UNI_TAB_FILE
!endif

; Get a possibly-locked file out of the way so a new copy can be written to its path.
; The TSF DLL is mapped into explorer, browsers, SearchHost and every other app that
; has used the IME, so during a real upgrade it can essentially never be deleted.
; Windows refuses to delete a mapped image but does allow renaming it, so rename it
; aside (like Edge/Chrome do with old_msedge.exe); running apps keep using the old
; image and newly started ones load the new file. Leftover *.old files are removed by
; the next install once nothing maps them any more.
; Deliberately no /REBOOTOK here: it sets the reboot flag, which made the upgrade abort
; half-way (old version removed, new one never installed), and a boot-time delete
; scheduled on the ORIGINAL path would also delete the freshly installed file.
; Emitted twice (installer and "un." uninstaller copies), as NSIS requires.
!macro DEFINE_MOVE_ASIDE_IF_LOCKED UN
Function ${UN}moveAsideIfLocked
	Exch $0 ; path of the file
	Push $1
	Delete "$0"
	${If} ${FileExists} "$0"
		StrCpy $1 0
		${Do}
			Delete "$0.old$1" ; reuse a stale slot if nothing maps it any more
			${IfNot} ${FileExists} "$0.old$1"
				ClearErrors
				Rename "$0" "$0.old$1"
				${IfNot} ${Errors}
					${ExitDo}
				${EndIf}
			${EndIf}
			IntOp $1 $1 + 1
		${LoopUntil} $1 >= 10
	${EndIf}
	Pop $1
	Pop $0
FunctionEnd
!macroend
!insertmacro DEFINE_MOVE_ASIDE_IF_LOCKED ""
!insertmacro DEFINE_MOVE_ASIDE_IF_LOCKED "un."

; Force-terminate anything still running from the install dir after the graceful
; "PIMELauncher.exe /quit": the launcher's worker kill does not reach its python
; backends, and settings-tool servers (configtool.py) could outlive their idle timeout
; in older versions. Any of them keeps python\python3\*.dll mapped, which blocks
; removing the old python tree. (The uninstaller itself runs from a %TEMP% copy, so
; it is never matched.)
!macro DEFINE_KILL_PROCESSES_IN_INSTDIR UN
Function ${UN}killProcessesInInstDir
	Push $0
	nsExec::ExecToLog `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $$_.ExecutablePath -like '$INSTDIR\*' } | ForEach-Object { Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue }"`
	Pop $0 ; exit code, ignored: best effort
	Pop $0
	Sleep 500
FunctionEnd
!macroend
!insertmacro DEFINE_KILL_PROCESSES_IN_INSTDIR ""
!insertmacro DEFINE_KILL_PROCESSES_IN_INSTDIR "un."

; The Start-menu folders earlier versions created: named after the language picked in
; the installer (PIME before the rename) and, as there was no SetShellVarContext, in
; the Start menu of the account the elevated installer ran as. Only these exact names
; are removed; copies in other accounts' Start menus cannot be reached from here.
!macro RMDIR_OLD_START_MENU_FOLDERS
	RMDir /r "$SMPROGRAMS\WIME 輸入法"
	RMDir /r "$SMPROGRAMS\WIME Input Methods"
	RMDir /r "$SMPROGRAMS\WIME 输入法"
	RMDir /r "$SMPROGRAMS\PIME 輸入法"
	RMDir /r "$SMPROGRAMS\PIME Input Methods"
	RMDir /r "$SMPROGRAMS\PIME 输入法"
!macroend

; Remove the Start-menu folder and the old ones, from both the current user's and the
; all-users Start menu. Leaves the shell context at "all", which every $SMPROGRAMS use
; in this script expects.
!macro DEFINE_REMOVE_START_MENU_FOLDERS UN
Function ${UN}removeStartMenuFolders
	SetShellVarContext current
	!insertmacro RMDIR_OLD_START_MENU_FOLDERS
	SetShellVarContext all
	!insertmacro RMDIR_OLD_START_MENU_FOLDERS
	RMDir /r "$SMPROGRAMS\${START_MENU_FOLDER}"
FunctionEnd
!macroend
!insertmacro DEFINE_REMOVE_START_MENU_FOLDERS ""
!insertmacro DEFINE_REMOVE_START_MENU_FOLDERS "un."

; Refuse to install while an earlier uninstall/upgrade still has boot-time deletes
; pending for files in the install dir: Windows deletes by path at the next boot, so
; the files we are about to install would silently disappear then (this is how
; "uninstall, then reinstall without rebooting" used to lose the x64 DLL).
; Read-only on purpose: PendingFileRenameOperations is a list of (source, target)
; pairs shared with other software (Edge/Chrome updates live there too), and a
; mis-parsed empty target would shift the pairs and corrupt their pending updates.
; Renamed-aside *.old files and directories (scheduled by RMDir /REBOOTOK and only
; removed at boot if empty) are harmless and ignored.
Function checkPendingDeletesInInstDir
	Push $0
	Push $1
	nsExec::ExecToStack `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$$v = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue).PendingFileRenameOperations; $$p = ('\??\' + '$INSTDIR' + '\').ToLower(); $$hit = @($$v | Where-Object { $$_ -and $$_.ToLower().StartsWith($$p) } | Where-Object { $$leaf = Split-Path $$_ -Leaf; $$leaf.Contains('.') -and -not $$leaf.ToLower().Contains('.old') }); if ($$hit.Count) { $$hit[0].Substring(4); exit 3 } else { exit 0 }"`
	Pop $0 ; exit code
	Pop $1 ; first offending path, if any
	${If} $0 == 3
		MessageBox MB_ICONSTOP|MB_OK "$(PENDING_DELETE_MESSAGE)$\r$\n$\r$\n$1" /SD IDOK
		Abort
	${EndIf}
	Pop $1
	Pop $0
FunctionEnd

; Ask whether to replace the installed version. Called from .onInit, which runs before
; the license and components pages, so this must not change anything: removing the old
; version here (as this used to) left the PC with no WIME at all - TSF DLLs unregistered,
; no Apps & features entry, no autostart, no python tree - when the user then clicked
; Cancel on one of those pages. The answer is kept for removeOldVersion, which the
; Prepare section runs once the user has clicked Install.
Function askRemoveOldVersion
	StrCpy $REMOVE_OLD_VERSION "False"
	ClearErrors
	ReadRegStr $R0 HKLM "${PRODUCT_UNINST_KEY}" "UninstallString"
	${If} $R0 != ""
		ClearErrors
		${If} ${FileExists} "$INSTDIR\Uninstall.exe"
			MessageBox MB_OKCANCEL|MB_ICONQUESTION $(UNINSTALL_OLD) /SD IDOK IDOK +2
			Abort ; this is skipped if the user select OK
			StrCpy $REMOVE_OLD_VERSION "True"
		${EndIf}
	${EndIf}
	ClearErrors
FunctionEnd

; Remove the old version (if the user agreed in askRemoveOldVersion) and get every file
; that is about to be replaced out of the way. Called from the Prepare section, before
; any section writes files. Failures Abort the install: NSIS then calls .onInstFailed
; itself, so calling it here as well would show its message twice.
Function removeOldVersion
	; Remove leftovers renamed aside by a previous upgrade (see moveAsideIfLocked);
	; ones still mapped by running apps just stay until the next install.
	Delete "$INSTDIR\x86\PIMETextService.dll.old*"
	Delete "$INSTDIR\x64\PIMETextService.dll.old*"
	Delete "$INSTDIR\arm64\PIMETextService.dll.old*"
	Delete "$INSTDIR\PIMELauncher.exe.old*"
	ClearErrors
	${If} $REMOVE_OLD_VERSION == "True"
		DetailPrint "$(REMOVING_OLD_VERSION)"

		; Remove the launcher from auto-start
		DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\PIME"
		DeleteRegValue HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "PIMELauncher"
		DeleteRegKey HKLM "Software\PIME"

		; Unregister COM objects (NSIS UnRegDLL command is broken and cannot be used)
		ExecWait '"$SYSDIR\regsvr32.exe" /u /s "$INSTDIR\x86\PIMETextService.dll"'
		; Verify the MD5/SHA1 checksum of 32-bit PIMETextService.dll
		StrCpy $0 "$INSTDIR\x86\PIMETextService.dll"
		md5dll::GetMD5File "$0"
		Pop $1
		StrCpy $2 "$PLUGINSDIR\PIMETextService_x86.dll"
		md5dll::GetMD5File "$2"
		Pop $3
		${If} $1 == $3
			StrCpy $UPDATEX86DLL "False"
		${Else}
			Push "$INSTDIR\x86\PIMETextService.dll"
			Call moveAsideIfLocked
		${EndIf}

		${If} ${RunningX64}
			SetRegView 64 ; disable registry redirection and use 64 bit Windows registry directly
			ExecWait '"$SYSDIR\regsvr32.exe" /u /s "$INSTDIR\x64\PIMETextService.dll"'
			; Verify the MD5/SHA1 checksum of 64-bit PIMETextService.dll
			StrCpy $0 "$INSTDIR\x64\PIMETextService.dll"
			md5dll::GetMD5File "$0"
			Pop $1
			StrCpy $2 "$PLUGINSDIR\PIMETextService_x64.dll"
			md5dll::GetMD5File "$2"
			Pop $3
			${If} $1 == $3
				StrCpy $UPDATEX64DLL "False"
			${Else}
				Push "$INSTDIR\x64\PIMETextService.dll"
				Call moveAsideIfLocked
			${EndIf}
		${EndIf}

		; Handle ARM64 version of PIMETextService.dll
		${If} ${IsNativeARM64}
			SetRegView 64 ; For ARM64, use native 64-bit registry view
			ExecWait '"$SYSDIR\regsvr32.exe" /u /s "$INSTDIR\arm64\PIMETextService.dll"'
			; Verify MD5 checksum to determine if update is needed
			StrCpy $0 "$INSTDIR\arm64\PIMETextService.dll"
			md5dll::GetMD5File "$0"
			Pop $1
			StrCpy $2 "$PLUGINSDIR\PIMETextService_arm64.dll"
			md5dll::GetMD5File "$2"
			Pop $3
			${If} $1 == $3
				StrCpy $UPDATEARM64DLL "False"
			${Else}
				Push "$INSTDIR\arm64\PIMETextService.dll"
				Call moveAsideIfLocked
			${EndIf}
		${EndIf}

		; Try to terminate running PIMELauncher and the server process
		; Otherwise we cannot replace it.
		ExecWait '"$INSTDIR\PIMELauncher.exe" /quit'
		Sleep 1000
		; /quit does not reach the python backends (or leftover settings-tool
		; servers); kill whatever still runs from the install dir so the old
		; files below can really be deleted instead of scheduled for reboot.
		Call killProcessesInInstDir
		Push "$INSTDIR\PIMELauncher.exe"
		Call moveAsideIfLocked

		Delete "$INSTDIR\backends.json"
		; No /REBOOTOK on anything we are about to reinstall: a boot-time delete
		; would wipe the new files, and the reboot flag aborts the upgrade.
		RMDir /r "$INSTDIR\python"
		RMDir /r "$INSTDIR\cinbase_rs"
		RMDir /r "$INSTDIR\node" ; node backend is no longer shipped; clean up old installs

		; Only exist in earlier versions, but need to delete it.
		RMDir /r "$INSTDIR\server"

		; Delete shortcuts in Start Menu
		Call removeStartMenuFolders

		Delete "$INSTDIR\version.txt"
		Delete "$INSTDIR\Uninstall.exe"
		RMDir "$INSTDIR" ; only removed if empty; we reinstall into it anyway
	${EndIf}

	ClearErrors
	; Ensure that old files are all deleted
	; Also covers installs without an uninstall key: nothing may still be running
	; from the install dir, or overwriting python\python3\*.dll fails and, with
	; AllowSkipFiles off, aborts the whole install.
	${If} ${FileExists} "$INSTDIR\PIMELauncher.exe"
		ExecWait '"$INSTDIR\PIMELauncher.exe" /quit'
		Sleep 1000
	${EndIf}
	Call killProcessesInInstDir
	${If} ${RunningX64}
		${If} ${FileExists} "$INSTDIR\x64\PIMETextService.dll"
			; Verify the MD5/SHA1 checksum of 64-bit PIMETextService.dll
			StrCpy $0 "$INSTDIR\x64\PIMETextService.dll"
			md5dll::GetMD5File "$0"
			Pop $1
			StrCpy $2 "$PLUGINSDIR\PIMETextService_x64.dll"
			md5dll::GetMD5File "$2"
			Pop $3
			${If} $1 == $3
				StrCpy $UPDATEX64DLL "False"
			${Else}
				Push "$INSTDIR\x64\PIMETextService.dll"
				Call moveAsideIfLocked
				${If} ${FileExists} "$INSTDIR\x64\PIMETextService.dll"
					Abort
				${EndIf}
			${EndIf}
		${EndIf}
	${EndIf}

	${If} ${IsNativeARM64}
		${If} ${FileExists} "$INSTDIR\arm64\PIMETextService.dll"
			; Verify the MD5 checksum of ARM64 PIMETextService.dll
			StrCpy $0 "$INSTDIR\arm64\PIMETextService.dll"
			md5dll::GetMD5File "$0"
			Pop $1
			StrCpy $2 "$PLUGINSDIR\PIMETextService_arm64.dll"
			md5dll::GetMD5File "$2"
			Pop $3
			${If} $1 == $3
				StrCpy $UPDATEARM64DLL "False"
			${Else}
				Push "$INSTDIR\arm64\PIMETextService.dll"
				Call moveAsideIfLocked
				${If} ${FileExists} "$INSTDIR\arm64\PIMETextService.dll"
					Abort
				${EndIf}
			${EndIf}
		${EndIf}
	${EndIf}

	${If} ${FileExists} "$INSTDIR\x86\PIMETextService.dll"
		; Verify the MD5/SHA1 checksum of 32-bit PIMETextService.dll
		StrCpy $0 "$INSTDIR\x86\PIMETextService.dll"
		md5dll::GetMD5File "$0"
		Pop $1
		StrCpy $2 "$PLUGINSDIR\PIMETextService_x86.dll"
		md5dll::GetMD5File "$2"
		Pop $3
		${If} $1 == $3
			StrCpy $UPDATEX86DLL "False"
		${Else}
			Push "$INSTDIR\x86\PIMETextService.dll"
			Call moveAsideIfLocked
			${If} ${FileExists} "$INSTDIR\x86\PIMETextService.dll"
				Abort
			${EndIf}
		${EndIf}
	${EndIf}

	; Nothing above uses /REBOOTOK, so this is only a safety net. .onInstFailed offers
	; the reboot; the removal block no longer asks as well, which in a section would
	; mean two reboot questions in a row.
	${If} ${RebootFlag}
		Abort
	${EndIf}
FunctionEnd

; Called during installer initialization
Function .onInit
	;Language selection dialog

	${IfNot} ${Silent}
		Push ""
		Push ${LANG_TRADCHINESE}
		Push "繁體中文"
!ifndef ONLY_DAYI_CHEWING_CHECJ
!ifndef NO_SIMP_CHINESE
		Push ${LANG_SIMPCHINESE}
		Push "简体中文"
!endif
!endif
		Push ${LANG_ENGLISH}
		Push "English"
		Push A ; A means auto count languages
			   ; for the auto count to work the first empty push (Push "") must remain
		LangDLL::LangDialog $(INSTALLER_LANGUAGE_TITLE) $(INSTALL_LANGUAGE_MESSAGE)

		Pop $LANGUAGE
		StrCmp $LANGUAGE "cancel" 0 +2
			Abort
	${EndIf}

	; The embedded Python 3.12 supports Windows 8.1 and later, and both it and the launcher
	; import Windows 8 APIs (PathCchCombineEx; ProcessPrng, WaitOnAddress,
	; GetSystemTimePreciseAsFileTime). Letting Vista/7 through only gave an install
	; that looked fine while the launcher failed to load at every logon. (The version
	; is reported correctly because NSIS manifests the installer for Windows 8.1/10.)
	${IfNot} ${AtLeastWin8.1}
		MessageBox MB_ICONSTOP|MB_OK $(AtLeastWin81_MESSAGE) /SD IDOK
		Quit
	${EndIf}

	${If} ${RunningX64}
		SetRegView 64 ; disable registry redirection and use 64 bit Windows registry directly
	${EndIf}

	${If} ${IsNativeARM64}
		SetRegView 64 ; disable registry redirection for ARM64 (also uses 64-bit view)
	${EndIf}

	File "/oname=$PLUGINSDIR\PIMETextService_x86.dll" "..\build\PIMETextService\Release\PIMETextService.dll"
	File "/oname=$PLUGINSDIR\PIMETextService_x64.dll" "..\build64\PIMETextService\Release\PIMETextService.dll"
	!if /FileExists "..\build_arm64\PIMETextService\Release\PIMETextService.dll"
		File "/oname=$PLUGINSDIR\PIMETextService_arm64.dll" "..\build_arm64\PIMETextService\Release\PIMETextService.dll"
	!endif

	StrCpy $UPDATEX86DLL "True"
	StrCpy $UPDATEX64DLL "True"
	!if /FileExists "..\build_arm64\PIMETextService\Release\PIMETextService.dll"
		StrCpy $UPDATEARM64DLL "True"
	!endif

	StrCpy $INST_PYTHON "False"
	StrCpy $INST_CINBASE "False"
	StrCpy $INST_DAYI_RUST "False"

!ifdef ONLY_DAYI_CHEWING_CHECJ
	; The component page is skipped during /S installs, so explicitly select the
	; three modules included in this limited installer. Without this, uninstall
	; cleanup can remove python and the backend sections never run.
	${If} ${Silent}
		Call selectLimitedSilentSections
	${EndIf}
!endif

	; must run before anything is removed or installed
	Call checkPendingDeletesInInstDir

	; check if old version is installed; it is removed later, by the Prepare section
	Call askRemoveOldVersion
	Call hideSection
FunctionEnd

; called to show an error message when errors happen
Function .onInstFailed
	${If} ${RebootFlag}
		MessageBox MB_YESNO $(REBOOT_QUESTION) IDNO +3
		Reboot
		Quit
		Abort
	${Else}
		MessageBox MB_ICONSTOP|MB_OK $(INST_FAILED_MESSAGE)
		Abort
	${EndIf}
FunctionEnd

Function ensureUCRT
	; PIMELauncher.exe and PIMETextService.dll link the C runtime statically and
	; python3\ carries its own vcruntime140.dll, so no VC++ redistributable is needed
	; (the old check downloaded one, and on 64-bit Windows only the x64 package, which
	; did not help the 32-bit launcher). The embedded Python still needs the Universal
	; C Runtime: built into Windows 10 and later, an update (KB2999226) on Windows 8.1,
	; the oldest version .onInit lets through. $SYSDIR is SysWOW64 for this 32-bit
	; installer, i.e. the 32-bit UCRT Python uses.
	${IfNot} ${FileExists} "$SYSDIR\ucrtbase.dll"
		MessageBox MB_ICONSTOP|MB_OK $(UCRT_MISSING_MESSAGE)
		ExecShell "open" "https://support.microsoft.com/kb/2999226"
		Abort
	${EndIf}
FunctionEnd

;Installer Type
InstType "$(INST_TYPE_STD)"
InstType "$(INST_TYPE_FULL)"

;Installer Sections
; Hidden and declared first, so it runs before any section writes files and only once
; the user has clicked Install (right away in silent installs).
Section "-Prepare"
	SectionIn 1 2 RO
	; Ensure that the Universal C Runtime the embedded python needs is present,
	; before anything of the old version is removed
	Call ensureUCRT
	Call removeOldVersion
SectionEnd

Section $(SECTION_MAIN) SecMain
	SectionIn 1 2 RO

	; TODO: may be we can automatically rebuild the dlls here.
	; http://stackoverflow.com/questions/24580/how-do-you-automate-a-visual-studio-build
	; For example, we can build the Visual Studio solution with the following command line.
	; C:\Program Files (x86)\Microsoft Visual Studio 12.0\Common7\IDE\devenv.com "..\build\PIME.sln" /build Release

	SetOverwrite on ; overwrite existing files
	SetOutPath "$INSTDIR"

    ; Install version info
    File "..\version.txt"

    ; Install backend informations
!ifdef ONLY_DAYI_CHEWING_CHECJ
    File "/oname=backends.json" "backends-dayi-chewing-checj.json"
!else
    File "..\backends.json"
!endif

	; Install the launcher responsible to launch the backends
	File "..\build\PIMELauncher\PIMELauncher.exe"
SectionEnd

!ifdef ONLY_DAYI_CHEWING_CHECJ
SectionGroup /e $(PYTHON_SECTION_GROUP) python_section_group
	SectionGroup /e $(PYTHON_CHT_SECTION_GROUP) python_cht_section_group
		Section $(CHEWING) chewing
			SectionIn 1 2
			SetOutPath "$INSTDIR\python\input_methods\chewing"
			; 不打包設定頁沒用到的檔案：原始碼對照 (*.map)、靜態預覽用的 debug\、沒引用的圖片，
			; 以及 jquery-ui 完整下載包裡頁面沒載入的檔案（只用 *.min.js / *.min.css）
			File /r /x "__pycache__" /x "simC.ico" /x "*.map" /x "debug" /x "keyborad_layouts_json" /x "logo.ico" \
				/x "jquery-ui.js" /x "jquery-ui.css" /x "jquery-ui.structure.css" /x "jquery-ui.structure.min.css" \
				/x "jquery-ui.theme.css" /x "external" /x "index.html" /x "package.json" /x "AUTHORS.txt" \
				"..\python\input_methods\chewing\*.*"
			StrCpy $INST_PYTHON "True"
		SectionEnd

		Section $(CHECJ) checj
			SectionIn 1 2
			SetOutPath "$INSTDIR\python\input_methods\checj"
			File /r /x "__pycache__" "..\python\input_methods\checj\*.*"
			StrCpy $INST_PYTHON "True"
			StrCpy $INST_CINBASE "True"
		SectionEnd

		Section $(CHEDAYI) chedayi
			SectionIn 1 2
			SetOutPath "$INSTDIR\python\input_methods\chedayi"
			File /r /x "__pycache__" "..\python\input_methods\chedayi\*.*"
			StrCpy $INST_PYTHON "True"
			StrCpy $INST_CINBASE "True"
		SectionEnd

		; 大易改由 Rust 後端（cinbase_rs\wime-cinbase.exe）處理；不勾選就維持 Python 後端。
		; 只在大易也勾選時有作用（實際安裝在 Register 區段，Python 的檔案複製完之後）
		Section $(CHEDAYI_RUST) chedayi_rust
			SectionIn 1 2
			StrCpy $INST_DAYI_RUST "True"
		SectionEnd
	SectionGroupEnd
SectionGroupEnd
!else
SectionGroup /e $(PYTHON_SECTION_GROUP) python_section_group
	SectionGroup /e $(PYTHON_CHT_SECTION_GROUP) python_cht_section_group
		Section $(CHEWING) chewing
			SectionIn 1 2
			SetOutPath "$INSTDIR\python\input_methods\chewing"
			File /r "..\python\input_methods\chewing\*.*"
			StrCpy $INST_PYTHON "True"
		SectionEnd

		Section $(CHECJ) checj
			SectionIn 2
			SetOutPath "$INSTDIR\python\input_methods\checj"
			File /r "..\python\input_methods\checj\*.*"
			StrCpy $INST_PYTHON "True"
			StrCpy $INST_CINBASE "True"
		SectionEnd

		Section $(CHELIU) cheliu
            SectionIn 2
            ; Ask the user to provide "liu-uni.tab" file
            MessageBox MB_OK|MB_ICONQUESTION "$(SELECT_LIU_FILE)"
            nsDialogs::SelectFileDialog open "" "liu-uni.tab file|liu-uni.tab"
            Pop $LIU_UNI_TAB_FILE
			${If} ${FileExists} "$LIU_UNI_TAB_FILE"
				SetOutPath "$INSTDIR\python\input_methods\cheliu"
				File /r "..\python\input_methods\cheliu\*.*"
				SetOutPath "$INSTDIR\python\cinbase\cin"
				StrCpy $INST_PYTHON "True"
				StrCpy $INST_CINBASE "True"
            ${Else}
                MessageBox MB_OK|MB_ICONSTOP "$(CANNOT_INSTALL_LIU)"
                StrCpy $LIU_UNI_TAB_FILE ""
			${EndIf}
		SectionEnd

		Section $(CHEARRAY) chearray
			SectionIn 2
			SetOutPath "$INSTDIR\python\input_methods\chearray"
			File /r "..\python\input_methods\chearray\*.*"
			StrCpy $INST_PYTHON "True"
			StrCpy $INST_CINBASE "True"
		SectionEnd

		; 大易列入標準安裝（SectionIn 1），其他 CIN 輸入法僅 full install（SectionIn 2）
		Section $(CHEDAYI) chedayi
			SectionIn 1 2
			SetOutPath "$INSTDIR\python\input_methods\chedayi"
			File /r "..\python\input_methods\chedayi\*.*"
			StrCpy $INST_PYTHON "True"
			StrCpy $INST_CINBASE "True"
		SectionEnd

		; 大易改由 Rust 後端（cinbase_rs\wime-cinbase.exe）處理；不勾選就維持 Python 後端。
		; 只在大易也勾選時有作用（實際安裝在 Register 區段，Python 的檔案複製完之後）
		Section $(CHEDAYI_RUST) chedayi_rust
			SectionIn 1 2
			StrCpy $INST_DAYI_RUST "True"
		SectionEnd

		Section $(CHEPINYIN) chepinyin
			SectionIn 2
			SetOutPath "$INSTDIR\python\input_methods\chepinyin"
			File /r "..\python\input_methods\chepinyin\*.*"
			StrCpy $INST_PYTHON "True"
			StrCpy $INST_CINBASE "True"
		SectionEnd

		Section $(CHESIMPLEX) chesimplex
			SectionIn 2
			SetOutPath "$INSTDIR\python\input_methods\chesimplex"
			File /r "..\python\input_methods\chesimplex\*.*"
			StrCpy $INST_PYTHON "True"
			StrCpy $INST_CINBASE "True"
		SectionEnd

		Section $(CHEPHONETIC) chephonetic
			SectionIn 2
			SetOutPath "$INSTDIR\python\input_methods\chephonetic"
			File /r "..\python\input_methods\chephonetic\*.*"
			StrCpy $INST_PYTHON "True"
			StrCpy $INST_CINBASE "True"
		SectionEnd

		Section $(CHEEZ) cheez
			SectionIn 2
			SetOutPath "$INSTDIR\python\input_methods\cheez"
			File /r "..\python\input_methods\cheez\*.*"
			StrCpy $INST_PYTHON "True"
			StrCpy $INST_CINBASE "True"
		SectionEnd

		Section $(CHEENG) cheeng
			${If} ${AtLeastWin8}
				SectionIn 2
				SetOutPath "$INSTDIR\python\input_methods\cheeng"
				File /r "..\python\input_methods\cheeng\*.*"
				StrCpy $INST_PYTHON "True"
			${EndIf}
		SectionEnd

		Section $(BRAILLE_CHEWING) braille_chewing
            SectionIn 2
            SetOutPath "$INSTDIR\python\input_methods\braille_chewing"
            File /r "..\python\input_methods\braille_chewing\*.*"
            StrCpy $INST_PYTHON "True"
		SectionEnd

    SectionGroupEnd

	SectionGroup /e $(PYTHON_CHS_SECTION_GROUP) python_chs_section_group
		Section $(RIME) rime
			SectionIn 2
			SetOutPath "$INSTDIR\python\input_methods\rime"
			File /r /x "brise" "..\python\input_methods\rime\*.*"
			SetOutPath "$INSTDIR\python\input_methods\rime\data"
			File "..\python\input_methods\rime\brise\*.txt"
			File "..\python\input_methods\rime\brise\*.yaml"
			File "..\python\input_methods\rime\brise\preset\*.yaml"
			File "..\python\input_methods\rime\brise\supplement\*.yaml"
			File "..\python\input_methods\rime\brise\extra\*.yaml"
			SetOutPath "$INSTDIR\python\input_methods\rime\data\opencc"
			File "..\python\opencc\*.json" "..\python\opencc\*.ocd"
			StrCpy $INST_PYTHON "True"
		SectionEnd
	SectionGroupEnd
SectionGroupEnd
!endif

!ifdef ONLY_DAYI_CHEWING_CHECJ
Function selectLimitedSilentSections
	!insertmacro SelectSection ${chewing}
	!insertmacro SelectSection ${checj}
	!insertmacro SelectSection ${chedayi}
	!insertmacro SelectSection ${chedayi_rust}
FunctionEnd
!endif

Function hideSection
!ifndef ONLY_DAYI_CHEWING_CHECJ
	${IfNot} ${AtLeastWin8}
		SectionSetText ${cheeng} ""
	${EndIf}
!endif
FunctionEnd

Section "" Register
	SectionIn 1 2
	; Install the python backend and input method modules along with an embedable version of python 3.
	${If} $INST_PYTHON == "True"
		SetOutPath "$INSTDIR\python"
!ifdef ONLY_DAYI_CHEWING_CHECJ
		; .pytest_cache：在 python\ 下跑過 pytest 就會出現，不入 git 但會被 /r 一起打包
		; python3\ 裡從不會被載入的檔案：沒用到的擴充模組、python3.dll（沒有程式匯入）、
		; 簽章目錄 python.cat、不會被讀取的 PIME.pth、設定工具沒用到的 tornado 模組。
		; 標準函式庫 zip 改用 build\ 裡精簡過的版本（build.bat 執行 installer\trim_python_zip.py 產生）
		File /r /x "__pycache__" /x ".pytest_cache" /x "input_methods" /x "cinbase" /x "opencc" /x ".git" /x ".idea" \
			/x "python312.zip" /x "python3.dll" /x "python.cat" /x "PIME.pth" \
			/x "_decimal.pyd" /x "_elementtree.pyd" /x "_msi.pyd" /x "_multiprocessing.pyd" /x "_zoneinfo.pyd" /x "pyexpat.pyd" \
			/x "auth.py" /x "autoreload.py" /x "curl_httpclient.py" /x "httpclient.py" /x "locks.py" /x "options.py" \
			/x "queues.py" /x "simple_httpclient.py" /x "tcpclient.py" /x "testing.py" /x "websocket.py" /x "wsgi.py" \
			/x "speedups.c" /x "caresresolver.py" /x "twisted.py" \
			"..\python\*.*"
		SetOutPath "$INSTDIR\python\python3"
		File "..\build\python312.zip"
		SetOutPath "$INSTDIR\python"
!else
		File /r /x "__pycache__" /x ".pytest_cache" /x "input_methods" /x "cinbase" /x ".git" /x ".idea" "..\python\*.*"
!endif
		SetOutPath "$INSTDIR\python\input_methods"
		File "..\python\input_methods\__init__.py"
	${EndIf}

	; Install the CinBase Class for all cin-based input method modules.
	${If} $INST_CINBASE == "True"
		SetOutPath "$INSTDIR\python"
!ifdef ONLY_DAYI_CHEWING_CHECJ
		; 不打包：建置用的工具 tools\（與只在原始碼開啟 DEBUG_MODE 才用到、需要 tools 的
		; debug.py）、圖示原始檔 *.pdn、設定頁沒載入的字型與舊版 / 未壓縮的 css、js、
		; 只有注音（chephonetic）才用的 kblayout.htm，以及說明文件（授權檔照常打包）
		File /r /x "__pycache__" /x "cin" /x "json" /x "sim_*.ico" /x "tools" /x "debug.py" /x "*.pdn" \
			/x "fonts" /x "kblayout.htm" /x "bootstrap-theme.min.css" /x "jquery.bootstrap-touchspin.css" \
			/x "jquery.bootstrap-touchspin.js" /x "jAlert-ie8.min.js" /x "jAlert-functions.min.js" \
			/x "README.md" /x "readme.md" /x "AUTHORS.txt" \
			"..\python\cinbase"
		SetOutPath "$INSTDIR\python\cinbase\json"
		File "..\python\cinbase\json\checj.json"
		File "..\python\cinbase\json\mscj3.json"
		File "..\python\cinbase\json\mscj3-ext.json"
		File "..\python\cinbase\json\cj-ext.json"
		File "..\python\cinbase\json\cnscj.json"
		File "..\python\cinbase\json\thcj.json"
		File "..\python\cinbase\json\newcj3.json"
		File "..\python\cinbase\json\cj5.json"
		File "..\python\cinbase\json\newcj.json"
		File "..\python\cinbase\json\scj6.json"
		File "..\python\cinbase\json\cj-fast.json"
		File "..\python\cinbase\json\thdayi.json"
		File "..\python\cinbase\json\dayi4.json"
		File "..\python\cinbase\json\dayi3.json"
		; 大易/酷倉設定頁的「同音字查詢」三個選項（與注音反查）用的注音碼表；
		; 沒附的話該功能開了也完全沒反應
		File "..\python\cinbase\json\thphonetic.json"
		File "..\python\cinbase\json\CnsPhonetic.json"
		File "..\python\cinbase\json\bpmf.json"
!else
		File /r /x "__pycache__" /x "cin" "..\python\cinbase"
        ${If} ${SectionIsSelected} ${cheliu}
            ; Convert the tab file to *.cin format first.
            nsExec::ExecToLog '"$INSTDIR\python\python3\python.exe" "$INSTDIR\python\cinbase\tools\liu_unitab2cin.py" "$LIU_UNI_TAB_FILE" "$INSTDIR\python\cinbase\cin\liu.cin"'
            ; Convert the liu.cin file to json format used by cinbase.
            nsExec::ExecToLog '"$INSTDIR\python\python3\python.exe" "$INSTDIR\python\cinbase\tools\cintojson.py" "liu.cin"'
        ${EndIf}
!endif
	${EndIf}

	; 大易的 Rust 後端：backends.json 的 cinbase_rs 資料夾放 ime.json，大易的 GUID 就由它接手。
	; 同一個 GUID 只能有一個後端：拿掉 Python 那份 ime.json（設定頁與 config\ 照舊在 python 下，
	; Rust 後端也讀同一份設定、碼表與資料檔）
	${If} $INST_DAYI_RUST == "True"
	${AndIf} ${SectionIsSelected} ${chedayi}
		SetOutPath "$INSTDIR\cinbase_rs"
		File "..\cinbase-rs\target\i686-pc-windows-msvc\release\wime-cinbase.exe"
		SetOutPath "$INSTDIR\cinbase_rs\input_methods\chedayi"
		File "..\cinbase-rs\input_methods\chedayi\ime.json"
		File "..\python\input_methods\chedayi\icon.ico"
		Delete "$INSTDIR\python\input_methods\chedayi\ime.json"
	${EndIf}

	; Install the text service dlls
	${If} ${RunningX64} ; This is a 64-bit Windows system
		SetOutPath "$INSTDIR\x64"
		${If} $UPDATEX64DLL == "True"
			File "..\build64\PIMETextService\Release\PIMETextService.dll" ; put 64-bit PIMETextService.dll in x64 folder
		${EndIf}
		; Register COM objects (NSIS RegDLL command is broken and cannot be used)
		ExecWait '"$SYSDIR\regsvr32.exe" /s "$INSTDIR\x64\PIMETextService.dll"'
	${EndIf}

	!if /FileExists "..\build_arm64\PIMETextService\Release\PIMETextService.dll"
	${If} ${IsNativeARM64} ; This is a native ARM64 Windows system
		SetOutPath "$INSTDIR\arm64"
		${If} $UPDATEARM64DLL == "True"
			File "..\build_arm64\PIMETextService\Release\PIMETextService.dll" ; put ARM64 PIMETextService.dll in arm64 folder
		${EndIf}
		; Register COM objects (NSIS RegDLL command is broken and cannot be used)
		ExecWait '"$SYSDIR\regsvr32.exe" /s "$INSTDIR\arm64\PIMETextService.dll"'
	${EndIf}
	!endif

	SetOutPath "$INSTDIR\x86"
	${If} $UPDATEX86DLL == "True"
		File "..\build\PIMETextService\Release\PIMETextService.dll" ; put 32-bit PIMETextService.dll in x86 folder
	${EndIf}
	; Register COM objects (NSIS RegDLL command is broken and cannot be used)
	ExecWait '"$SYSDIR\regsvr32.exe" /s "$INSTDIR\x86\PIMETextService.dll"'

	; Launch the python server on startup
	WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "PIMELauncher" "$INSTDIR\PIMELauncher.exe"

	;Store installation folder in the registry
	WriteRegStr HKLM "Software\PIME" "" $INSTDIR
	;Write an entry to Add & Remove applications
	WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayName" $(PRODUCT_NAME)
	WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
	WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "Publisher" $(PRODUCT_PUBLISHER)
	; The icon Settings > Apps shows. PIMETextService.dll has no icon resource, so use
	; the 大易 one when 大易 is installed, else the uninstaller's.
	${If} ${SectionIsSelected} ${chedayi}
		WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\python\input_methods\chedayi\icon.ico"
	${Else}
		WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\Uninstall.exe"
	${EndIf}
	WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
	WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "URLInfoAbout" "${HOMEPAGE_URL}"
	; Uninstall is the only action there is: without NoModify, Programs and Features
	; labels the button Uninstall/Change, and either way it runs the uninstaller
	WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoModify" 1
	WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoRepair" 1
	WriteUninstaller "$INSTDIR\Uninstall.exe" ;Create uninstaller

	; Compile all installed python modules to *.pyc files
	${If} $INST_PYTHON == "True"
		; -o 0：設定工具 (不加 -O) 用的 .pyc；-o 1：後端 (python.exe -O server.py) 用的 .opt-1.pyc。
		; 以前只產生前者，一般使用者又無權寫入 Program Files，後端每次啟動都重新編譯全部程式碼
		nsExec::ExecToLog  '"$INSTDIR\python\python3\python.exe" -m compileall -o 0 -o 1 "$INSTDIR\python"'
	${EndIf}

	; The size Settings > Apps shows (in KB), measured once everything, the .pyc files
	; above included, is in place
	${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
	WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "EstimatedSize" $0

	; Launch the python server as current user (non-elevated process)
	${StdUtils.ExecShellAsUser} $0 "$INSTDIR\PIMELauncher.exe" "open" ""

	; Create shortcuts. Clear out the old folders first also when removeOldVersion did not
	; run (no uninstall entry): an older uninstaller left the folder of the language it
	; did not run in.
	Call removeStartMenuFolders
	SetShellVarContext all
	CreateDirectory "$SMPROGRAMS\${START_MENU_FOLDER}"
	${If} ${SectionIsSelected} ${chewing}
		CreateShortCut "$SMPROGRAMS\${START_MENU_FOLDER}\$(SET_CHEWING).lnk" "$INSTDIR\python\python3\pythonw.exe" '"$INSTDIR\python\input_methods\chewing\config_tool.py" config' "$INSTDIR\python\input_methods\chewing\images\setting.ico" 0
		CreateShortCut "$SMPROGRAMS\${START_MENU_FOLDER}\$(SET_CHEWING_PHRASES).lnk" "$INSTDIR\python\python3\pythonw.exe" '"$INSTDIR\python\input_methods\chewing\config_tool.py" user_phrase_editor' "$INSTDIR\python\input_methods\chewing\images\phrase_editor.ico" 0
	${EndIf}

	${If} ${SectionIsSelected} ${checj}
		CreateShortCut "$SMPROGRAMS\${START_MENU_FOLDER}\$(SET_CHECJ).lnk" "$INSTDIR\python\python3\pythonw.exe" '"$INSTDIR\python\cinbase\configtool.py" config checj' "$INSTDIR\python\input_methods\checj\icon.ico" 0
	${EndIf}

!ifndef ONLY_DAYI_CHEWING_CHECJ
	${If} ${SectionIsSelected} ${cheliu}
		CreateShortCut "$SMPROGRAMS\${START_MENU_FOLDER}\$(SET_CHELIU).lnk" "$INSTDIR\python\python3\pythonw.exe" '"$INSTDIR\python\cinbase\configtool.py" config cheliu' "$INSTDIR\python\input_methods\cheliu\icon.ico" 0
	${EndIf}

	${If} ${SectionIsSelected} ${chearray}
		CreateShortCut "$SMPROGRAMS\${START_MENU_FOLDER}\$(SET_CHEARRAY).lnk" "$INSTDIR\python\python3\pythonw.exe" '"$INSTDIR\python\cinbase\configtool.py" config chearray' "$INSTDIR\python\input_methods\chearray\icon.ico" 0
	${EndIf}
!endif

	${If} ${SectionIsSelected} ${chedayi}
		CreateShortCut "$SMPROGRAMS\${START_MENU_FOLDER}\$(SET_CHEDAYI).lnk" "$INSTDIR\python\python3\pythonw.exe" '"$INSTDIR\python\cinbase\configtool.py" config chedayi' "$INSTDIR\python\input_methods\chedayi\icon.ico" 0
	${EndIf}

!ifndef ONLY_DAYI_CHEWING_CHECJ
	${If} ${SectionIsSelected} ${chepinyin}
		CreateShortCut "$SMPROGRAMS\${START_MENU_FOLDER}\$(SET_CHEPINYIN).lnk" "$INSTDIR\python\python3\pythonw.exe" '"$INSTDIR\python\cinbase\configtool.py" config chepinyin' "$INSTDIR\python\input_methods\chepinyin\icon.ico" 0
	${EndIf}

	${If} ${SectionIsSelected} ${chesimplex}
		CreateShortCut "$SMPROGRAMS\${START_MENU_FOLDER}\$(SET_CHESIMPLEX).lnk" "$INSTDIR\python\python3\pythonw.exe" '"$INSTDIR\python\cinbase\configtool.py" config chesimplex' "$INSTDIR\python\input_methods\chesimplex\icon.ico" 0
	${EndIf}

	${If} ${SectionIsSelected} ${chephonetic}
		CreateShortCut "$SMPROGRAMS\${START_MENU_FOLDER}\$(SET_CHEPHONETIC).lnk" "$INSTDIR\python\python3\pythonw.exe" '"$INSTDIR\python\cinbase\configtool.py" config chephonetic' "$INSTDIR\python\input_methods\chephonetic\icon.ico" 0
	${EndIf}

	${If} ${SectionIsSelected} ${cheez}
		CreateShortCut "$SMPROGRAMS\${START_MENU_FOLDER}\$(SET_CHEEZ).lnk" "$INSTDIR\python\python3\pythonw.exe" '"$INSTDIR\python\cinbase\configtool.py" config cheez' "$INSTDIR\python\input_methods\cheez\icon.ico" 0
	${EndIf}
!endif

	CreateShortCut "$SMPROGRAMS\${START_MENU_FOLDER}\$(UNINSTALL_PIME).lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

;Assign language strings to sections
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
	!insertmacro MUI_DESCRIPTION_TEXT ${SecMain} $(SecMain_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${python_section_group} $(PYTHON_SECTION_GROUP_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${python_cht_section_group} $(PYTHON_CHT_SECTION_GROUP_DESC)
!ifdef ONLY_DAYI_CHEWING_CHECJ
	!insertmacro MUI_DESCRIPTION_TEXT ${chewing} $(chewing_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${checj} $(checj_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${chedayi} $(chedayi_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${chedayi_rust} $(chedayi_rust_DESC)
!else
	!insertmacro MUI_DESCRIPTION_TEXT ${python_chs_section_group} $(PYTHON_CHS_SECTION_GROUP_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${chewing} $(chewing_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${checj} $(checj_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${cheliu} $(cheliu_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${chearray} $(chearray_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${chedayi} $(chedayi_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${chedayi_rust} $(chedayi_rust_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${chepinyin} $(chepinyin_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${chesimplex} $(chesimplex_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${chephonetic} $(chephonetic_DESC)
    !insertmacro MUI_DESCRIPTION_TEXT ${cheez} $(cheez_DESC)
    !insertmacro MUI_DESCRIPTION_TEXT ${rime} $(rime_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${cheeng} $(cheeng_DESC)
	!insertmacro MUI_DESCRIPTION_TEXT ${braille_chewing} $(braille_chewing_DESC)
!endif
!insertmacro MUI_FUNCTION_DESCRIPTION_END

;Uninstaller Section
Section "Uninstall"
	${If} ${RunningX64}
		SetRegView 64 ; disable registry redirection and use 64 bit Windows registry directly
	${EndIf}

	${If} ${IsNativeARM64}
		SetRegView 64 ; disable registry redirection on ARM64 systems
	${EndIf}

	; Remove the launcher from auto-start
	DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\PIME"
	DeleteRegValue HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "PIMELauncher"
	DeleteRegKey HKLM "Software\PIME"

	; Stop the launcher and anything else still running from the install dir first,
	; so the files below can really be deleted now.
	ExecWait '"$INSTDIR\PIMELauncher.exe" /quit'
	Sleep 1000
	Call un.killProcessesInInstDir

	; Files that are still mapped (the TSF DLL in explorer etc.) are renamed aside
	; before /REBOOTOK: the boot-time delete then targets the unique *.oldN name, never
	; the original path - otherwise reinstalling before the next reboot would have the
	; freshly installed file deleted at boot.
	; Unregister COM objects (NSIS UnRegDLL command is broken and cannot be used)
	ExecWait '"$SYSDIR\regsvr32.exe" /u /s "$INSTDIR\x86\PIMETextService.dll"'
	${If} ${RunningX64}
		ExecWait '"$SYSDIR\regsvr32.exe" /u /s "$INSTDIR\x64\PIMETextService.dll"'
		Push "$INSTDIR\x64\PIMETextService.dll"
		Call un.moveAsideIfLocked
		RMDir /REBOOTOK /r "$INSTDIR\x64"
	${EndIf}

	${If} ${IsNativeARM64}
		ExecWait '"$SYSDIR\regsvr32.exe" /u /s "$INSTDIR\arm64\PIMETextService.dll"'
		Push "$INSTDIR\arm64\PIMETextService.dll"
		Call un.moveAsideIfLocked
		RMDir /REBOOTOK /r "$INSTDIR\arm64"
	${EndIf}

	Push "$INSTDIR\PIMELauncher.exe"
	Call un.moveAsideIfLocked
	Delete /REBOOTOK "$INSTDIR\PIMELauncher.exe.old*"

	Push "$INSTDIR\x86\PIMETextService.dll"
	Call un.moveAsideIfLocked
	RMDir /REBOOTOK /r "$INSTDIR\x86"
	RMDir /REBOOTOK /r "$INSTDIR\python"
	RMDir /REBOOTOK /r "$INSTDIR\cinbase_rs"
	RMDir /REBOOTOK /r "$INSTDIR\node" ; only present in old installs (node backend removed)
    Delete "$INSTDIR\backends.json"

	; Delete shortcuts in Start Menu
	Call un.removeStartMenuFolders

	Delete "$INSTDIR\version.txt"
	Delete "$INSTDIR\Uninstall.exe"
	RMDir /REBOOTOK "$INSTDIR"

	; Everything is already removed or renamed aside; a reboot only cleans up the
	; leftover *.old files. Declining must not report the uninstall as failed (the old
	; code jumped to Abort, making silent uninstalls exit with an error).
	${If} ${RebootFlag}
		MessageBox MB_YESNO "$(MB_REBOOT_REQUIRED)" /SD IDNO IDNO +2
		Reboot
	${EndIf}
SectionEnd
