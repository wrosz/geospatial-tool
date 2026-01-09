# crs settings
metrical_crs = "EPSG:2180"  # used for finding buffers and geometry lengths

# additional parameters for finding line intersections
min_angle = 20  # minimum angle in degrees to consider an intersection valid
street_buff = 6  # buffer in meters for calculating intersections
non_relevant_len = 15  # minimum length of intersection to be considered relevant
streets_extension_distance = 20  # distance to extend streets for intersection detection
close_points_treshold = 50  # distance in meters to consider points close enough to be merged
max_number_of_intersections = 25  # maximum number of intersections to process (select top by weight if exceeded)

# partitioning parameters
number_of_alternatives = 3  # number of alternative routes to request from OSRM for partitioning
default_top_weights_percentage = 0.2  # percentage of top weights to consider for partitioning

# cleaning polygons parameters
min_artifact_width = 30  # buffer in meters for cleaning polygons