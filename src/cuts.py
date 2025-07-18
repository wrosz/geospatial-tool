import pandas as pd
import geopandas as gpd
import numpy as np

import warnings
import requests
import polyline

from shapely.geometry import LineString, Polygon, MultiPoint
from shapely.ops import split

from intersections import find_valid_intersections
import config


def get_osrm_route(
    lon1: float, lat1: float, lon2: float, lat2: float
) -> gpd.GeoDataFrame | None:
    """
    Requests a route from OSRM between two coordinates and returns it as a GeoDataFrame.

    Args:
        lon1 (float): Longitude of the start point.
        lat1 (float): Latitude of the start point.
        lon2 (float): Longitude of the end point.
        lat2 (float): Latitude of the end point.

    Returns:
        gpd.GeoDataFrame | None: GeoDataFrame with the route LineString and duration, or None if OSRM fails.
    """
    url = (
        f"http://localhost:5000/route/v1/driving/"
        f"{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=polyline&annotations=true"
    )
    response = requests.get(url)
    data = response.json()

    if data["code"] == "Ok":
        geom = data["routes"][0]["geometry"]
        duration = data["routes"][0]["duration"]
        coords_latlon = polyline.decode(geom)
        coords_lonlat = [(lon, lat) for lat, lon in coords_latlon]
        gdf = gpd.GeoDataFrame(geometry=[LineString(coords_lonlat)], crs="EPSG:4326")
        gdf["duration"] = duration
        gdf = gdf.to_crs(config.metrical_crs)
        return gdf
    else:
        print("OSRM Error:", data)
        return None


