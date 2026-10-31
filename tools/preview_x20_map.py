#!/usr/bin/env python3
"""Create an offline browser viewer from an already decoded PRIVATE map JSON."""
import argparse
import json
from pathlib import Path

from mihome_cloud import build_map_snapshot
from mihome_cloud.map_view import write_map_view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--name', default='')
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text())
        write_map_view(build_map_snapshot(data, name=args.name), args.output)
    except Exception:
        parser.exit(1, 'Unable to create private viewer. Check input and a new or managed output directory.\n')
    print('Private offline viewer written. Serve its directory on loopback to view index.html.')


if __name__ == '__main__':
    main()
