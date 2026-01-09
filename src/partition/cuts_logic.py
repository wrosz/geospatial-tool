import geopandas as gpd
import pandas as pd
import warnings
from shapely.geometry import Polygon, GeometryCollection
from shapely.ops import linemerge, split

import src.partition.intersections_logic as inters_logic
import src.partition.partition_utils as partition_utils
import src.utils as utils
import src.logic_config as cfg

metrical_crs = cfg.metrical_crs


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

            route_gdf = utils.get_osrm_route(p1_lon, p1_lat, p2_lon, p2_lat, alternatives=cfg.number_of_alternatives)
            if route_gdf is not None:
                routes.append(route_gdf)

    if routes:
        routes_gdf = pd.concat(routes).reset_index(drop=True)
        return routes_gdf
    else:
        return gpd.GeoDataFrame(columns=["geometry", "duration", "weight"], crs="EPSG:4326")
    


def trim_routes(routes, polygons):
    # Reproject
    routes = routes.to_crs(metrical_crs)
    polygons = polygons.to_crs(metrical_crs)

    # Union the polygon (likely just returns itself since there's one row)
    polygon_union = polygons.geometry.unary_union

    # Clip routes to polygon
    clipped_routes = gpd.clip(routes, polygon_union)

    # Skip lines that aren't valid
    clipped_routes = clipped_routes[
        clipped_routes.geometry.type.isin(["LineString", "MultiLineString"])
    ]

    # Merge multi-lines efficiently
    is_multi = clipped_routes.geometry.type == "MultiLineString"
    clipped_routes.loc[is_multi, "geometry"] = [
        linemerge(geom) for geom in clipped_routes.loc[is_multi, "geometry"]
    ]

    # Create buffered boundary once
    buffered_boundary = polygon_union.boundary.buffer(cfg.street_buff)

    # Spatially filter routes before overlay (optional but safe)
    intersects = clipped_routes.intersects(buffered_boundary)
    clipped_routes = clipped_routes[intersects]

    # Subtract boundary buffer from the routes
    boundary_gdf = gpd.GeoDataFrame(geometry=[buffered_boundary], crs=metrical_crs)
    clipped_routes = gpd.overlay(clipped_routes, boundary_gdf, how='difference')

    # Drop empty geometries
    clipped_routes = clipped_routes[~clipped_routes.geometry.is_empty]
    
    # Pick unique geometries
    clipped_routes = clipped_routes.drop_duplicates(subset='geometry')

    return clipped_routes.reset_index(drop=True)
    


# For merging fragments of polygons, if a cut results in more than two pieces
def join_gdfs_longest_border(gdf1, gdf2):
    """
    Join polygons from gdf2 to polygons in gdf1 based on the longest shared border.

    Args:
        gdf1 (GeoDataFrame): The first GeoDataFrame with multiple polygons.
        gdf2 (GeoDataFrame): The second GeoDataFrame with multiple polygons.

    Returns:
        geopandas.GeoDataFrame: A new GeoDataFrame containing merged polygons.
    """

    merged_gdf = gdf1[["geometry"]].copy()
    leftover = []

    for idx2, row2 in gdf2.iterrows():
        neighbors_from_merged = merged_gdf[merged_gdf.apply(lambda x: utils.shared_border(x.geometry, row2.geometry) is not None, axis=1)].copy()
        if neighbors_from_merged.empty:
            warnings.warn(f"No shared border found for polygon {row2.name} in gdf2, will not merge.")
            leftover.append(idx2)
            continue
        neighbors_from_merged["border_length"] = neighbors_from_merged.apply(lambda x: utils.shared_border(x.geometry, row2.geometry).length, axis=1)

        best_neighbor = neighbors_from_merged.loc[neighbors_from_merged["border_length"].idxmax()]
        merged_row = best_neighbor.geometry.union(row2.geometry)
        merged_gdf.loc[merged_gdf.index == best_neighbor.name, "geometry"] = [merged_row]

    if leftover:
        warnings.warn(f"Polygons {leftover} in gdf2 were not merged due to no shared border with gdf1.")
    
    return merged_gdf, gdf2.loc[leftover].copy()


