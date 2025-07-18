import geopandas as gpd
from pathlib import Path

# Get the current directory
current_dir = Path.cwd()

# Go one level up to the parent directory
parent_dir = current_dir.parent

streets = gpd.read_file(parent_dir / "sample_input_data/streets.gpkg")
adresses = gpd.read_file(parent_dir / "sample_input_data/adresses.gpkg")
area = gpd.read_file(parent_dir / "sample_input_data/area.gpkg")
