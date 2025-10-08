from __future__ import annotations
import argparse
from pathlib import Path
from .doctor import cmd_doctor
from .config import resolve_config, print_config
from jsonschema import ValidationError

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("spineprep")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="Check environment and dependencies")
    d.add_argument("--out", type=Path, default=Path("./out"))
    d.add_argument("--pam50", type=str, default=None)
    d.add_argument("--json", type=Path, default=None)
    d.add_argument("--strict", action="store_true")

    r = sub.add_parser("run", help="Resolve config and run pipeline (stub)")
    r.add_argument("--bids", dest="bids_root", type=str, default=None)
    r.add_argument("--out", dest="output_dir", type=str, default=None)
    r.add_argument("--config", type=Path, default=None, help="YAML config path")
    r.add_argument("--print-config", action="store_true", help="Print resolved config and exit")

    sub.add_parser("version", help="Show version")
    return p

def main(argv=None) -> int:
    p = build_parser()
    a = p.parse_args(argv)
    if a.cmd == "doctor":
        return cmd_doctor(a.out, a.pam50, a.json, a.strict)
    if a.cmd == "run":
        try:
            cfg = resolve_config(a.bids_root, a.output_dir, a.config)
        except ValidationError as e:
            print(f"[config] ERROR: {e.message}")
            return 1
        if a.print_config:
            print(print_config(cfg))
            return 0
        # stub: later stages will consume cfg
        print("[run] config resolved ✓")
        return 0
    if a.cmd == "version":
        from importlib.metadata import version, PackageNotFoundError
        try:
            print(f"spineprep {version('spineprep')}")
        except PackageNotFoundError:
            print("spineprep 0.0.0")
        return 0
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
