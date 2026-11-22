"""Copy a species' races and their pieces under new editor IDs. See fsftools/race_copy.py.

    python sf_race_copy.py <config.toml> --out DIR
"""
import sys

from fsftools.race_copy import main

if __name__ == '__main__':
    sys.exit(main())
