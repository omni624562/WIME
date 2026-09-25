"""Several text services of the same IME (one per application) share the code
table (CinTable) but each has its own copy of the settings, which it re-reads
from config.json at most every 3 seconds. After a table switch, an instance that
had not re-read the file yet switched the shared table back, and the instances
reloaded it back and forth several times (5 table parses for one change seen in
the audit), with the old table active in between.
"""

import os
import unittest
from unittest import mock

import cinbase_harness as h


def setUpModule():
    global _appdata, _real_play
    _appdata = h.IsolatedAppData()
    _real_play = h.cinbase.winsound.PlaySound
    h.cinbase.winsound.PlaySound = lambda *a, **k: None


def tearDownModule():
    h.cinbase.winsound.PlaySound = _real_play
    _appdata.close()


@h.requires_tables
class SharedTableTests(unittest.TestCase):
    IME = "chedayi"

    def setUp(self):
        h._ime_class(self.IME)
        self.module = h._modules[self.IME]
        self.reset_tables()
        self.loads = []
        loader = h.cinbase.LoadCinTable
        real_run = loader.run

        def run(thread):
            self.loads.append(thread.cbTS.cfg.selCinType)
            real_run(thread)

        def start(thread):          # background loads run synchronously here
            run(thread)
        for name, func in (("run", run), ("start", start)):
            patcher = mock.patch.object(loader, name, func)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        h.remove_user_config(self.IME)
        self.reset_tables()

    def reset_tables(self):
        for table in (self.module.CinTable, self.module.RCinTable, self.module.HCinTable):
            table.cin = None
            table.curCinType = None
            table.lastLoadFailure = 0.0

    def request(self, service):
        service.checkConfigChange()    # what handleRequest runs before every request

    def test_table_switch_is_loaded_once(self):
        a = h.make_service(self.IME)
        b = h.make_service(self.IME)
        self.assertEqual(self.loads, [0])
        self.loads.clear()

        path = h.write_user_config(self.IME, {"selCinType": 1})
        os.utime(path, (1_900_000_000, 1_900_000_000))   # a clearly new modification time
        a.cfg._lastUpdateTime = 0.0     # A re-reads config.json now; B read it moments ago
        for service in (a, b, a, b):
            self.request(service)

        self.assertEqual(self.loads, [1], "shared table reloaded back and forth")
        self.assertEqual(self.module.CinTable.curCinType, 1)
        self.assertIs(a.cin, self.module.CinTable.cin)
        self.assertIs(b.cin, self.module.CinTable.cin)

    def test_out_of_range_table_is_not_reloaded_by_every_new_instance(self):
        h.write_user_config(self.IME, {"selCinType": 99})
        a = h.make_service(self.IME)
        table = a.cin
        b = h.make_service(self.IME)
        c = h.make_service(self.IME)
        self.request(a)
        self.assertEqual(self.loads, [99], "each new instance re-parsed the table")
        self.assertIs(b.cin, table)
        self.assertIs(c.cin, table)
        self.assertTrue(table.chardefs, "the shared table was emptied by a reload")

    def test_reverse_lookup_table_switch_is_loaded_once(self):
        starts = []
        loader = h.cinbase.LoadRCinTable
        real_run = loader.run

        def start(thread):
            starts.append(thread.cbTS.cfg.selRCinType)
            real_run(thread)
        patcher = mock.patch.object(loader, "start", start)
        patcher.start()
        self.addCleanup(patcher.stop)

        h.write_user_config(self.IME, {"imeReverseLookup": True, "selRCinType": 0})
        a = h.make_service(self.IME)
        b = h.make_service(self.IME)
        for service in (a, b):
            self.request(service)
        self.assertEqual(starts, [0])
        starts.clear()

        path = h.write_user_config(self.IME, {"imeReverseLookup": True, "selRCinType": 18})
        os.utime(path, (1_900_000_000, 1_900_000_000))
        a.cfg._lastUpdateTime = 0.0
        for service in (a, b, a, b):
            self.request(service)
        self.assertEqual(starts, [18], "reverse lookup table reloaded back and forth")
        self.assertEqual(self.module.RCinTable.curCinType, 18)


if __name__ == "__main__":
    unittest.main()
