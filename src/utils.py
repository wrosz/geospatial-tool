import geopandas as gpd
import requests
import polyline
import warnings
import pandas as pd
from shapely.geometry import Polygon, LineString

import src.logic_config as logic_config


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
    buffer: float = logic_config.buff,
    non_relevant_len: float = logic_config.non_relevant_len,
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
    line_metric = line.to_crs(logic_config.metrical_crs)
    geoms_set_metric = geoms_set.to_crs(logic_config.metrical_crs)

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
        warnings.warn("Total intersect length is zero, returning 0.0 for weight.")  
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
