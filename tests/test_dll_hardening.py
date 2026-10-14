"""PIMETextService.dll 會被載入到每一個有文字輸入框的程式（含瀏覽器的沙箱），
所以三種架構的 DLL 都要真的帶有 Control Flow Guard。

以前只在編譯時加 /guard:cf、連結時沒加 /GUARD:CF：程式碼有插樁，但 DLL 沒有 CFG
表、也沒標 GuardCF 特性，x86/x64 的 CFG 實際上沒有作用（ARM64 的連結器預設會開）。
這裡直接讀 PE 檔頭檢查，不需要 dumpbin。

DLL 是 build.bat 建出來的；沒建置時跳過，CI 在 build.bat 之後設
WIME_REQUIRE_DLLS=1 再跑一次，缺檔就算失敗。
"""

import os
import struct
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
DLLS = {
    "x86": os.path.join(ROOT, "build", "PIMETextService", "Release", "PIMETextService.dll"),
    "x64": os.path.join(ROOT, "build64", "PIMETextService", "Release", "PIMETextService.dll"),
    "arm64": os.path.join(ROOT, "build_arm64", "PIMETextService", "Release", "PIMETextService.dll"),
}

IMAGE_DLLCHARACTERISTICS_DYNAMIC_BASE = 0x0040
IMAGE_DLLCHARACTERISTICS_NX_COMPAT = 0x0100
IMAGE_DLLCHARACTERISTICS_GUARD_CF = 0x4000
IMAGE_GUARD_CF_INSTRUMENTED = 0x00000100
IMAGE_GUARD_CF_FUNCTION_TABLE_PRESENT = 0x00000400
LOAD_CONFIG_DIRECTORY = 10


def pe_hardening(path):
    """(DllCharacteristics, GuardCFFunctionCount, GuardFlags) of a PE file."""
    with open(path, "rb") as f:
        data = f.read()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe:pe + 4] == b"PE\0\0"
    sections = struct.unpack_from("<H", data, pe + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    pe32plus = magic == 0x20B
    dll_characteristics = struct.unpack_from("<H", data, opt + 70)[0]
    directories = opt + (112 if pe32plus else 96)
    rva, size = struct.unpack_from("<II", data, directories + 8 * LOAD_CONFIG_DIRECTORY)
    if not rva:
        return dll_characteristics, 0, 0
    # load config RVA -> file offset
    section_table = opt + optional_size
    offset = None
    for i in range(sections):
        s = section_table + 40 * i
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, s + 8)
        if vaddr <= rva < vaddr + max(vsize, rawsize):
            offset = rawptr + rva - vaddr
            break
    assert offset is not None, "load config directory outside the sections"
    count_at, flags_at = (0x88, 0x90) if pe32plus else (0x54, 0x58)
    count = struct.unpack_from("<Q" if pe32plus else "<I", data, offset + count_at)[0]
    flags = struct.unpack_from("<I", data, offset + flags_at)[0]
    return dll_characteristics, count, flags


class DllHardeningTests(unittest.TestCase):
    def test_control_flow_guard_in_every_architecture(self):
        require = os.environ.get("WIME_REQUIRE_DLLS") == "1"
        checked = 0
        for arch, path in DLLS.items():
            if not os.path.exists(path):
                if require:
                    self.fail("%s DLL not built: %s" % (arch, path))
                continue
            with self.subTest(arch=arch):
                characteristics, count, flags = pe_hardening(path)
                self.assertTrue(characteristics & IMAGE_DLLCHARACTERISTICS_GUARD_CF, "GuardCF not set (link without /GUARD:CF)")
                self.assertTrue(flags & IMAGE_GUARD_CF_INSTRUMENTED)
                self.assertTrue(flags & IMAGE_GUARD_CF_FUNCTION_TABLE_PRESENT)
                self.assertGreater(count, 0)
                self.assertTrue(characteristics & IMAGE_DLLCHARACTERISTICS_DYNAMIC_BASE)
                self.assertTrue(characteristics & IMAGE_DLLCHARACTERISTICS_NX_COMPAT)
                checked += 1
        if not checked:
            self.skipTest("PIMETextService.dll not built (run build.bat)")


if __name__ == "__main__":
    unittest.main()
