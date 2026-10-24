use std::ffi::c_void;
use windows::core::{PCWSTR, PWSTR};
use windows::Win32::Foundation::{CloseHandle, LocalFree, HANDLE, HLOCAL};
use windows::Win32::Security::Authorization::{
    ConvertSidToStringSidW, ConvertStringSecurityDescriptorToSecurityDescriptorW, SDDL_REVISION_1,
};
use windows::Win32::Security::{
    GetTokenInformation, TokenUser, PSECURITY_DESCRIPTOR, SECURITY_ATTRIBUTES, TOKEN_QUERY,
    TOKEN_USER,
};
use windows::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

/// A small RAII wrapper for Windows handles to ensure they are closed.
struct AutoHandle(HANDLE);
impl Drop for AutoHandle {
    fn drop(&mut self) {
        if !self.0.is_invalid() {
            unsafe {
                let _ = CloseHandle(self.0);
            }
        }
    }
}

/// Wrapper around Windows SECURITY_ATTRIBUTES for named pipe security.
///
/// This provides a DACL that allows access to Local System, Administrators,
/// the current user, and all App Container packages, while denying network access.
/// It also sets a Low Mandatory Level to allow access from low-integrity processes.
pub struct PipeSecurityAttributes {
    sd: PSECURITY_DESCRIPTOR,
    /// The raw SECURITY_ATTRIBUTES structure that can be passed to Windows APIs.
    pub sa: SECURITY_ATTRIBUTES,
}

unsafe impl Send for PipeSecurityAttributes {}
unsafe impl Sync for PipeSecurityAttributes {}

impl Drop for PipeSecurityAttributes {
    fn drop(&mut self) {
        if !self.sd.0.is_null() {
            unsafe {
                let _ = LocalFree(Some(HLOCAL(self.sd.0)));
            }
        }
    }
}

impl PipeSecurityAttributes {
    /// Creates a new PipeSecurityAttributes by detecting the current user's SID
    /// and constructing an appropriate SDDL string.
    pub fn new() -> Option<Self> {
        let user_sid = current_user_sid()?;

        // Construct SDDL:
        // O: owner, the current user also when the launcher runs elevated (whose
        //    objects default to the Administrators group): PIMETextService
        //    accepts only a pipe owned by its own user (PIMEClient.cpp)
        // D: DACL
        // (D;;GA;;;NU) - Deny Network
        // (A;;GA;;;SY) - Allow Local System
        // (A;;GA;;;BA) - Allow Built-in Administrators
        // (A;;GA;;;AC) - Allow ALL APPLICATION PACKAGES (Metro Apps)
        // (A;;GA;;;<UserSid>) - Allow Current User
        // S: SACL
        // (ML;;NWNR;;;LW) - Low Mandatory Level (Integrity)
        let sddl = format!(
            "O:{0}D:(D;;GA;;;NU)(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;AC)(A;;GA;;;{0})S:(ML;;NWNR;;;LW)",
            user_sid
        );

        let sddl_utf16: Vec<u16> = sddl.encode_utf16().chain(std::iter::once(0)).collect();

        // 4. Convert SDDL string to Security Descriptor
        let mut sd = PSECURITY_DESCRIPTOR::default();
        unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                PCWSTR(sddl_utf16.as_ptr()),
                SDDL_REVISION_1,
                &mut sd,
                None,
            )
            .ok()?;
        }

        Some(Self {
            sd,
            sa: SECURITY_ATTRIBUTES {
                nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
                lpSecurityDescriptor: sd.0,
                // the backends (child processes) have no use for the pipe handles
                bInheritHandle: false.into(),
            },
        })
    }
}

/// The current user's SID as a string ("S-1-5-21-...").
pub fn current_user_sid() -> Option<String> {
    let mut process_token = HANDLE::default();
    unsafe {
        OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut process_token).ok()?;
    }
    let token = AutoHandle(process_token);

    let mut buf_size = 0;
    unsafe {
        // First call to get required buffer size.
        let _ = GetTokenInformation(token.0, TokenUser, None, 0, &mut buf_size);
    }
    let mut token_user_buf = vec![0u8; buf_size as usize];
    unsafe {
        GetTokenInformation(
            token.0,
            TokenUser,
            Some(token_user_buf.as_mut_ptr() as *mut c_void),
            buf_size,
            &mut buf_size,
        )
        .ok()?;
    }

    unsafe {
        let token_user = &*(token_user_buf.as_ptr() as *const TOKEN_USER);
        let mut sid_str_ptr = PWSTR::null();
        ConvertSidToStringSidW(token_user.User.Sid, &mut sid_str_ptr).ok()?;
        let sid = sid_str_ptr.to_string().ok();
        let _ = LocalFree(Some(HLOCAL(sid_str_ptr.0 as _)));
        sid
    }
}

/// The launcher's pipe: \\.\pipe\PIME\<user SID>\<session id>\Launcher, the name
/// PIMETextService builds the same way (PIMEClient::getPipeName). Pipe names are
/// shared by the whole machine: the user name alone let another account create
/// the pipe first (and the same account signed in twice share one name).
pub fn launcher_pipe_name() -> Option<String> {
    use windows::Win32::System::RemoteDesktop::ProcessIdToSessionId;
    use windows::Win32::System::Threading::GetCurrentProcessId;
    let sid = current_user_sid()?;
    let mut session = 0u32;
    unsafe { ProcessIdToSessionId(GetCurrentProcessId(), &mut session).ok()? };
    Some(format!(r"\\.\pipe\PIME\{}\{}\Launcher", sid, session))
}

/// The pipe of 1.3.0-beta19 and older (\\.\pipe\<user name>\PIME\Launcher),
/// still served so apps that loaded the old PIMETextService.dll before an
/// upgrade keep typing until they are restarted. To be dropped in a later release.
pub fn legacy_launcher_pipe_name() -> Option<String> {
    let username = std::env::var("USERNAME").ok().filter(|u| !u.is_empty())?;
    Some(format!(r"\\.\pipe\{}\PIME\Launcher", username))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pipe_names() {
        let name = launcher_pipe_name().unwrap();
        let sid = current_user_sid().unwrap();
        assert!(sid.starts_with("S-1-"), "{}", sid);
        assert!(name.starts_with(&format!(r"\\.\pipe\PIME\{}\", sid)), "{}", name);
        assert!(name.ends_with(r"\Launcher"), "{}", name);
    }

    #[test]
    fn test_create_security_attributes() {
        // This should succeed on any standard Windows dev machine
        let sa = PipeSecurityAttributes::new();
        assert!(sa.is_some());
    }
}
