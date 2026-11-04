"""Explicit migration CLI. Uses only the database selected by the process."""
import argparse
import json
import os
from pathlib import Path

from .db import connect, init_db
from .migrations import REVISION, status, validate_structure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--check', action='store_true', help='Inspect migration state without applying changes')
    actions.add_argument('--apply', action='store_true', help='Apply additive migration to the explicitly configured database')
    args = parser.parse_args()
    if args.check and not os.getenv('DATABASE_URL', '').strip():
        path = Path(os.getenv('COMPAC_DB', str(Path(__file__).resolve().parents[1] / '.data' / 'compac.db')))
        if not path.exists():
            print(json.dumps({'revision': REVISION, 'applied': False, 'checksum_valid': None, 'structure_valid': False}))
            return 1
    if args.apply:
        init_db(allow_migrations=True)
    with connect() as db:
        state = status(db)
        state['structure_valid'] = False
        if state['applied'] and state['checksum_valid']:
            try:
                validate_structure(db)
                state['structure_valid'] = True
            except RuntimeError:
                pass
    print(json.dumps(state))
    return 0 if state['applied'] and state['checksum_valid'] and state['structure_valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
