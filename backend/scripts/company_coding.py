"""Standalone explicit existing-company C application operator; never a disposable pilot."""

import argparse
from pathlib import Path

from nexus.execution.coding_operator import CODING_MODES, coding_mode


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit local Nexus coding application")
    parser.add_argument("--mode", choices=sorted(CODING_MODES), required=True)
    parser.add_argument("--coding-config", type=Path, required=True)
    parser.add_argument("--coding-config-sha", required=True)
    parser.add_argument("--planning-credential-fd", type=int)
    parser.add_argument("--coding-credential-fd", type=int)
    parser.add_argument("--admin-database-fd", type=int)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5189)
    coding_mode(parser.parse_args())


if __name__ == "__main__":
    main()
