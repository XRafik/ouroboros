"""Portable oracle/scope checks. These do not assert native ETW/UNC behavior."""
import copy
import unittest
import unc_probe as probe


class Gates(unittest.TestCase):
    def observation(self):
        return dict(complete=True, unsupported=0, events_lost=0, log_buffers_lost=0,
                    realtime_buffers_lost=0, stop_code=0, process_code=0, close_code=0,
                    records=[dict(pid=4, port=p, opcode=12, count=1)
                             for p in (50000, 50001, 445)])

    def test_each_loss_error_and_decode_gap_invalidates_zero(self):
        base = self.observation()
        probe.require_observer(base, (50000, 50001))
        for field in ("unsupported", "events_lost", "log_buffers_lost", "realtime_buffers_lost",
                      "stop_code", "process_code", "close_code"):
            with self.subTest(field=field):
                bad = copy.deepcopy(base)
                bad[field] = 1
                with self.assertRaises(probe.Incomplete):
                    probe.require_observer(bad, (50000, 50001))

    def test_missing_evidence_is_never_zero(self):
        bad = self.observation()
        del bad["events_lost"]
        with self.assertRaises(KeyError):
            probe.require_observer(bad, (50000, 50001))

    def test_each_window_requires_both_heartbeats(self):
        bad = self.observation()
        bad["records"] = bad["records"][1:]
        with self.assertRaises(probe.Incomplete):
            probe.require_observer(bad, (50000, 50001))

    def test_controls_cannot_count_as_smb_or_refused_attempt(self):
        evidence = self.observation()
        self.assertEqual(probe.count(evidence, {445, 139}, attempts=True), 1)
        self.assertEqual(probe.count(evidence, {50002}, attempts=True), 0)
        evidence["records"][2]["opcode"] = 13  # Disconnect alone is not a positive.
        self.assertEqual(probe.count(evidence, {445}, attempts=True), 0)
        self.assertEqual(probe.count(evidence, {445}), 1)  # Still invalidates safe absence.

    def test_targets_are_unique_and_numeric_loopback(self):
        used = set()
        for _ in range(20):
            address = probe.ipaddress.ip_address(probe.fresh_target(used))
            self.assertTrue(address.is_loopback)
            self.assertNotEqual(str(address), "127.0.0.1")
        self.assertEqual(len(used), 20)


if __name__ == "__main__":
    unittest.main()
