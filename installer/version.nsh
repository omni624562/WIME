; Four-part numeric version for the setup program's version resource, from
; PRODUCT_VERSION (the text of version.txt). VIProductVersion accepts only X.X.X.X, so
; the pre-release number becomes the last part, like CMakeLists.txt reads the numbers
; of version.txt for the DLL: 1.3.0-beta14 -> 1.3.0.14, 1.3.0 and 1.3.0-beta -> 1.3.0.0
; (nothing compares these numbers, so a release sorting below its betas does no harm).
; Anything else (such as 1.3 or v1.3.0) fails the build, here or at VIProductVersion.
; Kept apart from installer.nsi so tests/test_installer_script.py can run it on its own.

; the added "-"s: the first is the start string to search for, and the trailing one is
; always found, so a version without a suffix still fills VI_PATCH
!searchparse /noerrors "-${PRODUCT_VERSION}-" "-" VI_MAJOR "." VI_MINOR "." VI_PATCH "-" VI_PRERELEASE
!ifndef VI_PATCH
	!error "version.txt should look like 1.3.0 or 1.3.0-beta14, not ${PRODUCT_VERSION}"
!endif
!searchreplace VI_PRERELEASE "${VI_PRERELEASE}" "alpha" ""
!searchreplace VI_PRERELEASE "${VI_PRERELEASE}" "beta" ""
!searchreplace VI_PRERELEASE "${VI_PRERELEASE}" "rc" ""
!searchreplace VI_PRERELEASE "${VI_PRERELEASE}" "." ""
!searchreplace VI_PRERELEASE "${VI_PRERELEASE}" "-" ""
!if "${VI_PRERELEASE}" == ""
	!undef VI_PRERELEASE
	!define VI_PRERELEASE 0
!endif
!define VI_VERSION "${VI_MAJOR}.${VI_MINOR}.${VI_PATCH}.${VI_PRERELEASE}"
!undef VI_MAJOR
!undef VI_MINOR
!undef VI_PATCH
!undef VI_PRERELEASE
