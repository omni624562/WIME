To build an installer:

1. Run build.bat (PIMETextService.dll for x86/x64/ARM64, PIMELauncher.exe, cinbase-rs's
   wime-cinbase.exe and wime-config.exe, and the code tables in python\cinbase\json,
   generated with the repo's embedded Python).

2. Compile installer.nsi with NSIS.

The limited installer contains no Python. Its layout (see cinbase-rs\src\paths.rs):

    cinbase_rs\wime-cinbase.exe, wime-config.exe      backend and settings tool
    cinbase_rs\input_methods\<ime>\ime.json, icon.ico  language profiles
    data\                                            tables, data files, icons and
                                                     settings pages, in the same
                                                     sub-layout as the repo's python\

tests\installer_layout.py builds it into a temporary file and lists what is inside;
tests\test_packaging.py checks that list.

Limited WIME test installer:

To build an installer that only includes Dayi, New Chewing, and New Cangjie,
compile installer.nsi with the ONLY_DAYI_CHEWING_CHECJ define:

    makensis /DONLY_DAYI_CHEWING_CHECJ installer\installer.nsi

The output file is:

    installer\WIME-<version>-dayi-chewing-checj-setup.exe

The install paths, named pipe, and registry keys still use PIME internally for
low-level compatibility; only outward-facing display names and the installer
filename use WIME. See ..\docs\WIME_CHANGES.md for the post-rename change summary.
