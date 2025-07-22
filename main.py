import geopandas as gpd
import pandas as pd
import numpy as np
import json
import argparse
from pathlib import Path
from shapely.geometry import box

import src.handle_database.db_io as db_io
from src.partition.cuts import partition_polygons


def get_args(argv=None):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Cut geometries by area ID using OSM data and weights")
    parser.add_argument("--area_id", type=str, required=True, help="ID of the area to cut")
    parser.add_argument("--min_addresses", type=int, required=True, help="Minimum number of addresses per piece")
    parser.add_argument("--weights_path", type=str, required=True, help="Path to the weights CSV file")
    parser.add_argument("--config", type=str, default="db_config.json",
                        help="Path to config file (default: arc/handle_database/config.json)")
    parser.add_argument("--teryt_id", type=str, default=None, help="Optional TERYT ID to filter addresses")
    return parser.parse_args(argv)


def main(args):
    '''Main function to execute the partitioning process.'''

    # Load configuration
    with open(Path(args.config).resolve()) as f:
        config = json.load(f)
    
    # Connect to database
    engine = db_io.connect(config["connection"])

    # Load data from database
    area  = db_io.load_area(engine, config["areas"], args.area_id)
    # Get bounding box of the union of area geometries
    bbox = area.union_all().bounds  # (minx, miny, maxx, maxy)
    from_crs = config["areas"]["crs"]
    print(f"Bounding box of area: {bbox}")
    weights = db_io.load_weights_from_csv(args.weights_path)

    def reproject_bbox(bbox, crs_from, crs_to):
        """Reproject bounding box coordinates from one CRS to another."""
        bbox_gdf = gpd.GeoDataFrame(geometry=[box(*bbox)], crs=crs_from)
        bbox_gdf = bbox_gdf.to_crs(crs_to)
        return bbox_gdf.geometry[0].bounds

    # Load OSM data using bounding box
    bbox_reprojected = reproject_bbox(bbox, from_crs, config["osm_data"]["crs"])
    osm_data = db_io.load_osm_data(engine, config["osm_data"], bbox=bbox_reprojected)

    # Load addresses using bbox and teryt_id if provided
    bbox_reprojected = reproject_bbox(bbox, from_crs, config["addresses"]["crs"])
    teryt_id = args.teryt_id if args.teryt_id else args.area_id
    addresses = db_io.load_addresses(engine, config["addresses"], teryt_id=teryt_id, bbox=bbox_reprojected)
    if addresses.empty:
        print(f"No addresses found for TERYT ID {teryt_id} in bbox {bbox}, loading all addresses in bbox.")
        addresses = db_io.load_addresses(engine, config["addresses"], bbox=bbox)

    result = partition_polygons(
        polygons=area,
        streets=osm_data,
        addresses=addresses,
        min_addresses=args.min_addresses,
        weights=weights,
        id_column=config["areas"]["area_id_column"]
    )

    print(result.head())

    # Save result to database
    db_io.save_partition_result(engine, result, config["output"])


if __name__ == "__main__":

    import sys
    if len(sys.argv) == 1:
        # Debug mode
        debug_argv = [
            '--area_id', '146201_1.0007',
            '--min_addresses', '10',
            '--weights_path', r'C:\Users\17ros\Documents\PYTHON\praktyki\default_weights.csv',
            '--teryt_id', '146201',
        ]
        args = get_args(debug_argv)
    else:
        args = get_args()
    main(args)
