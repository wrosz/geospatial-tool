from pathlib import Path
import json
from src.handle_database import db_io as db_io
from src.partition.cuts_logic import partition_polygons


def run_partition(args):
    '''Main function to execute the partitioning process with incremental saving.'''
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
    
    if args.avg:
        # Calculate average daily number of addresses
        num_days = db_io.get_num_days_from_time_period(config["data_for_partition"]["addresses"])
    else:
        # Use total number of addresses
        num_days = None
    
    # Determine output table name
    output_table = args.output_table if args.output_table else config["data_for_partition"]["output"]["table"]
    
    # Generator-based partitioning that yields results one polygon at a time
    polygon_results = partition_polygons(
        polygons=area,
        streets=osm_data,
        addresses=addresses,
        min_addresses=args.min_addresses,
        weights=weights,
        id_column=config["data_for_partition"]["areas"]["area_id_column"],
        n_days=num_days
    )
    
    # Save results incrementally as they're generated
    for i, gdf in enumerate(polygon_results):
        if_exists = "replace" if i == 0 else "append"
        db_io.save_result(
            engine=engine,
            gdf=gdf,
            output_cfg=config["data_for_partition"]["output"],
            output_table=output_table,
            if_exists=if_exists
        )
    
    print(f"\nAll polygons partitioned and saved to table {output_table}.")