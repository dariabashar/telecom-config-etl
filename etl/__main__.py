"""CLI:  python -m etl init-db | run --data-dir DIR [--config FILE]"""
from __future__ import annotations

import argparse
import logging
import sys

from .db import connect, init_db
from .pipeline import run_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etl")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create tables if they do not exist")
    run = sub.add_parser("run", help="load every source from the config")
    run.add_argument("--config", default="config/sources.yaml")
    run.add_argument("--data-dir", required=True)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with connect() as conn:
        init_db(conn)
        if args.command == "init-db":
            print("schema ready")
            return 0
        results = run_all(conn, args.config, args.data_dir)

    for r in results:
        print(f"{r.status:<20} {r.path:<22} {r.message}")
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
