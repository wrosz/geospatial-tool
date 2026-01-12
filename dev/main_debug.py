# script to debug main.py commands

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from main import get_arguments

# enter the command you want to debug here
command = 'cut --area_id 166101_1.0103 --min_addresses 30 --output_table opole_centrum_test'

def main():

    if len(sys.argv) == 1:
        # Enable warnings as errors for debugging
        # import warnings
        # warnings.simplefilter("error")

        sys.argv.extend(command.split())

    args = get_arguments(argv=sys.argv[1:])
    args.func(args)


if __name__ == "__main__":
    main()

