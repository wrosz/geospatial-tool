import warnings
import geopandas as gpd
import pandas as pd
import sys

from src.utils import shared_border, addresses_inside_polygon, get_osrm_route, sort_polygons_spatially, sort_outer_polygons_spatially
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
    multipoint = points_proj.union_all()  # unary_union of points → MultiPoint
    centroid_proj = multipoint.centroid
    centroid_gdf = gpd.GeoSeries(centroid_proj, crs=metrical_crs)
    centroid_gdf = centroid_gdf.to_crs("EPSG:4326")  # Convert back to EPSG:4326
    return centroid_gdf.geometry.iloc[0]



def merge_polygons_by_shortest_route(gdf, addresses, min_addresses, max_addresses, id_col: str = "id", n_days: int = 1):
    """
    Merges polygons in a GeoDataFrame based on the shortest route between them.
    
    Args:
        gdf (gpd.GeoDataFrame): GeoDataFrame containing polygons to merge.
        addresses (gpd.GeoDataFrame): GeoDataFrame containing address points.
        min_addresses (int): Minimum number of addresses required for merging.
        max_addresses (int): Maximum number of addresses allowed in a merged polygon.
        id_col (str): Column name in gdf_new that contains unique identifiers for polygons.
        n_days (int): Number of days to consider for merging.

    Returns:
        gpd.GeoDataFrame: Merged GeoDataFrame with polygons that have enough addresses.
    """

    min_addresses = min_addresses * n_days
    max_addresses = max_addresses * n_days

    if min_addresses <= 0:
        raise ValueError("min_addresses must be greater than 0")

    if max_addresses <= 0:
        raise ValueError("max_addresses must be greater than 0")
    if min_addresses > max_addresses:
        raise ValueError("min_addresses cannot be greater than max_addresses")
    

    gdf_new = gdf[[id_col, "geometry"]].copy()
    gdf_new["merged_ids"] = gdf_new[id_col].apply(lambda x: [x])
    gdf_new = gdf_new.to_crs("EPSG:4326")  # Ensure CRS is set to WGS84 for OSRM compatibility
    addresses = addresses.to_crs("EPSG:4326")  # Ensure addresses are in the same CRS


    def addresses_centroid(poly):
        """
        Calculate the centroid of addresses inside a polygon.
        
        Args:
            poly (shapely.geometry.Polygon): Polygon to check.
            addresses (gpd.GeoDataFrame): GeoDataFrame containing address points.
        
        Returns:
            shapely.geometry.Point: Centroid of addresses inside the polygon.
        """
        addresses_in_poly = addresses_inside_polygon(poly, addresses)
        if not addresses_in_poly.empty:
            return calculate_points_centroid(addresses_in_poly)
        else:
            return calculate_points_centroid(gpd.GeoDataFrame(geometry=[poly], crs=gdf_new.crs))


    gdf_new.reset_index(drop=True, inplace=True)
    gdf_new = gdf_new.drop(columns=id_col).copy()
    gdf_new["n_addresses"] = gdf_new.geometry.apply(lambda x: len(addresses_inside_polygon(x, addresses)))
    gdf_new["addresses_centroid"] = gdf_new.geometry.apply(addresses_centroid)
    gdf_new["can_be_merged"] = gdf_new["n_addresses"] < max_addresses
    gdf_new["must_be_merged"] = gdf_new["n_addresses"] < min_addresses

    if sum(gdf_new["n_addresses"]) < min_addresses:
        warnings.warn("Total number of addresses is less than min_addresses, returning sum of all geometries.")
        return gdf_new.dissolve(by="can_be_merged", as_index=False, aggfunc="first").reset_index(drop=True)
    if any(gdf_new["n_addresses"] > max_addresses):
        print(f"Warning: Polygons with ids {sum(gdf_new[gdf_new['n_addresses'] > max_addresses].merged_ids.tolist(), [])} already have more than maximum of {max_addresses} addresses on average.")

    gdf_new = sort_polygons_spatially(gdf_new)
    gdf_new.reset_index(drop=True, inplace=True)

    prev_num_len = len(str(gdf_new.must_be_merged.sum()))
    prefix = "Number of polygons not following minimum address requirement: "

    while True:
        # refresh the current count of polygons that must be merged on console
        count_str = str(gdf_new.must_be_merged.sum())
        padding = max(prev_num_len - len(count_str), 0)
        sys.stdout.write('\r' + prefix + count_str + (' ' * padding))
        sys.stdout.flush()
        prev_num_len = len(count_str)

        if gdf_new.can_be_merged.sum() == 0 or gdf_new.must_be_merged.sum() == 0:
            # If no polygons can be merged or must be merged, exit the loop
            break

        row_to_merge = gdf_new[gdf_new.must_be_merged].iloc[0]
        neighbors = gdf_new[gdf_new.geometry.apply(lambda x:shared_border(x, row_to_merge.geometry) is not None)].drop(row_to_merge.name).copy()
        neighbors_to_merge = neighbors[neighbors["n_addresses"] + row_to_merge.n_addresses <= max_addresses].copy()

        # avoid multipolygon merging
        neighbors_to_merge = neighbors_to_merge[neighbors_to_merge.geometry.apply(lambda x: x.union(row_to_merge.geometry).geom_type == 'Polygon')].copy()
        if neighbors_to_merge.empty:
            gdf_new.loc[row_to_merge.name, "can_be_merged"] = False
            continue

        # Find the neighbor with the shortest route to polygon_to_merge (based on centroid)
        neighbors_to_merge["route_duration"] = neighbors_to_merge.addresses_centroid.apply(
            lambda pt: get_osrm_route(row_to_merge.addresses_centroid.x, row_to_merge.addresses_centroid.y, pt.x, pt.y).duration
        )

        best_neighbor = neighbors_to_merge.loc[neighbors_to_merge["route_duration"].idxmin()]
        row_merged_geom = gdf_new.loc[[row_to_merge.name, best_neighbor.name]].union_all()
        new_row = gpd.GeoDataFrame(
            {
                "geometry": [row_merged_geom],
                "merged_ids": [row_to_merge.merged_ids + best_neighbor.merged_ids],
                "n_addresses": [row_to_merge.n_addresses + best_neighbor.n_addresses],
                "addresses_centroid": [addresses_centroid(row_merged_geom)],
                "can_be_merged": [row_to_merge.n_addresses + best_neighbor.n_addresses < max_addresses],
                "must_be_merged": [row_to_merge.n_addresses + best_neighbor.n_addresses < min_addresses]
            },
            crs=gdf_new.crs
        )
        gdf_new = gdf_new.drop([row_to_merge.name, best_neighbor.name]).copy()
        gdf_new = pd.concat([new_row, gdf_new], ignore_index=True)

    remaining_to_merge = gdf_new[gdf_new.must_be_merged].copy()
    if not remaining_to_merge.empty:
        warnings.warn(f"Some polygons have less than {min_addresses/n_days} addresses on average, merging them without maximum address limit")
        for index, row in remaining_to_merge.iterrows():
            neighbors = gdf_new[gdf_new.geometry.apply(lambda x: shared_border(x, row.geometry) is not None)].copy()
            if row.name in neighbors.index:
                neighbors = neighbors.drop(index=row.name)
            if neighbors.empty:
                continue
            
            best_neighbor = neighbors.loc[neighbors.addresses_centroid.apply(
                lambda pt: get_osrm_route(row.addresses_centroid.x, row.addresses_centroid.y, pt.x, pt.y).duration).idxmin()].copy()
            row_merged_geom = gdf_new.loc[[row.name, best_neighbor.name]].union_all()
            new_row = gpd.GeoDataFrame(
                {
                    "geometry": [row_merged_geom],
                    "merged_ids": [row.merged_ids + best_neighbor.merged_ids],
                    "n_addresses": [row.n_addresses + best_neighbor.n_addresses],
                    "addresses_centroid": [addresses_centroid(row_merged_geom)],
                    "can_be_merged": [False]  # Set to False since we are merging without address limit
                },
                crs=gdf_new.crs
            )
            gdf_new = gdf_new.drop([row.name, best_neighbor.name])
            gdf_new = pd.concat([new_row, gdf_new])
    gdf_new.drop(columns=["addresses_centroid", "can_be_merged", "must_be_merged"], inplace=True)
    gdf_new["avg_addresses"] = gdf_new["n_addresses"] / n_days
    gdf_new.drop(columns=["n_addresses"], inplace=True)
    return gdf_new







































