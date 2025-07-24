import warnings
import geopandas as gpd
import pandas as pd

# # FOR DEBUGGING
# import sys
# import os
# # Add the project root (e.g., src/) to sys.path when debugging
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.utils import shared_border, addresses_inside_polygon, get_osrm_route
from src.logic_config import metrical_crs


def calculate_points_centroid(points):
    """
    Calculate the centroid of a GeoDataFrame of points in EPSG:4326 by
    reprojecting to a metric CRS, computing centroid, then converting back.

    Parameters:
        points (gpd.GeoDataFrame | gpd.GeoSeries): GeoDataFrame or GeoSeries containing points

    Returns:
        shapely.geometry.Point: centroid point in target_crs.
    """
    points_proj = points.to_crs(metrical_crs)
    multipoint = points_proj.unary_union  # unary_union of points → MultiPoint
    centroid_proj = multipoint.centroid
    centroid_gdf = gpd.GeoSeries([centroid_proj], crs=metrical_crs).to_crs("EPSG:4326")
    return centroid_gdf.iloc[0]



def merge_polygons_by_shortest_route(gdf, addresses, min_addresses, max_addresses, id_col: str = "id"):
    """
    Merges polygons in a GeoDataFrame based on the shortest route between them.
    
    Args:
        gdf (gpd.GeoDataFrame): GeoDataFrame containing polygons to merge.
        addresses (gpd.GeoDataFrame): GeoDataFrame containing address points.
        min_addresses (int): Minimum number of addresses required for merging.
        max_adresses (int): Maximum number of addresses allowed in a merged polygon.
        id_col (str): Column name in gdf_new that contains unique identifiers for polygons.
    
    Returns:
        gpd.GeoDataFrame: Merged GeoDataFrame with polygons that have enough addresses.
    """
    
    gdf_new = gdf.copy()
    gdf_new = gdf_new[[id_col, "geometry"]]
    gdf_new["merged_ids"] = gdf_new[id_col].apply(lambda x: [x])
    gdf_new = gdf_new.to_crs("EPSG:4326")  # Ensure CRS is set to WGS84 for OSRM compatibility
    addresses = addresses.to_crs("EPSG:4326")  # Ensure addresses are in the same CRS


    gdf_new.reset_index(drop=True, inplace=True)
    gdf_new = gdf_new.drop(columns=id_col)
    gdf_new["n_addresses"] = gdf_new.geometry.apply(lambda x: len(addresses_inside_polygon(x, addresses)))
    gdf_new["adresses_centroid"] = gdf_new.geometry.apply(lambda x: calculate_points_centroid(addresses_inside_polygon(x, addresses))
                                                          if not addresses_inside_polygon(x, addresses).empty
                                                          else calculate_points_centroid(gpd.GeoSeries([x], crs=gdf_new.crs)))


    if sum(gdf_new["n_addresses"]) < min_addresses:
        warnings.warn("Not enough addresses to merge polygons, returning original GeoDataFrame.")
        return gdf_new
    
    while any(gdf_new["n_addresses"] < min_addresses):
        row_to_merge = gdf_new[gdf_new["n_addresses"] < min_addresses].iloc[0]
        neighbors = gdf_new[gdf_new.geometry.apply(lambda x:shared_border(x, row_to_merge.geometry) is not None)].drop(row_to_merge.name)

        if neighbors.empty:
            warnings.warn("No neighboring polygons found to merge, returning original GeoDataFrame.")
            break

        # Find the neighbor with the shortest route to poly_to_merge (based on centroid)
        neighbors["route_duration"] = neighbors.adresses_centroid.apply(
            lambda pt: get_osrm_route(row_to_merge.adresses_centroid.x, row_to_merge.adresses_centroid.y, pt.x, pt.y).duration
        )

        best_neighbor = neighbors.loc[neighbors["route_duration"].idxmin()]
        row_merged_geom = gdf_new.loc[[row_to_merge.name, best_neighbor.name]].union_all()
        new_row = gpd.GeoDataFrame(
            {
                "geometry": [row_merged_geom],
                "merged_ids": [row_to_merge.merged_ids + best_neighbor.merged_ids],
                "n_addresses": [row_to_merge.n_addresses + best_neighbor.n_addresses],
                "adresses_centroid": [calculate_points_centroid(
                    addresses_inside_polygon(row_merged_geom, addresses)
                )]
            },
            crs=gdf_new.crs
        )
        gdf_new = gdf_new.drop([row_to_merge.name, best_neighbor.name])
        gdf_new = pd.concat([gdf_new, new_row], ignore_index=True)
    
    gdf_new.drop(columns=["adresses_centroid"], inplace=True)
    return gdf_new



        
        
















