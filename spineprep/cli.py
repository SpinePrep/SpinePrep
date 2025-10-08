from __future__ import annotations
import argparse
from pathlib import Path
from .doctor import cmd_doctor

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("spineprep")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="Check environment and dependencies")
    d.add_argument("--out", type=Path, default=Path("./out"))
    d.add_argument("--pam50", type=str, default=None, help="Explicit PAM50 directory")
    d.add_argument("--json", type=Path, default=None, help="Optional extra JSON path")
    d.add_argument("--strict", action="store_true", help="Treat warnings as errors")

    sub.add_parser("version", help="Show version")
    return p

def main(argv=None) -> int:
    p = build_parser()
    a = p.parse_args(argv)
    if a.cmd == "doctor":
        return cmd_doctor(a.out, a.pam50, a.json, a.strict)
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