def merge_polygons_by_shortest_route2(gdf, addresses, min_addresses, max_addresses, id_col: str = "id", n_days: int = 1):
    """
    Merges polygons in a GeoDataFrame based on the shortest route between them.
    
    Args:
        gdf (gpd.GeoDataFrame): GeoDataFrame containing polygons to merge.
        addresses (gpd.GeoDataFrame): GeoDataFrame containing address points.
        min_addresses (int): Minimum number of addresses required for merging.
        max_addresses (int): Maximum number of addresses allowed in a merged polygon.
        id_col (str): Column name in gdf_new that contains unique identifiers for polygons.
        n_days (int): Number of days to consider for merging.

    Returns:
        gpd.GeoDataFrame: Merged GeoDataFrame with polygons that have enough addresses.
    """

    min_addresses = min_addresses * n_days
    max_addresses = max_addresses * n_days

    if min_addresses <= 0:
        raise ValueError("min_addresses must be greater than 0")

    if max_addresses <= 0:
        raise ValueError("max_addresses must be greater than 0")
    if min_addresses > max_addresses:
        raise ValueError("min_addresses cannot be greater than max_addresses")
    

    gdf_new = gdf[[id_col, "geometry"]].copy()
    gdf_new["merged_ids"] = gdf_new[id_col].apply(lambda x: [x])
    gdf_new = gdf_new.to_crs("EPSG:4326")  # Ensure CRS is set to WGS84 for OSRM compatibility
    addresses = addresses.to_crs("EPSG:4326")  # Ensure addresses are in the same CRS


    def addresses_centroid(poly):
        """
        Calculate the centroid of addresses inside a polygon.
        
        Args:
            poly (shapely.geometry.Polygon): Polygon to check.
            addresses (gpd.GeoDataFrame): GeoDataFrame containing address points.
        
        Returns:
            shapely.geometry.Point: Centroid of addresses inside the polygon.
        """
        addresses_in_poly = addresses_inside_polygon(poly, addresses)
        if not addresses_in_poly.empty:
            return calculate_points_centroid(addresses_in_poly)
        else:
            return calculate_points_centroid(gpd.GeoDataFrame(geometry=[poly], crs=gdf_new.crs))


    gdf_new.reset_index(drop=True, inplace=True)
    gdf_new = gdf_new.drop(columns=id_col).copy()
    gdf_new["n_addresses"] = gdf_new.geometry.apply(lambda x: len(addresses_inside_polygon(x, addresses)))
    gdf_new["addresses_centroid"] = gdf_new.geometry.apply(addresses_centroid)
    gdf_new["can_be_merged"] = gdf_new["n_addresses"] < max_addresses
    gdf_new["must_be_merged"] = gdf_new["n_addresses"] < min_addresses

    if sum(gdf_new["n_addresses"]) < min_addresses:
        warnings.warn("Total number of addresses is less than min_addresses, returning sum of all geometries.")
        return gdf_new.dissolve(by="can_be_merged", as_index=False, aggfunc="first").reset_index(drop=True)

    gdf_new = sort_polygons_spatially(gdf_new)
    gdf_new.reset_index(drop=True, inplace=True)
    while True:

        if gdf_new.can_be_merged.sum() == 0:
            break

        row_to_merge = gdf_new[gdf_new.can_be_merged].iloc[0]
        neighbors = gdf_new[gdf_new.geometry.apply(lambda x:shared_border(x, row_to_merge.geometry) is not None)].drop(row_to_merge.name).copy()
        neighbors_to_merge = neighbors[neighbors["n_addresses"] + row_to_merge.n_addresses <= max_addresses].copy()

        if neighbors_to_merge.empty:
            gdf_new.loc[row_to_merge.name, "can_be_merged"] = False
            continue

        # Find the neighbor with the shortest route to polygon_to_merge (based on centroid)
        neighbors_to_merge["route_duration"] = neighbors_to_merge.addresses_centroid.apply(
            lambda pt: get_osrm_route(row_to_merge.addresses_centroid.x, row_to_merge.addresses_centroid.y, pt.x, pt.y).duration
        )

        best_neighbor = neighbors_to_merge.loc[neighbors_to_merge["route_duration"].idxmin()]
        row_merged_geom = gdf_new.loc[[row_to_merge.name, best_neighbor.name]].union_all()
        new_row = gpd.GeoDataFrame(
            {
                "geometry": [row_merged_geom],
                "merged_ids": [row_to_merge.merged_ids + best_neighbor.merged_ids],
                "n_addresses": [row_to_merge.n_addresses + best_neighbor.n_addresses],
                "addresses_centroid": [addresses_centroid(row_merged_geom)],
                "can_be_merged": [row_to_merge.n_addresses + best_neighbor.n_addresses < max_addresses]
            },
            crs=gdf_new.crs
        )
        gdf_new = gdf_new.drop([row_to_merge.name, best_neighbor.name]).copy()
        gdf_new = pd.concat([new_row, gdf_new], ignore_index=True)

    remaining_to_merge = gdf_new[gdf_new.n_addresses < min_addresses].copy()
    warnings.warn(f"Some polygons have less than {min_addresses} addresses, merging them without maximum address limit")
    for index, row in remaining_to_merge.iterrows():
        neighbors = gdf_new[gdf_new.geometry.apply(lambda x: shared_border(x, row.geometry) is not None)].copy()
        if row.name in neighbors.index:
            neighbors = neighbors.drop(index=row.name)
        if neighbors.empty:
            continue
        
        best_neighbor = neighbors.loc[neighbors["n_addresses"].idxmin()].copy()
        row_merged_geom = gdf_new.loc[[row.name, best_neighbor.name]].union_all()
        new_row = gpd.GeoDataFrame(
            {
                "geometry": [row_merged_geom],
                "merged_ids": [row.merged_ids + best_neighbor.merged_ids],
                "n_addresses": [row.n_addresses + best_neighbor.n_addresses],
                "addresses_centroid": [addresses_centroid(row_merged_geom)],
                "can_be_merged": [False]  # Set to False since we are merging without address limit
            },
            crs=gdf_new.crs
        )
        gdf_new = gdf_new.drop([row.name, best_neighbor.name])
        gdf_new = pd.concat([new_row, gdf_new])
    gdf_new.drop(columns=["addresses_centroid", "can_be_merged"], inplace=True)
    gdf_new["avg_addresses"] = gdf_new["n_addresses"] / n_days
    gdf_new.drop(columns=["n_addresses"], inplace=True)
    return gdf_new
















