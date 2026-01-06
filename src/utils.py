import geopandas as gpd
import requests
import polyline
import warnings
import pandas as pd
from shapely.geometry import Polygon, LineString, MultiLineString, Point
from shapely.ops import linemerge, unary_union
import numpy as np
from shapely.geometry import MultiPoint

import src.logic_config as cfg

metrical_crs = cfg.metrical_crs


def get_osrm_route(
    lon1: float, lat1: float, lon2: float, lat2: float
) -> gpd.GeoDataFrame | None:
    """
    Requests a route from OSRM between two coordinates and returns it as a GeoDataFrame.
    To run this, you need to have an OSRM server running locally (see readme for details).

    Args:
        lon1 (float): Longitude of the start point.
        lat1 (float): Latitude of the start point.
        lon2 (float): Longitude of the end point.
        lat2 (float): Latitude of the end point.

    Returns:
        gpd.GeoDataFrame | None: GeoDataFrame with the route LineString and duration, or None if OSRM fails.
        (in crs EPSG:4326)
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
        return gdf
    else:
        print("OSRM Error:", data)
        return None


def calculate_weight_by_buffer(
    line: gpd.GeoDataFrame,
    geoms_set: gpd.GeoDataFrame,
    weights: pd.DataFrame,
    buffer: float = cfg.street_buff,
    non_relevant_len: float = cfg.non_relevant_len,
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
    line_metric = line.to_crs(metrical_crs)
    geoms_set_metric = geoms_set.to_crs(metrical_crs)

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
            warnings.warn(f"Key '{key}' not found in geometries dataframe, skipping.")
            continue
        w = weights[weights.osm_key == key][["osm_value", "weight"]]
        to_add = pd.merge(arr, w, how="left", left_on=key, right_on="osm_value")
        relevant_geoms.total_weight = relevant_geoms.total_weight.values + to_add.weight.fillna(0).values
    
    if sum(relevant_geoms.intersect_length) == 0:
        # warnings.warn("Total intersect length is zero, returning 0.0 for weight.")  
        return 0.0
    return float(
        sum(relevant_geoms.total_weight * relevant_geoms.intersect_length)
        / sum(relevant_geoms.intersect_length)
    )



def addresses_inside_polygon(
    polygon: Polygon, addresses: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Returns addresses from a GeoDataFrame that are located within a given polygon.

    Args:
        polygon (Polygon): The polygon geometry.
        addresses (gpd.GeoDataFrame): GeoDataFrame of address points.

    Returns:
        gpd.GeoDataFrame: Subset of addresses within the polygon.
    """
    possible_matches = addresses.iloc[
        addresses.geometry.sindex.query(polygon, predicate="contains")
    ]
    return possible_matches[possible_matches.within(polygon)]



def sort_by_distance_from_point(
    gdf: gpd.GeoDataFrame, point: Point
) -> gpd.GeoDataFrame:
    """
    Sorts a GeoDataFrame of polygons by their distance to a given point.

    Args:
        gdf (gpd.GeoDataFrame): GeoDataFrame of polygons.
        point (Point): The point to measure distance from.

    Returns:
        gpd.GeoDataFrame: Sorted GeoDataFrame.
    """
    gdf = gdf.copy()
    gdf["distance"] = gdf.geometry.distance(point)
    gdf = gdf.sort_values("distance", ascending=False)
    gdf.drop(columns=["distance"], inplace=True)
    return gdf


