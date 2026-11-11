"""Build and inspect one Bambu Studio plate offline. Python 3.10+."""

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent / "examples"
PROFILE_IDS = {"machine": "printer_settings_id", "process": "print_settings_id", "filament": "filament_settings_id"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path):
    with path.open("rb") as f:
        digest = hashlib.sha256()
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def executable(name):
    if name == "blender":
        env = "BLENDER_BIN"
        choices = sorted(Path("C:/Program Files/Blender Foundation").glob("*/blender.exe"), reverse=True)
        choices.append(Path("/Applications/Blender.app/Contents/MacOS/Blender"))
    else:
        env = "BAMBU_STUDIO_BIN"
        choices = [Path("C:/Program Files/Bambu Studio/bambu-studio.exe"),
                   Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio")]
    if os.environ.get(env):
        choices = [Path(os.environ[env])]
    elif shutil.which(name):
        choices.insert(0, Path(shutil.which(name)))
    for candidate in choices:
        if candidate.is_file():
            return candidate.resolve()
    raise ValueError(f"Set {env} to the installed {name} executable")


def run(args, cwd, timeout):
    result = subprocess.run(list(map(str, args)), cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise ValueError(f"{Path(args[0]).name} exited {result.returncode}\n" +
                         result.stdout.decode("utf-8", errors="replace")[-3500:])


def blender(script, args, cwd):
    run([executable("blender"), "--background", "--factory-startup", "--disable-autoexec",
         "--python-exit-code", "1", "--python", script, "--", *args], cwd, 600)


def system_profile(root, name, parents=()):
    require(isinstance(name, str) and Path(name).name == name and "\\" not in name and "/" not in name,
            "Expected the name of an installed system preset")
    require(name not in parents, f"Preset inheritance cycle at {name}")
    variant = read(root / (name + ".json"))
    chain = (*parents, name)
    result = system_profile(root, variant["inherits"], chain) if variant.get("inherits") else {}
    for include in variant.get("include", []):
        template = system_profile(root, include, chain)
        result.update({k: v for k, v in template.items() if k not in ("name", "type", "from", "setting_id", "instantiation")})
    result.update({k: v for k, v in variant.items() if k not in ("inherits", "include")})
    return result


def profiles(studio, spec, work):
    roots = [studio.parent / "resources/profiles/BBL", studio.parent.parent / "Resources/profiles/BBL",
             Path("/usr/share/BambuStudio/profiles/BBL")]
    if os.environ.get("BAMBU_PROFILES"):
        roots = [Path(os.environ["BAMBU_PROFILES"])]
    root = next((p for p in roots if (p / "machine").is_dir()), None)
    require(root, "Set BAMBU_PROFILES to the installed profiles/BBL directory")
    full = {}
    for kind, key in PROFILE_IDS.items():
        name = spec[kind]
        cfg = system_profile(root / kind, name)
        require(cfg.get("instantiation") == "true", f"Select a concrete {kind} preset")
        compatible = cfg.get("compatible_printers", [])
        require(not compatible or spec["machine"] in compatible, f"Incompatible {kind} preset")
        cfg[key] = [name] if kind == "filament" else name
        full[kind] = cfg
    cfg = full["process"]
    overrides = spec.get("process_settings", {})
    allowed = {"enable_support", "support_type", "wall_loops", "brim_type", "brim_width",
               "sparse_infill_density", "sparse_infill_pattern", "top_shell_layers", "bottom_shell_layers"}
    require(isinstance(overrides, dict) and overrides.keys() <= allowed and
            all(isinstance(v, str) and v and "\n" not in v for v in overrides.values()),
            "Unsupported process_settings; see the job format")
    cfg.update(overrides)
    for kind, settings in full.items():
        write(work / f"{kind}.json", settings)
    return full


def slice_audit(package, full, spec, preview):
    with ZipFile(package) as archive:
        require(archive.testzip() is None, "Corrupt 3MF")
        paths = [n for n in archive.namelist() if n.endswith(".gcode")]
        require(paths == ["Metadata/plate_1.gcode"], "Expected exactly one sliced plate")
        data = archive.read(paths[0])
        checksum = archive.read(paths[0] + ".md5").decode().strip().lower()
        require(hashlib.md5(data).hexdigest() == checksum, "G-code checksum mismatch")
        cfg = json.loads(archive.read("Metadata/project_settings.config"))
        for kind, key in PROFILE_IDS.items():
            require(cfg[key] == full[kind][key], f"Slicer changed {key}")
        for key in ("nozzle_diameter", "printer_model", "printable_area", "printable_height",
                    "machine_start_gcode", "machine_end_gcode"):
            require(full["machine"].get(key) and cfg[key] == full["machine"][key], f"Machine mismatch: {key}")
        for key in ("machine_start_gcode", "machine_end_gcode"):
            require(re.search(r"(?m)^\s*[GMT]\d+", cfg[key]), f"Unresolved {key}")
        require(cfg["curr_bed_type"] == spec["bed"] and
                float(cfg["layer_height"]) == float(full["process"]["layer_height"]), "Plate or layer height changed")
        for key, value in spec.get("process_settings", {}).items():
            require(cfg[key] == value, f"Slicer changed {key} to {cfg[key]}")
        info = ET.fromstring(archive.read("Metadata/slice_info.config"))
        plate, = info.findall("plate")
        fields = {m.get("key"): m.get("value") for m in plate.findall("metadata")}
        require(fields.get("outside") == "false", "Object outside build volume or missing placement metadata")
        objects = plate.findall("object")
        names = Counter(Path(p["stl"]).name for p in spec["parts"])
        require(Counter(o.get("name") for o in objects if o.get("skipped") == "false") == names,
                "Missing, skipped or unexpected objects on plate")
        layer_data = data.decode("utf-8").replace("\r\n", "\n").split("; CHANGE_LAYER\n")[1:]
        count = re.search(rb"(?m)^; total layer number:\s*(\d+)", data)
        require(count and len(layer_data) == int(count[1]) and len(layer_data) > 0, "Layer counts disagree")
        started = set()
        object_id = None
        for line in layer_data[0].splitlines():
            if line.startswith(("; OBJECT_ID: ", "; start printing object, unique label id: ")):
                object_id = line.rsplit(" ", 1)[-1]
            elif line.startswith("; stop printing object"):
                object_id = None
            elif object_id and re.match(r"^G[123] .*[XY][-.\d]", line):
                amount = re.search(r" E([.\d]+)", line)
                if amount and float(amount[1]) > 0:
                    started.add(object_id)
        require(started == {o.get("identify_id") for o in objects}, "First-layer extrusion missing for a part")
        first = json.loads(archive.read("Metadata/plate_1.json"))
        require(Counter(b["name"] for b in first["bbox_objects"] if b["area"] > 0) == names,
                "Incomplete first-layer footprints")
        seconds, grams = int(fields["prediction"]), float(fields["weight"])
        require(seconds > 0 and math.isfinite(grams) and grams > 0, "Empty time or material estimate")
        preview.write_bytes(archive.read("Metadata/plate_1.png"))
        return {"printer": cfg["printer_model"], "nozzle_mm": cfg["nozzle_diameter"],
                "layer_mm": float(cfg["layer_height"]), "plate": spec["bed"],
                "filament": spec["filament"], "layers": len(layer_data), "objects_on_first_layer": len(started),
                "estimated_seconds": seconds, "estimated_grams": grams, "support_used": fields["support_used"],
                "warnings": [w.attrib for w in plate.findall("warning")]}


def prepare(spec_path, out, demo=False):
    out = out.resolve()
    require(not out.exists(), "Choose a new output directory for this revision")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=".bambu-") as temp:
        work = Path(temp)
        result = work / "job"
        result.mkdir()
        if demo:
            spec_path = EXAMPLES / "tag.json"
            blender(EXAMPLES / "make_tag.py", [result], work)
        spec = read(spec_path)
        for key in ("request", "design", "acceptance", "machine", "process", "filament", "bed"):
            require(isinstance(spec.get(key), str) and spec[key].strip(), f"Missing {key}")
        require(isinstance(spec.get("parts"), list) and spec["parts"], "Expected at least one part")
        sources = spec.get("source_files", [])
        require(isinstance(sources, list), "source_files must be a list of local design files")
        for name in sources:
            require(isinstance(name, str) and Path(name).name == name and not re.search(r'[/\\:*?"<>|]', name)
                    and Path(name).suffix.lower() in {".blend", ".3dm", ".fcstd", ".step", ".stp", ".scad", ".py", ".f3d", ".zip"},
                    "Expected a local editable model, modelling script, or source ZIP")
            if not demo:
                shutil.copyfile(spec_path.parent / name, result / name)
        names = set()
        for part in spec["parts"]:
            name = part["stl"]
            require(Path(name).name == name and not re.search(r'[/\\:*?"<>|]', name) and
                    name.lower().endswith(".stl") and name.casefold() not in names, "Expected distinct local STL filenames")
            names.add(name.casefold())
            if not demo:
                shutil.copyfile(spec_path.parent / name, result / name)
        write(result / "job.json", spec)
        blender(HERE / "geometry.py", [result / "job.json", result / "geometry.json"], work)
        studio = executable("bambu-studio")
        full = profiles(studio, spec, work)
        package = result / ("print-" + uuid.uuid4().hex[:16] + ".gcode.3mf")
        run([studio, "--load-settings", f"{work / 'machine.json'};{work / 'process.json'}",
             "--load-filaments", work / "filament.json", "--curr-bed-type", spec["bed"],
             "--orient", "0", "--arrange", "1", "--slice", "0", "--export-3mf", package,
             *(result / p["stl"] for p in spec["parts"])], work, 900)
        stats = slice_audit(package, full, spec, result / "plate.png")
        report = {"stage": "sliced", "file": package.name, "sha256": sha256(package), "slice": stats}
        write(result / "report.json", report)
        result.rename(out)
        return report


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    subs = cli.add_subparsers(dest="action", required=True)
    subs.add_parser("demo", help="Build the cable tag and slice it offline").add_argument("output", type=Path)
    custom = subs.add_parser("job", help="Audit and slice a custom design")
    custom.add_argument("spec", type=Path)
    custom.add_argument("output", type=Path)
    args = cli.parse_args()
    try:
        print(json.dumps(prepare(getattr(args, "spec", None), args.output, args.action == "demo"),
                         ensure_ascii=True, indent=2))
    except (KeyError, IndexError, TypeError, OSError, ValueError, BadZipFile, ET.ParseError, subprocess.TimeoutExpired) as e:
        sys.exit(f"Preparation stopped: {e}")
