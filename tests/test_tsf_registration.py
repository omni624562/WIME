"""Uninstalling (and every upgrade) runs regsvr32 /u on the x86 and x64
PIMETextService.dll, which ends in libIME2's ImeModule::unregisterServer()
(libIME2/src/ImeModule.cpp). It called RegisterCategory() for
GUID_TFCAT_TIPCAP_SYSTRAYSUPPORT right after ITfInputProcessorProfiles::Unregister()
had removed the whole TIP\\{clsid} key, recreating an orphan
TIP\\{clsid}\\Category key under both HKLM\\SOFTWARE\\Microsoft\\CTF and its
WOW6432Node view. GUID_TFCAT_TIPCAP_UIELEMENTENABLED was never unregistered.

Registering and unregistering touch HKLM, so these tests read the source the
way test_composition_placeholder.py does."""

import os
import re
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
IME_MODULE_CPP = os.path.join(ROOT, "libIME2", "src", "ImeModule.cpp")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _function(source, signature):
    """The body of a function defined at column 0, without its // comments."""
    match = re.search(r"\n" + re.escape(signature) + r"\s*\{(.*?)\n\}", source, re.S)
    if match is None:
        raise AssertionError("%s not found" % signature)
    return re.sub(r"//[^\n]*", "", match.group(1))


class UnregisterServerTests(unittest.TestCase):
    def setUp(self):
        source = _read(IME_MODULE_CPP)
        self.register = _function(
            source, "HRESULT ImeModule::registerServer(wchar_t* imeName, LangProfileInfo* langs, int count)")
        self.unregister = _function(source, "HRESULT ImeModule::unregisterServer()")

    def test_unregistering_registers_nothing(self):
        self.assertNotRegex(self.unregister, r"\bRegisterCategory\(")

    def test_every_registered_category_is_unregistered(self):
        registered = re.findall(r"\bRegisterCategory\(textServiceClsid_, (GUID_\w+)", self.register)
        unregistered = re.findall(r"\bUnregisterCategory\(textServiceClsid_, (GUID_\w+)", self.unregister)
        self.assertIn("GUID_TFCAT_TIPCAP_SYSTRAYSUPPORT", registered)   # the regex still finds them
        self.assertEqual(sorted(unregistered), sorted(registered))


if __name__ == "__main__":
    unittest.main()
