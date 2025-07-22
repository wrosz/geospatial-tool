import pandas as pd
import geopandas as gpd
import numpy as np

import warnings

from shapely.geometry import LineString, Polygon, MultiPoint
from shapely.ops import split

from src.partition.intersections import find_valid_intersections
from src.logic_config import default_top_weights_percentage, metrical_crs
from src.utils import calculate_weight_by_buffer, addresses_inside_polygon, get_osrm_route


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


def cut_single_polygon(
    polygon_gdf: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    addresses: gpd.GeoDataFrame,
    min_addresses: int,
    weights: pd.DataFrame,
    top_weights_percentage: float = default_top_weights_percentage,
    depth: int = 0
) -> list[gpd.GeoDataFrame]:
    """
    Recursively splits a polygon using street routes to maximize balance and weight.

    Args:
        polygon_gdf (gpd.GeoDataFrame): GeoDataFrame with a single polygon geometry.
        streets (gpd.GeoDataFrame): GeoDataFrame of street geometries.
        addresses (gpd.GeoDataFrame): GeoDataFrame of address points.
        min_addresses (int): Minimum number of addresses required in each resulting part.
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
    
    # ensure polygon_gdf is in the correct CRS (metrical units)
    polygon_gdf = polygon_gdf.to_crs(metrical_crs)
    
    # ensure streets are in the correct CRS (metrical units)
    streets = streets.to_crs(metrical_crs)
    if not isinstance(polygon_gdf.geometry.iloc[0], Polygon):
        raise ValueError("Input polygon_gdf must contain a single Polygon geometry")
    
    # ensure addresses are in the correct CRS (metrical units)
    addresses = addresses.to_crs(metrical_crs)    

    # define an "n_addresses" column if it doesn't exist
    if "n_addresses" not in polygon_gdf.columns:    
        polygon_gdf["n_addresses"] = len(addresses_inside_polygon(polygon_gdf.geometry.iloc[0], addresses))

    if polygon_gdf["n_addresses"].iloc[0] < min_addresses:
        warnings.warn(
            f"Polygon has fewer addresses ({polygon_gdf['n_addresses'].iloc[0]}) than the minimum required ({min_addresses}), returning the original polygon"
        )
        return [polygon_gdf]

    # Calculate the boundaries of the polygon and find intersections with streets
    if not polygon_gdf.geometry.iloc[0].is_valid:
        warnings.warn("Input polygon is not valid, returning the original polygon")
        return [polygon_gdf]
    borders = polygon_gdf["geometry"].boundary
    borders = gpd.GeoDataFrame(geometry=borders, crs=metrical_crs)
    intersections = find_valid_intersections(borders, streets)
    if len(intersections) < 2:
        if depth < 1:
            print("Not enough intersections found, returning the original polygon")
        return [polygon_gdf]
    
    # Find all routes between intersections
    cuts = find_all_routes(intersections).to_crs(metrical_crs)
    cuts["weight"] = [
        calculate_weight_by_buffer(
            gpd.GeoDataFrame(geometry=[row.geometry], crs=metrical_crs),
            streets,
            weights,
        )
        for _, row in cuts.iterrows()
    ]

    # add a column for a list of addresses inside each component a cut creates
    cuts["n_addresses"] = [None for _ in cuts.iterrows()]
    polygon = polygon_gdf.geometry.iloc[0]
    for i, row in cuts.iterrows():
        line = row.geometry
        result = split(polygon, line)
        cuts.at[i, "n_addresses"] = [
            len(addresses_inside_polygon(poly, addresses)) for poly in list(result.geoms)
        ]

    # Define a function to validate cuts based on address counts
    # (Check if the cut results in exactly two polygons with sufficient addresses)
    def cut_is_valid(n_addresses_list: list[int]) -> bool:
        if len(n_addresses_list) < 2:
            return False
        positive_addresses = [x for x in n_addresses_list if x > 0]
        if len(positive_addresses) < 2:
            return False
        elif len(positive_addresses) == 2:
            if positive_addresses[0] < min_addresses or positive_addresses[1] < min_addresses:
                return False
            else:
                return True
        else:
            # warnings.warn(
            #     f"Cut results in more than 2 polygons with addresses inside: {n_addresses_list}"
            # )
            return False
    cuts = cuts[[cut_is_valid(lst) for lst in cuts["n_addresses"]]]

    # If no valid cuts are found, return the original polygon
    if len(cuts) == 0:
        if depth < 1:
            print("No valid cuts found, returning the original polygon")
        return [polygon_gdf]

    # Select the top cuts based on weight
    cuts = cuts[cuts["weight"] >= cuts["weight"].quantile(1 - top_weights_percentage)]

    # If no cuts remain after filtering, return the original polygon
    if len(cuts) == 0:
        if depth < 1:
            print("No valid cuts remaining after filtering by weight, returning the original polygon")
        return [polygon_gdf]

    # select the best cut based on the difference in address counts (the smaller the better)
    def addresses_difference(valid_addresses_list: list[int]) -> int:
        positive_addresses = [x for x in valid_addresses_list if x > 0]
        if len(positive_addresses) != 2:
            raise Exception("Valid n_addresses list should contain exactly two positive entries")
        return abs(positive_addresses[0] - positive_addresses[1])
    cuts["n_addresses_diff"] = [
        addresses_difference(row.n_addresses) for _, row in cuts.iterrows()
    ]
    best_cut = cuts.loc[cuts["n_addresses_diff"].idxmin()]

    # Find the relevant polygons created by the best cut (exactly two polygons with addresses)
    relevant_polys_idxs = np.array(best_cut.n_addresses) > 0

    best_line = best_cut.geometry
    best_result = split(polygon, best_line)
    best_result = pd.DataFrame(list(best_result.geoms))
    poly1 = best_result[relevant_polys_idxs].iloc[0]
    poly2 = best_result[relevant_polys_idxs].iloc[1]
    poly1 = gpd.GeoDataFrame(geometry=poly1, crs=metrical_crs)
    poly2 = gpd.GeoDataFrame(geometry=poly2, crs=metrical_crs)

    # Assign the number of addresses to each polygon
    n_addresses_poly_1 = best_cut.n_addresses[np.where(np.array(best_cut.n_addresses) > 0)[0][0]]
    n_addresses_poly_2 = best_cut.n_addresses[np.where(np.array(best_cut.n_addresses) > 0)[0][1]]
    poly1["n_addresses"] = n_addresses_poly_1
    poly2["n_addresses"] = n_addresses_poly_2

    pieces: list[gpd.GeoDataFrame] = []
    pieces.extend(
        cut_single_polygon(
            poly1,
            streets,
            addresses_inside_polygon(poly1.geometry.iloc[0], addresses),
            min_addresses,
            weights,
            top_weights_percentage,
            depth + 1
        )
    )
    pieces.extend(
        cut_single_polygon(
            poly2,
            streets,
            addresses_inside_polygon(poly2.geometry.iloc[0], addresses),
            min_addresses,
            weights,
            top_weights_percentage,
            depth + 1
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
        gdf_sorted = pd.concat([gdf_sorted, outer_polygons], ignore_index=True)
        remaining = remaining.drop(index=outer_polygons.index)

    return gdf_sorted


def pieces_to_final_data(
    pieces: list[gpd.GeoDataFrame],
    streets: gpd.GeoDataFrame,
    weights: pd.DataFrame,
) -> gpd.GeoDataFrame:
    """
    Combines polygon pieces into a final GeoDataFrame with neighbor and border information.

    Args:
        pieces (list[gpd.GeoDataFrame]): List of GeoDataFrames for each polygon piece (returned by cut_polygon_gdf).
        streets (gpd.GeoDataFrame): GeoDataFrame of street geometries.
        addresses (gpd.GeoDataFrame): GeoDataFrame of address points.
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
        border = gpd.GeoDataFrame(geometry=list(border.geoms), crs=metrical_crs)
        return calculate_weight_by_buffer(border, streets, weights)
    gdf["weights"] = gdf.apply(
        lambda row: {neigh: calculate_border_weight(row.name, neigh) for neigh in row["neighbors"]},
        axis=1,
    )

    # return the final GeoDataFrame with expected crs
    return gdf