def find_all_routes(points: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Computes OSRM routes between all unique pairs of points in the input GeoDataFrame.

    Args:
        points (gpd.GeoDataFrame): GeoDataFrame containing Point geometries. Must have at least 2 entries.

    Returns:
        gpd.GeoDataFrame: GeoDataFrame containing LineString geometries for each route between point pairs,
                          with all routes concatenated and index reset.

    Raises:
        Exception: If the input GeoDataFrame contains fewer than 2 points.
    """
    if len(points) < 2:
        raise Exception("GeoDataFrame 'points' must contain at least 2 entries")

    points_wgs84 = points.to_crs("EPSG:4326")
    routes: list[gpd.GeoDataFrame] = []

    for i in range(len(points_wgs84)):
        for j in range(i + 1, len(points_wgs84)):
            p1 = points_wgs84.iloc[i]
            p2 = points_wgs84.iloc[j]
            p1_lon, p1_lat = p1.geometry.x, p1.geometry.y
            p2_lon, p2_lat = p2.geometry.x, p2.geometry.y

            route_gdf = get_osrm_route(p1_lon, p1_lat, p2_lon, p2_lat)
            if route_gdf is not None:
                routes.append(route_gdf)

    if routes:
        routes_gdf = pd.concat(routes).reset_index(drop=True)
        return routes_gdf
    else:
        return gpd.GeoDataFrame(columns=["geometry", "duration"], crs="EPSG:4326")


def calculate_weight_by_buffer(
    line: gpd.GeoDataFrame,
    geoms_set: gpd.GeoDataFrame,
    weights: pd.DataFrame,
    buffer: float = config.buff,
    non_relevant_len: float = config.non_relevant_len,
) -> float:
    """
    Calculates a weighted average of intersected geometry lengths along a buffered line.

    Args:
        line (gpd.GeoDataFrame): GeoDataFrame with a single LineString geometry.
        geoms_set (gpd.GeoDataFrame): GeoDataFrame of geometries to intersect with the buffer.
        weights (pd.DataFrame): DataFrame with columns ["osm_key", "osm_value", "weight"].
        buffer (float): Buffer distance for the line.
        non_relevant_len (float): Minimum intersection length to consider relevant.

    Returns:
        float: Weighted average value for the intersected geometries.
    """

    # ensure line and geoms_set are in the correct CRS (metrical units)
    line_metric = line.to_crs(config.metrical_crs)
    geoms_set_metric = geoms_set.to_crs(config.metrical_crs)

    # ensure weights DataFrame has the required columns
    for colname in ["osm_key", "osm_value", "weight"]:
        if colname not in weights.columns:
            raise ValueError(f"Data frame 'weights' not defined properly: column {colname} missing")

    # create a buffer around the line
    buffered_line = line_metric.geometry.buffer(buffer)

    # ensure buffered_line is a Polygon (can be MultiPolygon, if argument line is a MultiLineString)
    if not isinstance(buffered_line, Polygon):
        buffered_line = buffered_line.union_all()

    # find geometries that intersect with the buffered line
    possible_matches = geoms_set_metric.iloc[
        geoms_set_metric.sindex.query(buffered_line, predicate="intersects")
    ]
    geoms_along_line = possible_matches[possible_matches.intersects(buffered_line)]
    geoms_along_line["intersect_geom"] = geoms_along_line.geometry.intersection(buffered_line)
    geoms_along_line["intersect_length"] = geoms_along_line["intersect_geom"].length
    relevant_geoms = geoms_along_line[geoms_along_line.intersect_length >= non_relevant_len].copy()

    # if no relevant geometries found, return 0.0
    if relevant_geoms.empty:
        warnings.warn("No relevant geometries found for the given buffer and non-relevant length, returning 0.0")
        return 0.0
    
    # calculate total weight for each geometry based on the weights DataFrame
    relevant_geoms = relevant_geoms.reset_index(drop=True)
    relevant_geoms["total_weight"] = 0

    # iterate over each osm_key in weights and calculate the total weight
    for key in weights.osm_key.unique():
        try:
            arr = relevant_geoms[["intersect_length", key]]
        except KeyError:
            continue
        w = weights[weights.osm_key == key][["osm_value", "weight"]]
        to_add = pd.merge(arr, w, how="left", left_on=key, right_on="osm_value")
        relevant_geoms.total_weight = relevant_geoms.total_weight.values + to_add.weight.fillna(0).values
    
    if sum(relevant_geoms.intersect_length) == 0:
        warnings.warn("Total intersect length is zero, returning 0.0 for weight.")  
        return 0.0
    return float(
        sum(relevant_geoms.total_weight * relevant_geoms.intersect_length)
        / sum(relevant_geoms.intersect_length)
    )


def adresses_inside_polygon(
    polygon: Polygon, adresses: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Returns addresses from a GeoDataFrame that are located within a given polygon.

    Args:
        polygon (Polygon): The polygon geometry.
        adresses (gpd.GeoDataFrame): GeoDataFrame of address points.

    Returns:
        gpd.GeoDataFrame: Subset of addresses within the polygon.
    """
    possible_matches = adresses.iloc[
        adresses.geometry.sindex.query(polygon, predicate="contains")
    ]
    return possible_matches[possible_matches.within(polygon)]


def cut_polygon_gdf(
    polygon_gdf: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    adresses: gpd.GeoDataFrame,
    min_adresses: int = config.default_min_adresses,
    weights: pd.DataFrame = config.default_weights,
    top_weights_percentage: float = config.default_top_weights_percentage,
) -> list[gpd.GeoDataFrame]:
    """
    Recursively splits a polygon using street routes to maximize balance and weight.

    Args:
        polygon_gdf (gpd.GeoDataFrame): GeoDataFrame with a single polygon geometry.
        streets (gpd.GeoDataFrame): GeoDataFrame of street geometries.
        adresses (gpd.GeoDataFrame): GeoDataFrame of address points.
        min_adresses (int): Minimum number of addresses required in each resulting part.
        weights (pd.DataFrame): DataFrame with weights for street types.
        top_weights_percentage (float): Fraction of top-weighted cuts to consider.

    Returns:
        list[gpd.GeoDataFrame]: List of GeoDataFrames for each resulting polygon piece.
    """
    if len(polygon_gdf) != 1:
        raise ValueError("Input polygon_gdf must contain exactly one polygon")
    if len(streets) == 0:
        warnings.warn("No streets provided, returning the original polygon")
        return [polygon_gdf]
    
    # ensure streets are in the correct CRS (metrical units)
    streets = streets.to_crs(config.metrical_crs)
    if not isinstance(polygon_gdf.geometry.iloc[0], Polygon):
        raise ValueError("Input polygon_gdf must contain a single Polygon geometry")
    
    # ensure adresses are in the correct CRS (metrical units)
    adresses = adresses.to_crs(config.metrical_crs)

    # Calculate the boundaries of the polygon and find intersections with streets
    if not polygon_gdf.geometry.iloc[0].is_valid:
        warnings.warn("Input polygon is not valid, returning the original polygon")
        return [polygon_gdf]
    borders = polygon_gdf["geometry"].boundary
    borders = gpd.GeoDataFrame(geometry=borders, crs=config.metrical_crs)
    intersections = find_valid_intersections(borders, streets)
    if len(intersections) < 2:
        return [polygon_gdf]
    
    # Find all routes between intersections
    cuts = find_all_routes(intersections)
    cuts["weight"] = [
        calculate_weight_by_buffer(
            gpd.GeoDataFrame(geometry=[row.geometry], crs=config.metrical_crs),
            streets,
            weights,
        )
        for _, row in cuts.iterrows()
    ]

    # add a column for a list of addresses inside each component a cut creates
    cuts["n_adresses"] = [None for _ in cuts.iterrows()]
    polygon = polygon_gdf.geometry.iloc[0]
    for i, row in cuts.iterrows():
        line = row.geometry
        result = split(polygon, line)
        cuts.at[i, "n_adresses"] = [
            len(adresses_inside_polygon(poly, adresses)) for poly in list(result.geoms)
        ]

    # Define a function to validate cuts based on address counts
    # (Check if the cut results in exactly two polygons with sufficient addresses)
    def cut_is_valid(n_adresses_list: list[int]) -> bool:
        if len(n_adresses_list) < 2:
            return False
        positive_adresses = [x for x in n_adresses_list if x > 0]
        if len(positive_adresses) < 2:
            return False
        elif len(positive_adresses) == 2:
            if positive_adresses[0] < min_adresses or positive_adresses[1] < min_adresses:
                return False
            else:
                return True
        else:
            warnings.warn(
                f"Cut results in more than 2 polygons with adresses inside: {n_adresses_list}"
            )
            return False
    cuts = cuts[[cut_is_valid(lst) for lst in cuts["n_adresses"]]]

    # If no valid cuts are found, return the original polygon
    if len(cuts) == 0:
        return [polygon_gdf]

    # Select the top cuts based on weight
    cuts = cuts[cuts["weight"] >= cuts["weight"].quantile(1 - top_weights_percentage)]

    # If no cuts remain after filtering, return the original polygon
    if len(cuts) == 0:
        warnings.warn("No valid cuts remaining after filtering by weight, returning the original polygon")
        return [polygon_gdf]

    # select the best cut based on the difference in address counts (the smaller the better)
    def adresses_difference(valid_adresses_list: list[int]) -> int:
        positive_adresses = [x for x in valid_adresses_list if x > 0]
        if len(positive_adresses) != 2:
            raise Exception("Valid n_adresses list should contain exactly two positive entries")
        return abs(positive_adresses[0] - positive_adresses[1])
    cuts["n_adresses_diff"] = [
        adresses_difference(row.n_adresses) for _, row in cuts.iterrows()
    ]
    best_cut = cuts.loc[cuts["n_adresses_diff"].idxmin()]

    # Find the relevant polygons created by the best cut (exactly two polygons with addresses)
    relevant_polys_idxs = np.array(best_cut.n_adresses) > 0

    best_line = best_cut.geometry
    best_result = split(polygon, best_line)
    best_result = pd.DataFrame(list(best_result.geoms))
    poly1 = best_result[relevant_polys_idxs].loc[0]
    poly2 = best_result[relevant_polys_idxs].loc[1]
    poly1 = gpd.GeoDataFrame(geometry=poly1, crs=config.metrical_crs)
    poly2 = gpd.GeoDataFrame(geometry=poly2, crs=config.metrical_crs)

    # Assign the number of addresses to each polygon
    n_adresses_poly_1 = best_cut.n_adresses[np.where(np.array(best_cut.n_adresses) > 0)[0][0]]
    n_adresses_poly_2 = best_cut.n_adresses[np.where(np.array(best_cut.n_adresses) > 0)[0][1]]
    poly1["n_adresses"] = n_adresses_poly_1
    poly2["n_adresses"] = n_adresses_poly_2

    pieces: list[gpd.GeoDataFrame] = []
    pieces.extend(
        cut_polygon_gdf(
            poly1,
            streets,
            adresses_inside_polygon(poly1.geometry.iloc[0], adresses),
            min_adresses,
            weights,
            top_weights_percentage,
        )
    )
    pieces.extend(
        cut_polygon_gdf(
            poly2,
            streets,
            adresses_inside_polygon(poly2.geometry.iloc[0], adresses),
            min_adresses,
            weights,
            top_weights_percentage,
        )
    )
    return pieces


def sort_polygons_spatially(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Sorts polygons spatially from outermost to innermost, each layer clockwise.

    Args:
        gdf (gpd.GeoDataFrame): GeoDataFrame of polygons.

    Returns:
        gpd.GeoDataFrame: Sorted GeoDataFrame.
    """
    def compute_angle(point, origin):
        dx = point.x - origin.x
        dy = point.y - origin.y
        angle = np.arctan2(dy, dx)
        return angle

    gdf_sorted = gdf.copy()
    gdf_sorted["centroid"] = gdf_sorted.geometry.centroid
    origin = MultiPoint(gdf_sorted["centroid"].tolist()).centroid
    gdf_sorted["angle"] = gdf_sorted["centroid"].apply(lambda p: compute_angle(p, origin))
    gdf_sorted = gdf_sorted.sort_values("angle", ascending=False)
    gdf_sorted = gdf_sorted.drop(columns=["centroid", "angle"])

    polygons_union = gdf_sorted.geometry.union_all()
    if not isinstance(polygons_union, Polygon):
        return gdf_sorted
    outer_border = polygons_union.exterior
    outer_polygons = gdf_sorted[gdf_sorted.geometry.touches(outer_border)].copy()
    remaining = gdf_sorted.drop(index=outer_polygons.index)
    gdf_sorted = outer_polygons
    while len(remaining) > 0:
        polygons_union = gdf_sorted.geometry.union_all()
        outer_border = polygons_union.boundary
        outer_polygons = remaining[remaining.geometry.touches(outer_border)].copy()
        gdf_sorted = gdf_sorted.concat(outer_polygons)
        remaining = gdf_sorted.drop(index=outer_polygons.index)

    return gdf_sorted


def pieces_to_final_data(
    pieces: list[gpd.GeoDataFrame],
    streets: gpd.GeoDataFrame,
    adresses: gpd.GeoDataFrame,
    weights: pd.DataFrame = config.default_weights,
) -> gpd.GeoDataFrame:
    """
    Combines polygon pieces into a final GeoDataFrame with neighbor and border information.

    Args:
        pieces (list[gpd.GeoDataFrame]): List of GeoDataFrames for each polygon piece (returned by cut_polygon_gdf).
        streets (gpd.GeoDataFrame): GeoDataFrame of street geometries.
        adresses (gpd.GeoDataFrame): GeoDataFrame of address points.
        weights (pd.DataFrame): DataFrame with weights for street types.

    Returns:
        gpd.GeoDataFrame: Final GeoDataFrame with geometry, id, neighbors, border weights, and address counts.
    """

    # turn pieces into a single GeoDataFrame
    gdf = pd.concat(pieces, ignore_index=True)

    # add ids based on spatial sorting
    gdf = sort_polygons_spatially(gdf)
    gdf = gdf.reset_index(drop=True)
    gdf["id"] = gdf.index

    # add neighbors based on touching geometries
    neighbors = gpd.sjoin(gdf, gdf, how="left", predicate="touches")
    gdf["neighbors"] = neighbors.groupby(neighbors.index)["id_right"].apply(list)
    gdf["neighbors"] = gdf["neighbors"].apply(
        lambda x: sorted([i for i in x if not pd.isna(i)]) if isinstance(x, list) else []
    )

    # add a dictionary of border weights
    def calculate_border_weight(id1: int, id2: int) -> float:
        poly1 = gdf.geometry.loc[id1]
        poly2 = gdf.geometry.loc[id2]
        border = poly1.intersection(poly2)
        border = gpd.GeoDataFrame(geometry=list(border.geoms), crs=config.metrical_crs)
        return calculate_weight_by_buffer(border, streets, weights)
    gdf["weights"] = gdf.apply(
        lambda row: {neigh: calculate_border_weight(row.name, neigh) for neigh in row["neighbors"]},
        axis=1,
    )

    # return the final GeoDataFrame with expected crs
    return gdf.to_crs(config.final_crs)


# example usage
adresses = gpd.read_file("sample_input_data/sample_adresses.gpkg")
area = gpd.read_file("sample_input_data/sample_area.gpkg")
streets = gpd.read_file("sample_input_data/sample_streets.gpkg")

# ensure metrical CRS is applied
adresses = adresses.to_crs(config.metrical_crs)
area = area.to_crs(config.metrical_crs)
streets = streets.to_crs(config.metrical_crs)

pieces = cut_polygon_gdf(polygon_gdf=area, streets=streets, adresses=adresses)
final_data = pieces_to_final_data(pieces, streets, adresses)
print(final_data)