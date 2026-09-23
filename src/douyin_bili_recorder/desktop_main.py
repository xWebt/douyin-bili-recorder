from __future__ import annotations

import argparse

from .config import load_config
from .desktop import run_desktop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="douyin-recorder-desktop")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    run_desktop(load_config(args.config), debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
