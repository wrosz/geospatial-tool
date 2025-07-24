from pathlib import Path
import json
from src.handle_database import db_io as db_io
from src.partition.cuts_logic import partition_polygons

def run_partition(args):
    '''Main function to execute the partitioning process.'''

    # Load configuration
    with open(Path(args.config).resolve()) as f:
        config = json.load(f)
    
    # Connect to database
    engine = db_io.connect(config["connection"])

    # Load weights from CSV
    weights = db_io.load_weights_from_csv(args.weights_path, config["weights"])

    # Load all relevant data from the database
    data = db_io.load_all_data_with_bbox(engine, config["data_for_partition"], args)
    area, addresses, osm_data = data["area"], data["addresses"], data.get("osm_data")

    result = partition_polygons(
        polygons=area,
        streets=osm_data,
        addresses=addresses,
        min_addresses=args.min_addresses,
        weights=weights,
        id_column=config["data_for_partition"]["areas"]["area_id_column"]
    )

    # Save result to database
    db_io.save_result(engine, result, config["data_for_partition"]["output"], args.output_table)

    