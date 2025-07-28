from pathlib import Path
import json
import src.handle_database.db_io as db_io
from src.merge.merge_logic import merge_polygons_by_shortest_route
import src.handle_database.db_io as db_io

import logging
logging.basicConfig(level=logging.INFO)

def run_merge(args):
    '''Main function to execute the merging process.'''

    # Load configuration
    with open(Path(args.config).resolve()) as f:
        config = json.load(f)
    
    # Connect to database
    engine = db_io.connect(config["connection"])

    # Load all relevant data from the database
    data = db_io.load_all_data_with_bbox(engine, config["data_for_merge"], args)
    area, addresses = data["area"], data["addresses"]

    if args.avg:
        # Calculate average daily number of addresses
        num_days = db_io.get_num_days_from_time_period(config["data_for_merge"]["addresses"])
    else:
        # Use total number of addresses
        num_days = None


    print("\nMerging polygons based on shortest route...")
    result = merge_polygons_by_shortest_route(
        gdf=area,
        addresses=addresses,
        min_addresses=args.min_addresses,
        max_addresses=args.max_addresses,
        id_col=config["data_for_merge"]["areas"]["area_id_column"],
        n_days=num_days
    )

    # Save result to database
    db_io.save_result(engine, result, config["data_for_merge"]["output"], args.output_table)