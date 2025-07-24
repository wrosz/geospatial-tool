from pathlib import Path
import json
import src.handle_database.db_io as db_io
from src.merge.merge_logic import merge_polygons_by_shortest_route
import src.handle_database.db_io as db_io

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

    result = merge_polygons_by_shortest_route(
        gdf=area,
        addresses=addresses,
        min_addresses=args.min_addresses,
        max_addresses=args.max_addresses,
        id_col=config["data_for_merge"]["areas"]["area_id_column"]
    )

    # Save result to database
    db_io.save_partition_result(engine, result, config["data_for_merge"]["output"], args.output_table)