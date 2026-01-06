import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon
from shapely.ops import unary_union

import src.logic_config as cfg
import src.utils as utils

metrical_crs = cfg.metrical_crs


def find_neighbors(
    pieces: list[gpd.GeoDataFrame],
    streets: gpd.GeoDataFrame,
    weights: pd.DataFrame,
) -> gpd.GeoDataFrame:
    
    # turn pieces into a single GeoDataFrame
    gdf = pd.concat(pieces, ignore_index=True)

    # add ids based on spatial sorting
    gdf = utils.sort_polygons_spatially(gdf)
    gdf = gdf.reset_index(drop=True)
    gdf["id"] = gdf.index

    # Ensure correct CRS
    gdf = gdf.to_crs(metrical_crs)

    # buffer geometries for neighbor detection
    gdf["geom_buffered"] = gdf.geometry.buffer(cfg.street_buff)

    # Create a temporary GeoDataFrame with buffered geometry as active geometry
    gdf_buffered = gdf.set_geometry("geom_buffered")

    # Find neighbors based on intersection of buffered geometries
    neighbors = gpd.sjoin(gdf_buffered, gdf_buffered, how="left", predicate="intersects")

    # Filter out self-joins
    neighbors = neighbors[neighbors.index != neighbors["id_right"]]

    # Group neighbors by original index
    gdf["neighbors"] = neighbors.groupby(neighbors.index)["id_right"].apply(list)
    gdf["neighbors"] = gdf["neighbors"].apply(
        lambda x: sorted([int(i) for i in x if not pd.isna(i)]) if isinstance(x, list) else []
    )

    return gdf


def calculate_border_weights(
    gdf: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    weights: pd.DataFrame,
    buffer: float = cfg.street_buff,
    non_relevant_len: float = cfg.non_relevant_len,
) -> gpd.GeoDataFrame:
    """
    Calculates weighted borders between neighboring polygons based on street intersections.
    
    Args:
        gdf: GeoDataFrame with polygons, 'neighbors', and 'geom_buffered' columns
        streets: GeoDataFrame of street geometries
        weights: DataFrame with columns ["osm_key", "osm_value", "weight"]
        buffer: Buffer distance for the border (not used, kept for compatibility)
        non_relevant_len: Minimum intersection length to consider relevant
    
    Returns:
        GeoDataFrame with added 'border_weights' column (dict of neighbor_id: weight)
    """
    # Ensure streets are in correct CRS
    streets = streets.to_crs(metrical_crs)
    
    # Validate weights DataFrame
    for colname in ["osm_key", "osm_value", "weight"]:
        if colname not in weights.columns:
            raise ValueError(f"DataFrame 'weights' missing column: {colname}")
    
    # Validate that geom_buffered exists
    if "geom_buffered" not in gdf.columns:
        raise ValueError("GeoDataFrame must have 'geom_buffered' column. Run find_neighbors() first.")
    
    # Initialize border_weights column
    gdf["border_weights"] = [{} for _ in range(len(gdf))]
    
    # Calculate weights for each polygon and its neighbors
    for idx, row in gdf.iterrows():
        neighbor_ids = row["neighbors"]
        
        if not neighbor_ids:
            continue
        
        # Use pre-computed buffered geometry
        poly1_buffered = row["geom_buffered"]
        
        border_weights_dict = {}
        
        for neighbor_id in neighbor_ids:
            # Use pre-computed buffered geometry for neighbor
            poly2_buffered = gdf.loc[neighbor_id, "geom_buffered"]
            
            # Get border buffer as intersection of buffered polygons
            border_buffer = poly1_buffered.intersection(poly2_buffered)
            
            # Check if intersection is valid and non-empty
            if border_buffer.is_empty or border_buffer.area < 1e-8:
                border_weights_dict[neighbor_id] = 0.0
                continue
            
            # Ensure it's a Polygon
            if border_buffer.geom_type == 'GeometryCollection':
                # Extract polygons from collection
                polys = [g for g in border_buffer.geoms if g.geom_type in ['Polygon', 'MultiPolygon']]
                if not polys:
                    border_weights_dict[neighbor_id] = 0.0
                    continue
                border_buffer = unary_union(polys)
            elif border_buffer.geom_type == 'MultiPolygon':
                border_buffer = unary_union([border_buffer])
            
            # Find streets that intersect with the border buffer
            possible_matches = streets.iloc[
                streets.sindex.query(border_buffer, predicate="intersects")
            ]
            streets_along_border = possible_matches[
                possible_matches.intersects(border_buffer)
            ].copy()
            
            if streets_along_border.empty:
                border_weights_dict[neighbor_id] = 0.0
                continue
            
            # Calculate intersection geometries and lengths
            streets_along_border["intersect_geom"] = streets_along_border.geometry.intersection(
                border_buffer
            )
            streets_along_border["intersect_length"] = streets_along_border["intersect_geom"].length
            
            # Filter by minimum length
            relevant_streets = streets_along_border[
                streets_along_border.intersect_length >= non_relevant_len
            ].copy()
            
            if relevant_streets.empty:
                border_weights_dict[neighbor_id] = 0.0
                continue
            
            # Calculate weights for each street
            relevant_streets = relevant_streets.reset_index(drop=True)
            relevant_streets["total_weight"] = 0.0
            
            # Iterate over each osm_key in weights
            for key in weights.osm_key.unique():
                if key not in relevant_streets.columns:
                    continue
                
                arr = relevant_streets[["intersect_length", key]]
                w = weights[weights.osm_key == key][["osm_value", "weight"]]
                to_add = pd.merge(arr, w, how="left", left_on=key, right_on="osm_value")
                relevant_streets["total_weight"] += to_add["weight"].fillna(0).values
            
            # Calculate weighted average
            total_length = relevant_streets["intersect_length"].sum()
            
            if total_length == 0:
                border_weights_dict[neighbor_id] = 0.0
            else:
                weighted_sum = (
                    relevant_streets["total_weight"] * relevant_streets["intersect_length"]
                ).sum()
                border_weights_dict[neighbor_id] = float(weighted_sum / total_length)
        
        gdf.at[idx, "border_weights"] = border_weights_dict
    
    return gdf