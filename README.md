# WIME

[![GitHub release](https://img.shields.io/github/release/omni624562/WIME.svg)](https://github.com/omni624562/WIME/releases)

Implement input methods easily for Windows via Text Services Framework:
*   LibIME contains a library which aims to be a simple wrapper for Windows Text Service Framework (TSF).
*   PIMETextService contains an backbone implementation of Windows text service for using libIME.
*   The python server part requires python 3.x and pywin32 package.

All parts are licensed under GNU LGPL v2.1 license.

## Improvements in this fork

WIME is based on the original PIME project and includes the following fixes and performance improvements:

**Bug fixes**
*   Fixed extra space inserted after character selection in cinbase-based input methods.
*   Fixed `[json.exception.type_error.302]` crash when backend response arrives before C++ timeout — all `ret["return"].get<bool>()` calls now use `ret.value("return", false)` to handle absent fields safely.
*   Fixed `updateCandidateList` crash when `showCandidates` field is absent in response JSON.

**Performance improvements**
*   Added `PYTHONUNBUFFERED=1` when spawning Python backends — eliminates 8 KB block-buffering delay that was the root cause of all input lag.
*   Added `flush=True` to all `print()` calls in `python/server.py` as a secondary safeguard.
*   Redirected debug/error prints in `server.py` from stdout to stderr, preventing protocol pollution.
*   Fixed `BackendManager::get_backend_input()` in PIMELauncher to release the async mutex *before* spawning a new backend process, eliminating cold-start blocking of all other clients.
*   Increased pipe read buffer from 1 KB to 8 KB in PIMEClient to reduce syscall round-trips for large candidate-list responses.
*   Reduced `connectPipe` timeout from 30 s × 5 attempts to 3 s × 3 attempts to prevent UI freeze when PIMELauncher is unavailable.
*   Changed watchdog tick logging from `info!` to `debug!` level to reduce console noise.
*   Optimised `parse_backend_output()` in protocol.rs to use `strip_prefix`/`find` instead of `splitn().collect()`, avoiding heap allocation per message.

# Development

## Tool Requirements
*   [CMake](http://www.cmake.org/) >= 3.0
*   [Visual Studio 2022](https://visualstudio.microsoft.com/vs)
*   [Rust Toolchain](https://rustup.rs/) (Stable channel with `i686-pc-windows-msvc` target)
*   [git](http://windows.github.com/)
*   [Node.js](https://nodejs.org/) (Required for some backends like McBopomofo)

## How to Build
*   Get source from github.

        git clone https://github.com/omni624562/WIME.git
        cd WIME
        git submodule update --init

*   Ensure the 32-bit Rust target is installed:

        rustup target add i686-pc-windows-msvc

*   Use `build.bat` to build everything, or use the following CMake commands to generate Visual Studio project.

        cmake . -Bbuild -G "Visual Studio 17 2022" -A Win32
        cmake --build build --config Release

        # For 64-bit Text Service (Required for 64-bit apps)
        cmake . -Bbuild64 -G "Visual Studio 17 2022" -A x64
        cmake --build build64 --config Release --target PIMETextService

*   The generated installer will be in the `installer` folder after running `makensis`.

## TSF References
*   [Text Services Framework](http://msdn.microsoft.com/en-us/library/windows/desktop/ms629032%28v=vs.85%29.aspx)
*   [Guidelines and checklist for IME development (Windows Store apps)](http://msdn.microsoft.com/en-us/library/windows/apps/hh967425.aspx)
*   [Input Method Editors (Windows Store apps)](http://msdn.microsoft.com/en-us/library/windows/apps/hh967426.aspx)
*   [Third-party input method editors](http://msdn.microsoft.com/en-us/library/windows/desktop/hh848069%28v=vs.85%29.aspx)
*   [Strategies for App Communication between Windows 8 UI and Windows 8 Desktop](http://software.intel.com/en-us/articles/strategies-for-app-communication-between-windows-8-ui-and-windows-8-desktop)
*   [TSF Aware, Dictation, Windows Speech Recognition, and Text Services Framework. (blog)](http://blogs.msdn.com/b/tsfaware/?Redirected=true)
*   [Win32 and COM for Windows Store apps](http://msdn.microsoft.com/en-us/library/windows/apps/br205757.aspx)
*   [Input Method Editor (IME) sample supporting Windows 8](http://code.msdn.microsoft.com/windowsdesktop/Input-Method-Editor-IME-b1610980)

## Windows ACL (Access Control List) references
*   [The Windows Access Control Model Part 1](http://www.codeproject.com/Articles/10042/The-Windows-Access-Control-Model-Part-1#SID)
*   [The Windows Access Control Model: Part 2](http://www.codeproject.com/Articles/10200/The-Windows-Access-Control-Model-Part-2#SidFun)
*   [Windows 8 App Container Security Notes - Part 1](http://recxltd.blogspot.tw/2012/03/windows-8-app-container-security-notes.html)
*   [How AccessCheck Works](http://msdn.microsoft.com/en-us/library/windows/apps/aa446683.aspx)
*   [GetAppContainerNamedObjectPath function (enable accessing object outside app containers using ACL)](http://msdn.microsoft.com/en-us/library/windows/desktop/hh448493)
*   [Creating a DACL](http://msdn.microsoft.com/en-us/library/windows/apps/ms717798.aspx)

# Install
*   Copy `PIMETextService.dll` to C:\Program Files (X86)\PIME\x86\.
*   Copy `PIMETextService.dll` to C:\Program Files (X86)\PIME\x64\.
*   Copy the folder `python` to `C:\Program Files (X86)\PIME\`
*   Copy the folder `node` to `C:\Program Files (X86)\PIME\`
*   Use `regsvr32` to register `PIMETextService.dll`. 64-bit system need to register both 32-bit and 64-bit `PIMETextService.dll`

        regsvr32 "C:\Program Files (X86)\PIME\x86\PIMETextService.dll" (run as administrator)
        regsvr32 "C:\Program Files (X86)\PIME\x64\PIMETextService.dll" (run as administrator)

*   NOTICE: the `regsvr32` command needs to be run as Administrator. Otherwise you'll get access denied error.
*   In Windows 8, if you put the dlls in places other than C:\Windows or C:\Program Files, they will not be accessible in metro apps.

# Uninstall
*   Use `regsvr32` to unregister `PIMETextService.dll`. 64-bit system need to unregister both 32-bit and 64-bit `PIMETextService.dll`

        regsvr32 /u "C:\Program Files (X86)\PIME\x86\PIMETextService.dll" (run as administrator)
        regsvr32 /u "C:\Program Files (X86)\PIME\x64\PIMETextService.dll" (run as administrator)
*   Remove `C:\Program Files (X86)\PIME`

*   NOTICE: the `regsvr32` command needs to be run as Administrator. Otherwise you'll get access denied error.

# Bug Report
Please report any issue to [here](https://github.com/omni624562/WIME/issues).

# Debugging
If you encounter issues, you can run PIMELauncher.exe with the /console argument:

    PIMELauncher.exe /console

This opens a console window which displays debug logs, making it easier to
troubleshoot backend communication and other internal events.
