"""Explicit private preview invitation inspection/renewal; no account initialization or reset."""

import argparse
import sys
from pathlib import Path

from nexus.company.pilot_invitation import (
    inspect_owner_invitation,
    renew_expired_owner_invitation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["inspect-owner", "renew-expired-owner"])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (args.mode == "renew-expired-owner") != (args.output is not None):
        parser.error("Only renewal requires a fresh private --output file")
    try:
        result = (
            inspect_owner_invitation(args.root)
            if args.mode == "inspect-owner"
            else renew_expired_owner_invitation(args.root, args.output)
        )
    except Exception:
        # Validation/OS exceptions can contain private inputs. Never print their values.
        sys.stderr.write('{"status":"owner_invitation_unavailable"}\n')
        return 1
    sys.stdout.write(result.model_dump_json() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
