# projection
univ_epsg = 2180
univ_crs = f"EPSG:{univ_epsg}"

# geometry type default weights
default_weights = {
    ("highway","primary"): 6,
    ("highway","secondary"): 5,
    ("highway","tertiary"): 4,
    ("highway","unclassified"): 3,
    ("highway","residential"): 2,
    ("highway","living"): 1
}
default_weights_percentage = 0.2
default_min_adresses = 10

# additional parameters
min_angle = 20
buff = 6
non_relevant_len = 15
