import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from main import get_arguments

def main():

    if len(sys.argv) == 1:
        # import warnings
        # warnings.simplefilter("error")
        sys.argv.extend(["merge",
            "--area_id" ,"1419", "--min_addresses","2", "--max_addresses", "10", "--avg"
        ])

    args = get_arguments(argv=sys.argv[1:])
    args.func(args)


if __name__ == "__main__":
    main()

