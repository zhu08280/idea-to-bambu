import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

SKILL = Path(__file__).resolve().parents[1] / "skills/bambu-print"
sys.path.insert(0, str(SKILL / "scripts"))
import device
import prepare


class Profiles(unittest.TestCase):
    def test_inheritance_includes_and_child_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare.write(root / "base.json", {"name": "base", "bed": 180, "speed": 2})
            prepare.write(root / "start.json", {"name": "start", "machine_start_gcode": "G28", "speed": 3})
            prepare.write(root / "unit.json", {"name": "unit", "inherits": "base", "include": ["start"], "speed": 4})
            self.assertEqual(prepare.system_profile(root, "unit"),
                             {"name": "unit", "machine_start_gcode": "G28", "speed": 4, "bed": 180})
            prepare.write(root / "base.json", {"inherits": "unit"})
            with self.assertRaisesRegex(ValueError, "cycle"):
                prepare.system_profile(root, "unit")


class Delivery(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {"BAMBU_PRINT_STATE": str(self.root / "state")})
        env.start()
        self.addCleanup(env.stop)
        self.id = "print-0123456789abcdef"
        self.file = self.root / (self.id + ".gcode.3mf")
        self.file.write_bytes(b"fixture")
        self.digest = prepare.sha256(self.file)
        prepare.write(self.root / "report.json", {"stage": "sliced", "file": self.file.name, "sha256": self.digest})

    def status(self, name, state):
        return {"status": {"state": state, "job": {"name": name, "layer": 1}, "errors": {"blocking": False}}}

    def test_artifact_change_blocks_both_transports(self):
        self.file.write_bytes(b"changed")
        for action in ("studio", "send"):
            with self.assertRaisesRegex(ValueError, "changed"):
                device.dispatch(action, self.root, "desk", "A1", True)
        self.assertFalse(device.receipt_path(self.file).exists())

    @patch.object(device, "lan_tool", return_value="fake")
    @patch.object(device, "lan")
    def test_ready_and_preflight_before_any_send(self, lan, _):
        with self.assertRaisesRegex(ValueError, "ready"):
            device.dispatch("send", self.root, "desk", "A1")
        lan.assert_not_called()
        lan.return_value = {"preflight": {"result": "FAIL"}}
        with self.assertRaisesRegex(ValueError, "Preflight"):
            device.dispatch("send", self.root, "desk", "A1", True)
        self.assertFalse(device.receipt_path(self.file).exists())
        self.assertEqual(lan.call_count, 1)
        with self.assertRaisesRegex(ValueError, "external spool"):
            device.dispatch("send", self.root, "desk", "ext", True)

    @patch.object(device, "lan_tool", return_value="fake")
    @patch.object(device, "lan")
    def test_lost_ack_never_repeats_send_and_watch_recovers(self, lan, _):
        preflight = {"preflight": {"result": "PASS"}}
        lan.side_effect = [preflight, subprocess.TimeoutExpired("fake", 1), preflight,
                           self.status(self.id, "FINISH")]
        with self.assertRaises(subprocess.TimeoutExpired):
            device.dispatch("send", self.root, "desk", "A1", True)
        with self.assertRaisesRegex(ValueError, "already attempted"):
            device.dispatch("send", self.root, "desk", "A1", True)
        self.assertEqual(device.dispatch("watch", self.root, "desk")["stage"], "device_finished")
        with self.assertRaisesRegex(ValueError, "receipt"):
            device.dispatch("watch", self.root, "other")
        calls = [call.args[2] for call in lan.call_args_list]
        self.assertEqual(calls, ["preflight", "print", "preflight", "status"])

    def test_parallel_sends_serialize_per_printer(self):
        with device.sending_to(self.file, "Desk"):
            with self.assertRaisesRegex(ValueError, "in progress"):
                with device.sending_to(self.file, "desk"):
                    self.fail("Second writer entered")
        with device.sending_to(self.file, "Desk"):
            pass

    @patch.object(device, "lan_tool", return_value="fake")
    @patch.object(device, "lan")
    def test_accepted_reply_still_checks_identity(self, lan, _):
        lan.side_effect = [{"preflight": {"result": "PASS"}}, {"sent": True}, self.status("other", "RUNNING")]
        self.assertEqual(device.dispatch("send", self.root, "desk", "A1", True)["stage"], "different_job")
        self.assertTrue(device.receipt_path(self.file).exists())

    def test_old_finish_and_matched_pause(self):
        for name, state, expected in [("old", "FINISH", "awaiting_matching_job"), (self.id, "PAUSE", "paused"),
                                      (self.id, "FAILED", "failed"), (self.id, "PREPARE", "preparing")]:
            self.assertEqual(device.observe(self.status(name, state)["status"], self.id)["stage"], expected)
        status = self.status(self.id, "RUNNING")["status"]
        status["errors"]["blocking"] = True
        self.assertEqual(device.observe(status, self.id)["stage"], "device_error")

    @patch.object(device, "lan_tool", return_value="fake")
    @patch.object(device, "lan", side_effect=device.LanError(8, "unreachable"))
    def test_watch_connection_loss_is_not_completion(self, lan, _):
        device.reserve(self.file, self.digest, "lan", "desk")
        result = device.dispatch("watch", self.root, "desk", timeout=0)
        self.assertEqual(result["stage"], "monitor_timeout")
        self.assertEqual(result["last"]["stage"], "connection_interrupted")
        self.assertEqual(lan.call_args.args[2], "status")

    @patch.object(device.subprocess, "Popen")
    @patch.object(device, "executable", return_value=Path("studio"))
    def test_studio_only_opens_package(self, _, popen):
        result = device.dispatch("studio", self.root, "desk")
        self.assertEqual(result["stage"], "opened_in_studio")
        popen.assert_called_once_with(["studio", str(self.file.resolve())])
        with self.assertRaisesRegex(ValueError, "already attempted"):
            device.dispatch("studio", self.root, "desk")


