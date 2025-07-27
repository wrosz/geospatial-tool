# crs settings
metrical_crs = "EPSG:2180"  # used for finding buffers and geometry lengths

# additional parameters for finding line intersections
min_angle = 20  # minimum angle in degrees to consider an intersection valid
buff = 6  # buffer in meters for calculating intersections
non_relevant_len = 15  # minimum length of intersection to be considered relevant
streets_extension_distance = 20  # distance to extend streets for intersection detection
close_points_treshold = 50  # distance in meters to consider points close enough to be merged

default_top_weights_percentage = 0.2  # percentage of top weights to consider for partitioning