//! Keep the launcher and its backends off Windows' power throttling (EcoQoS).
//!
//! Windows throttles the execution speed of background processes that have no
//! window, which the worker and the backends are. After the user has been idle
//! the first key then waits for a throttled backend, and the IME DLL gives up on
//! a slow reply (PIMEClient.cpp kColdKeyEventRpcTimeoutMs): the key is lost.

use windows::Win32::Foundation::HANDLE;
use windows::Win32::System::Threading::{
    GetCurrentProcess, ProcessPowerThrottling, SetProcessInformation, PROCESS_POWER_THROTTLING_CURRENT_VERSION,
    PROCESS_POWER_THROTTLING_EXECUTION_SPEED, PROCESS_POWER_THROTTLING_STATE,
};

/// Best effort: an older Windows without the setting leaves it as is.
pub fn disable_throttling(process: HANDLE) {
    let state = PROCESS_POWER_THROTTLING_STATE {
        Version: PROCESS_POWER_THROTTLING_CURRENT_VERSION,
        ControlMask: PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
        StateMask: 0,
    };
    let result = unsafe {
        SetProcessInformation(
            process,
            ProcessPowerThrottling,
            &state as *const PROCESS_POWER_THROTTLING_STATE as *const std::ffi::c_void,
            std::mem::size_of::<PROCESS_POWER_THROTTLING_STATE>() as u32,
        )
    };
    if let Err(e) = result {
        tracing::warn!("cannot turn off power throttling: {}", e);
    }
}

pub fn disable_throttling_for_this_process() {
    disable_throttling(unsafe { GetCurrentProcess() });
}

/// For a child process just spawned (its handle is kept open by tokio).
pub fn disable_throttling_for_child(child: &tokio::process::Child) {
    if let Some(handle) = child.raw_handle() {
        disable_throttling(HANDLE(handle as *mut std::ffi::c_void));
    }
}