@unittest.skipUnless(os.environ.get("BAMBU_INTEGRATION") == "1", "needs Blender and Bambu Studio")
class OfflineSlice(unittest.TestCase):
    def test_real_demo_then_reject_wrong_diameter_and_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            demo = root / "demo"
            report = prepare.prepare(None, demo, demo=True)
            self.assertEqual(report["stage"], "sliced")
            self.assertEqual(report["slice"]["objects_on_first_layer"], 1)
            self.assertEqual(report["slice"]["layers"], 15)
            self.assertEqual(hashlib.sha256((demo / report["file"]).read_bytes()).hexdigest(), report["sha256"])
            spec = json.loads((demo / "job.json").read_text("utf-8"))
            shutil.copyfile(demo / "tag.stl", demo / "second.stl")
            second = {**spec["parts"][0], "stl": "second.stl"}
            prepare.write(demo / "pair.json", {**spec, "parts": [*spec["parts"], second]})
            pair = prepare.prepare(demo / "pair.json", root / "pair")
            self.assertEqual(pair["slice"]["objects_on_first_layer"], 2)
            self.assertEqual(prepare.sha256(root / "pair/tag.blend"), prepare.sha256(demo / "tag.blend"))
            damaged = root / "corrupt.3mf"
            with ZipFile(demo / report["file"]) as source, ZipFile(damaged, "w") as output:
                for name in source.namelist():
                    output.writestr(name, b"G28\n" if name.endswith(".gcode") else source.read(name))
            with self.assertRaisesRegex(ValueError, "checksum"):
                prepare.slice_audit(damaged, {}, spec, root / "preview.png")
            for field, value, error in [("size_mm", [30, 20, 4], "Expected"),
                                        ("vertical_bores", [{"center_xy_mm": [-10, 0], "diameter_mm": 6}], "Bore wall")]:
                part = {**spec["parts"][0], field: value}
                prepare.write(demo / "invalid.json", {**spec, "parts": [part]})
                with self.assertRaisesRegex(ValueError, error):
                    prepare.prepare(demo / "invalid.json", root / "bad")
                self.assertFalse((root / "bad").exists())


if __name__ == "__main__":
    unittest.main()