# | Final function to partition multiple polygons

def partition_polygons(
    polygons: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    addresses: gpd.GeoDataFrame,
    min_addresses: int,
    weights: pd.DataFrame,
    id_column: str,
    top_weights_percentage: float = default_top_weights_percentage,
) -> gpd.GeoDataFrame:
    """
    Partitions multiple polygons into smaller pieces based on street routes and address distribution.

    Args:
        polygons (gpd.GeoDataFrame): GeoDataFrame of polygons to partition.
        streets (gpd.GeoDataFrame): GeoDataFrame of street geometries.
        addresses (gpd.GeoDataFrame): GeoDataFrame of address points.
        min_addresses (int): Minimum number of addresses required in each resulting part.
        weights (pd.DataFrame): DataFrame with weights for street types.
        id_column (str): Column name for unique identifiers in the polygons GeoDataFrame.
        top_weights_percentage (float): Fraction of top-weighted cuts to consider.

    Returns:
        gpd.GeoDataFrame: Final GeoDataFrame with partitioned polygons, neighbors, and border weights.
    """
    dataframes = []
    polygons = polygons.to_crs(metrical_crs)
    addresses = addresses.to_crs(metrical_crs)
    streets = streets.to_crs(metrical_crs)

    # Narrow addresses and streets to only those near the polygons using spatial index for efficiency
    # Buffer polygons slightly to ensure we include nearby features (e.g., 100 meters)
    buffered_polygons = polygons.geometry.buffer(100)

    # Use spatial index to filter addresses
    if not addresses.empty:
        address_sindex = addresses.sindex
        address_idx = set()
        for poly in buffered_polygons:
            possible_matches_index = list(address_sindex.intersection(poly.bounds))
            precise_matches = addresses.iloc[possible_matches_index][addresses.iloc[possible_matches_index].intersects(poly)]
            address_idx.update(precise_matches.index)
        addresses = addresses.loc[list(address_idx)]

    # Use spatial index to filter streets
    if not streets.empty:
        street_sindex = streets.sindex
        street_idx = set()
        for poly in buffered_polygons:
            possible_matches_index = list(street_sindex.intersection(poly.bounds))
            precise_matches = streets.iloc[possible_matches_index][streets.iloc[possible_matches_index].intersects(poly)]
            street_idx.update(precise_matches.index)
        streets = streets.loc[list(street_idx)]

    # filter geoms_set to keep only those where at least one column from weights.osm_key is not null
    osm_keys = weights.osm_key.unique()
    streets = streets[streets[osm_keys].notnull().any(axis=1)]
    print(f"\nFiltered streets to {len(streets)} relevant geometries based on weights and spatial data.")

    for i, polygon in polygons.iterrows():
        print(f"\nPartitioning polygon {i + 1}/{len(polygons)}: {polygon[id_column]}")
        initial_id = polygon[id_column]
        pieces = cut_single_polygon(
            gpd.GeoDataFrame(geometry=[polygon.geometry], crs=metrical_crs),
            streets,
            addresses,
            min_addresses,
            weights,
            top_weights_percentage
        )
        gdf = pieces_to_final_data(pieces, streets, weights)
        gdf["id"] = str(initial_id) + "." + gdf["id"].astype(str)
        print(f"Partitioned polygon {initial_id} into {len(gdf)} pieces.")
        dataframes.append(gdf)
    
    return pd.concat(dataframes, ignore_index=True).reset_index(drop=True)