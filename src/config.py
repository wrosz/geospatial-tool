import pandas as pd

# projection
metrical_crs = "EPSG:2180"  # used for finding buffers
final_crs = "EPSG:4326"

# geometry type default weights
default_weights = pd.DataFrame([
    ["highway","primary", 6],
    ["highway","secondary", 5],
    ["highway","tertiary", 4],
    ["highway","unclassified", 3],
    ["highway","residential", 2],
    ["highway","living", 1]
])
default_weights.columns = ["osm_key", "osm_value", "weight"]

default_top_weights_percentage = 0.2
default_min_adresses = 10

# additional parameters
min_angle = 20
buff = 6  # buffer in meters (for calculating ways' intersections)
non_relevant_len = 15