def sort_outer_polygons_spatially(gdf: gpd.GeoDataFrame, how:str, pts = None) -> gpd.GeoDataFrame:
    '''Sorts outer polygons spatially based on a given method and points.
    Args:
        gdf (gpd.GeoDataFrame): GeoDataFrame of polygons.
        how (str): Method to sort polygons. Options are 'angle' or 'distance'.
        pts (gpd.GeoDataFrame, optional): Points to consider for sorting, if how == 'distance' (distance is measured from centroid of these points).
            If None, uses the union of polygons.

        Returns:
            gpd.GeoDataFrame: Sorted GeoDataFrame.
    '''

    if how not in ['angle', 'distance']:
        raise ValueError("Parameter 'how' must be either 'angle' or 'distance'.")
    
    gdf_sorted = gdf.to_crs(metrical_crs).copy()
    
    if how == 'distance':
        # Sort polygons by distance from the centroid

        if pts is None or pts.empty:
            pts_centroid = gdf_sorted.geometry.centroid

        else:
            pts = pts.to_crs(metrical_crs)
            pts_inside = addresses_inside_polygon(gdf.union_all(), pts).copy()
            pts_metr = pts_inside.to_crs(metrical_crs) if pts_inside is not None else gdf_sorted.geometry.centroid
            pts_centroid = MultiPoint(pts_metr.geometry.tolist()).centroid if isinstance(pts_metr, gpd.GeoDataFrame) else pts_metr

        gdf_sorted = sort_by_distance_from_point(gdf_sorted, pts_centroid)
        gdf_sorted = gdf_sorted.to_crs(gdf.crs)
        
    elif how == 'angle':
        def compute_angle(point, origin):
            dx = point.x - origin.x
            dy = point.y - origin.y
            angle = np.arctan2(dy, dx)
            return angle
        gdf_sorted["centroid"] = gdf_sorted.geometry.centroid
        origin = MultiPoint(gdf_sorted["centroid"].tolist()).centroid
        gdf_sorted["angle"] = gdf_sorted["centroid"].apply(lambda p: compute_angle(p, origin))
        gdf_sorted = gdf_sorted.sort_values("angle", ascending=False)
        gdf_sorted = gdf_sorted.drop(columns=["centroid", "angle"])
    
    gdf_sorted = gdf_sorted.to_crs(gdf.crs)
    polygons_union = gdf_sorted.geometry.union_all()
    if not isinstance(polygons_union, Polygon):
        return gdf_sorted, gpd.GeoDataFrame(geometry=[], crs=gdf_sorted.crs)
    outer_border = polygons_union.exterior
    outer_polygons = gdf_sorted[gdf_sorted.geometry.touches(outer_border)].copy()
    remaining = gdf_sorted.drop(index=outer_polygons.index)
    return outer_polygons, remaining



def sort_polygons_spatially(gdf: gpd.GeoDataFrame, how = 'angle', pts = None) -> gpd.GeoDataFrame:
    """
    Sorts polygons spatially from outermost to innermost, each layer clockwise.

    Args:
        gdf (gpd.GeoDataFrame): GeoDataFrame of polygons.
        how (str): Method to sort polygons. Options are 'angle' or 'distance'.
        pts (gpd.GeoDataFrame, optional): Points to consider for sorting, if how == 'distance'.

    Returns:
        gpd.GeoDataFrame: Sorted GeoDataFrame.
    """
    outer_polygons, remaining = sort_outer_polygons_spatially(gdf, how, pts)
    gdf_sorted = outer_polygons.copy()
    while len(remaining) > 0:
        prev_len = len(remaining)
        polygons_union = gdf_sorted.geometry.union_all()
        outer_border = polygons_union.boundary
        outer_polygons = remaining[remaining.geometry.touches(outer_border)].copy()
        gdf_sorted = pd.concat([gdf_sorted, outer_polygons], ignore_index=True)
        remaining = remaining.drop(index=outer_polygons.index)
        gdf_sorted = gdf_sorted.reset_index(drop=True)

        if len(remaining) == prev_len and len(remaining) > 0:
            warnings.warn(f"No more outer polygons found, stopping sorting.\nNumber of remaining polygons: {len(remaining)}")
            gdf_sorted = pd.concat([gdf_sorted, remaining], ignore_index=True)
            break
        elif len(remaining) == 0:
            print("All polygons sorted successfully.")
            break
    return gdf_sorted



def shared_border(poly1, poly2):
    """
    Check if two GeoDataFrames (each containing one polygon) share a border.

    Args:
        poly1: Polygon
        poly2: Polygon
    Returns:
        LineString or MultiLineString: The shared border if it exists, otherwise None.
    """
    
    border = poly1.boundary.intersection(poly2.boundary)
    if isinstance(border, MultiLineString):
        border = linemerge(border)
    if border.is_empty:
        return None
    return border



def extend_linestring(line, distance: float) -> LineString:
    if not isinstance(line, LineString) or len(line.coords) < 2:
        return line  # Return unchanged for non-LineStrings or degenerate lines

    # Use interpolation to get direction at start and end
    # Interpolate a small fraction along the line to get a second point
    frac = 1  # Small fraction for interpolation

    # Start direction
    start_pt = line.interpolate(0)
    next_pt = line.interpolate(frac)
    v_start = np.array(next_pt.coords[0]) - np.array(start_pt.coords[0])
    norm_start = np.linalg.norm(v_start)
    if norm_start == 0:
        return line  # Degenerate at start
    v_start /= norm_start
    new_start = np.array(start_pt.coords[0]) - distance * v_start

    # End direction
    end_pt = line.interpolate(line.length)
    prev_pt = line.interpolate(line.length - frac)
    v_end = np.array(end_pt.coords[0]) - np.array(prev_pt.coords[0])
    norm_end = np.linalg.norm(v_end)
    if norm_end == 0:
        return line  # Degenerate at end
    v_end /= norm_end
    new_end = np.array(end_pt.coords[0]) + distance * v_end

    # Build new coordinates
    coords = list(line.coords)
    new_coords = [tuple(new_start)] + coords[1:-1] + [tuple(new_end)]
    return LineString(new_coords)


