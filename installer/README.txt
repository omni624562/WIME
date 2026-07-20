To build an installer:

1. Build release version of PIMETextService.dll (both 64 bit and 32 bit versions are required)

2. Compile installer.nsi with NSIS.

Limited WIME test installer:

To build an installer that only includes Dayi, New Chewing, and New Cangjie,
compile installer.nsi with the ONLY_DAYI_CHEWING_CHECJ define:

    makensis /DONLY_DAYI_CHEWING_CHECJ installer\installer.nsi

The output file is:

    installer\WIME-<version>-dayi-chewing-checj-setup.exe

The install paths, named pipe, and registry keys still use PIME internally for
low-level compatibility; only outward-facing display names and the installer
filename use WIME. See ..\docs\WIME_CHANGES.md for the post-rename change summary.
