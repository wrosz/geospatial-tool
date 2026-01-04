# script to debug main.py commands

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from main import get_arguments

# enter the command you want to debug here
command = 'cut --area_id 146201_1.0001.0012 --min_addresses 40 --config dev/debug_db_config.json --output_table debug_partition_output'

def main():

    if len(sys.argv) == 1:
        # import warnings
        # warnings.simplefilter("error")
        sys.argv.extend(command.split())

    args = get_arguments(argv=sys.argv[1:])
    args.func(args)


if __name__ == "__main__":
    main()

