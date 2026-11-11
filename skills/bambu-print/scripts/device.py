"""Official Studio handoff and optional voska/bambu 0.3.0 LAN transport."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from prepare import executable, read, require, sha256


class LanError(ValueError):
    def __init__(self, code, reason):
        self.code = code
        super().__init__(f"LAN exit {code}: {reason}")


def package_for(folder):
    report = read(folder / "report.json")
    name = report["file"]
    require(report["stage"] == "sliced" and re.fullmatch(r"print-[0-9a-f]{16}\.gcode\.3mf", name),
            "Expected an audited job directory")
    path = folder / name
    require(sha256(path) == report["sha256"], "3MF changed since slice review; prepare a new revision")
    return path, report["sha256"]


def receipt_path(path):
    base = os.environ.get("BAMBU_PRINT_STATE") or os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local/state"
    return root / "idea-to-bambu" / (path.name + ".json")


def reserve(path, digest, route, printer):
    marker = receipt_path(path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        with marker.open("x", encoding="utf-8") as f:
            json.dump({"sha256": digest, "route": route, "printer": printer,
                       "time": datetime.now(timezone.utc).isoformat()}, f)
            f.flush()
            os.fsync(f.fileno())
    except FileExistsError:
        raise ValueError("A handoff was already attempted for this job. Inspect the device; do not resend.")


@contextmanager
def sending_to(path, printer):
    """Serialize LAN sends from this host using the same configured printer alias."""
    root = receipt_path(path).parent
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(printer.casefold().encode()).hexdigest()
    with (root / f"device-{key}.lock").open("a+b") as f:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Another send to this printer is in progress") from exc
        yield


def lan_tool():
    tool = os.environ.get("BAMBU_CLI") or shutil.which("bambu")
    require(tool, "Install voska/bambu 0.3.0 or use the studio command")
    version = subprocess.run([tool, "version"], capture_output=True, text=True, timeout=10, check=True)
    require(re.match(r"bambu 0\.3\.0\b", version.stdout), "Expected voska/bambu version 0.3.0")
    return tool


def lan(tool, printer, *args):
    run = subprocess.run([tool, "--json", "--no-input", "--printer", printer, *map(str, args)],
                         capture_output=True, encoding="utf-8", errors="replace", timeout=360)
    try:
        data = json.loads(run.stdout)
    except ValueError:
        raise ValueError(f"LAN client returned no usable reply (exit {run.returncode}); check device status")
    if run.returncode:
        reason = data.get("error", {}).get("message") or str(data.get("preflight", {}).get("failed", "unavailable"))
        raise LanError(run.returncode, reason)
    require(data.get("printer") == printer, "LAN client returned a different printer")
    return data


def observe(status, name):
    job = status["job"]
    reported = job.get("name") or Path(job.get("file", "").replace("\\", "/")).name.removesuffix(".gcode.3mf")
    state = status["state"]
    if reported != name:
        if state in {"RUNNING", "PAUSE", "PREPARE", "SLICING"} and reported:
            return {"stage": "different_job", "device_state": state}
        return {"stage": "awaiting_matching_job", "device_state": state}
    stage = {"PREPARE": "preparing", "RUNNING": "printing", "FINISH": "device_finished",
             "FAILED": "failed", "PAUSE": "paused"}.get(state, "awaiting_device_state")
    if status["errors"]["blocking"] and stage != "failed":
        stage = "device_error"
    return {"stage": stage, "device_state": state, "layer": job.get("layer"), "layers": job.get("total_layers"),
            "percent": job.get("percent"), "remaining_min": job.get("remaining_min")}


def preflight(tool, printer, path, slot):
    data = lan(tool, printer, "preflight", path, "--slot", slot)
    result = data["preflight"]
    require(result["result"] == "PASS", f"Preflight: {result['result']}")
    return result


def dispatch(action, folder, printer, slot=None, ready=False, timeout=3600):
    path, digest = package_for(folder.resolve())
    require(printer and printer.strip(), "Choose the intended printer")
    if action == "studio":
        studio = executable("bambu-studio")
        reserve(path, digest, "studio", printer)
        subprocess.Popen([str(studio), str(path)])
        return {"stage": "opened_in_studio", "target": printer, "file": path.name}
    tool = lan_tool()
    if action in {"check", "send"}:
        require(re.fullmatch(r"(?:[1-4]|[A-D][1-4])", slot or ""), "Use an AMS slot; use Studio for an external spool")
        if action == "check":
            return preflight(tool, printer, path, slot)
        require(ready, "send requires --ready after checking this job, material and clear build plate")
        with sending_to(path, printer), tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / path.name
            shutil.copyfile(path, snapshot)
            require(sha256(snapshot) == digest, "File changed during handoff")
            preflight(tool, printer, snapshot, slot)
            reserve(path, digest, "lan", printer)
            reply = lan(tool, printer, "print", "send", snapshot, "--slot", slot, "--confirm")
            require(reply.get("sent") is True, "Ambiguous start reply; use watch, do not resend")
    marker = read(receipt_path(path))
    require(marker["printer"] == printer and marker["sha256"] == digest and marker["route"] == "lan",
            "Job receipt does not match this LAN target")
    until = time.monotonic() + timeout
    last = {}
    while True:
        try:
            current = observe(lan(tool, printer, "status")["status"], path.name.removesuffix(".gcode.3mf"))
        except (LanError, subprocess.TimeoutExpired) as exc:
            if action != "watch" or isinstance(exc, LanError) and exc.code != 8:
                raise
            current = {"stage": "connection_interrupted"}
        if action == "send" or current["stage"] in {"device_finished", "failed", "paused", "device_error", "different_job"}:
            return current
        if current != last:
            print(json.dumps(current), file=sys.stderr, flush=True)
            last = current
        remaining = until - time.monotonic()
        if remaining <= 0:
            return {"stage": "monitor_timeout", "last": last}
        time.sleep(min(15, remaining))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("studio", "check", "send", "watch"):
        cmd = sub.add_parser(action)
        cmd.add_argument("folder", type=Path)
        cmd.add_argument("--printer", required=True, help="Studio device name or configured LAN alias")
        if action in {"check", "send"}:
            cmd.add_argument("--slot", required=True)
        if action == "send":
            cmd.add_argument("--ready", action="store_true")
        if action == "watch":
            cmd.add_argument("--timeout", default=3600, type=int, help="Seconds; safe to run watch again")
    try:
        result = dispatch(**vars(parser.parse_args()))
        print(json.dumps(result, ensure_ascii=True, indent=2))
        if result.get("stage") in {"monitor_timeout", "failed", "paused", "device_error", "different_job",
                                   "awaiting_matching_job", "awaiting_device_state"}:
            sys.exit(2)
    except (KeyError, TypeError, OSError, ValueError, subprocess.SubprocessError) as e:
        sys.exit(f"Device step stopped: {e}")