def cut_single_polygon(
    polygon_gdf: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    addresses: gpd.GeoDataFrame,
    min_addresses: int,
    weights: pd.DataFrame,
    top_weights_percentage: float = cfg.default_top_weights_percentage,
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
        depth (int): Recursion depth for debugging purposes and printing messages.

    Returns:
        list[gpd.GeoDataFrame]: List of GeoDataFrames for each resulting polygon piece.
    """

    if len(polygon_gdf) != 1 or not isinstance(polygon_gdf.geometry.iloc[0], Polygon):
        raise ValueError("Input polygon_gdf must contain exactly one polygon")
    if len(streets) == 0:
        warnings.warn("No streets provided, returning the original polygon")
        return [polygon_gdf]
    
    # ensure data is in the correct CRS
    polygon_gdf = polygon_gdf.to_crs(metrical_crs)
    streets = streets.to_crs(metrical_crs)
    addresses = addresses.to_crs(metrical_crs)

    # define an "n_addresses" column if it doesn't exist
    if "n_addresses" not in polygon_gdf.columns:    
        polygon_gdf["n_addresses"] = len(utils.addresses_inside_polygon(polygon_gdf.geometry.iloc[0], addresses))
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
    intersections = inters_logic.find_valid_intersections(borders, streets, weights)
    if len(intersections) < 2:
        if depth == 0:
            print("Not enough intersections found, returning the original polygon")
        return [polygon_gdf]
    
    # Find all routes between intersections
    cuts = find_all_routes(intersections).to_crs(metrical_crs).loc[:, ["geometry", "weight"]]
    cuts = trim_routes(cuts, polygon_gdf)


    # add a column for a list of addresses inside each component a cut creates
    cuts["n_addresses"] = [None for _ in cuts.iterrows()]
    cuts["result"] = [None for _ in cuts.iterrows()]
    polygon = polygon_gdf.geometry.iloc[0]
    for i, row in cuts.iterrows():
        line = row.geometry
        result = split(polygon, utils.extend_linestring(line, cfg.streets_extension_distance))
        cuts.at[i, "n_addresses"] = [
            len(utils.addresses_inside_polygon(poly, addresses)) for poly in result.geoms
        ]
        cuts.at[i, "result"] = result
        # If the cut results in more than two polygons, merge them based on shared borders
        # and re-calculate the number of addresses in the merged polygons
        if len(result.geoms) > 2:
            gdf = gpd.GeoDataFrame(geometry=list(result.geoms), crs=metrical_crs)
            gdf["n_addresses"] = cuts.at[i, "n_addresses"]
            if any(gdf.nlargest(2, "n_addresses").n_addresses < min_addresses):
                continue  # Skip cuts that don't result in two large polygons
            main_polys = gdf.nlargest(2, "n_addresses").copy()
            rest = gdf.drop(index=main_polys.index).copy()
            merged = join_gdfs_longest_border(main_polys, rest)[0]
            cuts.at[i, "geometry"] = utils.shared_border(
                merged.geometry.iloc[0], merged.geometry.iloc[1]
            )
            cuts.at[i, "result"] = GeometryCollection(list(merged.geometry))
            cuts.at[i, "n_addresses"] = [
                len(utils.addresses_inside_polygon(poly, addresses)) for poly in merged.geometry
            ]

    # Define a function to validate cuts based on address counts
    # (Check if the cut results in exactly two polygons with sufficient addresses)
    def cut_is_valid(n_addresses_list: list[int]) -> bool:
        if len(n_addresses_list) != 2:
            return False
        else:
            return all(n >= min_addresses for n in n_addresses_list)
    cuts = cuts[[cut_is_valid(lst) for lst in cuts["n_addresses"]]]

    # If no valid cuts are found, return the original polygon
    if len(cuts) == 0:
        if depth == 0:
            print("No valid cuts found, returning the original polygon")
        return [polygon_gdf]

    # Select top cuts based on weight
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
    best_result = best_cut.result
    
    # Extract the two polygon pieces
    poly1_geom = list(best_result.geoms)[0]
    poly2_geom = list(best_result.geoms)[1]
    
    # CLEAN ARTIFACTS IMMEDIATELY AFTER CUT
    poly1_geom, poly2_geom = partition_utils.clean_two_pieces_after_cut(
        poly1_geom,
        poly2_geom
    )
    
    n_addr_1 = len(utils.addresses_inside_polygon(poly1_geom, addresses))
    n_addr_2 = len(utils.addresses_inside_polygon(poly2_geom, addresses))
    
    # Create GeoDataFrames for each piece
    poly1 = gpd.GeoDataFrame(
        geometry=[poly1_geom], 
        crs=metrical_crs,
        data={'n_addresses': [n_addr_1]},
        index=[0]
    )
    poly2 = gpd.GeoDataFrame(
        geometry=[poly2_geom], 
        crs=metrical_crs,
        data={'n_addresses': [n_addr_2]},
        index=[0]
    )
    
    print(f"Cutting polygon at depth {depth}: {n_addr_1} addresses in first piece, {n_addr_2} in second piece")
    
    # Recursively cut each piece (they're already clean!)
    pieces: list[gpd.GeoDataFrame] = []
    pieces.extend(
        cut_single_polygon(
            poly1,
            streets,
            utils.addresses_inside_polygon(poly1.geometry.iloc[0], addresses),
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
            utils.addresses_inside_polygon(poly2.geometry.iloc[0], addresses),
            min_addresses,
            weights,
            top_weights_percentage,
            depth + 1
        )
    )
    
    return pieces


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
    gdf = utils.sort_polygons_spatially(gdf)
    gdf = gdf.reset_index(drop=True)
    gdf["id"] = gdf.index

    # add neighbors based on touching geometries
    gdf = partition_utils.find_neighbors(gdf)
    # add border weights between neighbors
    gdf = partition_utils.calculate_border_weights(gdf, streets, weights)

    # reorder columns
    gdf = gdf[["id", "n_addresses", "geometry", "neighbors", "border_weights"]]

    return gdf


# | Final function to partition multiple polygons


def partition_polygons(
    polygons: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    addresses: gpd.GeoDataFrame,
    min_addresses: int,
    weights: pd.DataFrame,
    id_column: str,
    top_weights_percentage: float = cfg.default_top_weights_percentage,
    n_days: int | None = None
):
    """
    Generator that partitions multiple polygons into smaller pieces based on street routes 
    and address distribution. Yields results one polygon at a time.

    Args:
        polygons (gpd.GeoDataFrame): GeoDataFrame of polygons to partition.
        streets (gpd.GeoDataFrame): GeoDataFrame of street geometries.
        addresses (gpd.GeoDataFrame): GeoDataFrame of address points.
        min_addresses (int): Minimum number of addresses required in each resulting part.
        weights (pd.DataFrame): DataFrame with weights for street types.
        id_column (str): Column name for unique identifiers in the polygons GeoDataFrame.
        top_weights_percentage (float): Fraction of top-weighted cuts to consider.
        n_days (int | None): Number of days for average address calculation, if applicable.

    Yields:
        gpd.GeoDataFrame: GeoDataFrame with partitioned pieces for each polygon.
    """
    if n_days is not None:
        if n_days <= 0:
            raise ValueError("n_days must be greater than 0 to calculate daily averages.")
        print(f"Using {n_days} days for address calculations to return daily averages.")
        min_addresses = min_addresses * n_days

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
            utils.addresses_inside_polygon(polygon.geometry, addresses),
            min_addresses,
            weights,
            top_weights_percentage
        )
        gdf = pieces_to_final_data(pieces, streets, weights)
        gdf["id"] = str(initial_id) + "." + gdf["id"].astype(str).str.zfill(4)
        print(f"Partitioned polygon {initial_id} into {len(gdf)} pieces.")

        # Apply n_days transformation if needed
        if n_days is not None:
            gdf["n_addresses"] = gdf["n_addresses"] / n_days
            gdf.rename(columns={"n_addresses": "avg_addresses"}, inplace=True)
        
        # Yield this polygon's results
        yield gdf