from __future__ import annotations

import argparse

import uvicorn

from .config import load_config
from .webapp import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="douyin-recorder-ui")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    uvicorn.run(create_app(config), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
