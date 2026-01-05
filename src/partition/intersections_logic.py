import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point, LineString
from src.logic_config import metrical_crs, min_angle, streets_extension_distance, close_points_treshold, max_number_of_intersections
from src.utils import extend_linestring


def azimuth(p1: Point, p2: Point) -> float:
    """
    Returns the azimuth (bearing) in degrees between two points (expected to be in metrical units), measured clockwise from the north.

    Args:
        p1 (Point): Starting point.
        p2 (Point): Target point.

    Returns:
        float: Azimuth in degrees (0–360).
    """
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    angle = np.degrees(np.arctan2(dy, dx)) % 360
    return angle


def extend_lines_in_gdf(gdf: gpd.GeoDataFrame, distance: float) -> gpd.GeoDataFrame:
    """
    Extend both ends of all LineString geometries in a GeoDataFrame by a given distance.

    Parameters:
        gdf (GeoDataFrame): Input GeoDataFrame with LineStrings.
        distance (float): Distance in the same units as the CRS (meters for projected CRS).

    Returns:
        GeoDataFrame: A new GeoDataFrame with extended LineStrings.
    """

    # Ensure CRS is projected (not lat/lon)
    if gdf.crs is None or gdf.crs.is_geographic:
        raise ValueError("GeoDataFrame must have a projected CRS (e.g., EPSG:3857).")

    gdf_extended = gdf.copy()
    gdf_extended["geometry"] = gdf_extended["geometry"].apply(lambda geom: extend_linestring(geom, distance))

    return gdf_extended


def find_intersections_with_angle_and_weight(
    borders: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    weights: pd.DataFrame,
) -> gpd.GeoDataFrame:
    """
    Finds intersection points between area borders and streets, 
    and computes the angle between them at each intersection.
    Reprojects both layers to a projected (metrical) CRS for geometric operations.
    Args:
        borders (GeoDataFrame): GeoDataFrame of border lines (LineStrings).
        streets (GeoDataFrame): GeoDataFrame of street lines (LineStrings).
        weights (DataFrame): DataFrame with columns ["osm_key", "osm_value", "weight"] for street weighting.
    Returns:
        GeoDataFrame: Points of intersection with an added 'angle' column and 'weight' column.
    """
    def check_angle(pt: Point, b: LineString, s: LineString) -> float:
        """
        Returns the angle in degrees between two lines (g and u) at their intersection point (pt).
        This is used to filter out near-parallel intersections (small angles), which are often false.
        Args:
            pt (Point): Intersection point.
            b (LineString): First geometry (usually a border).
            s (LineString): Second geometry (usually a street).
        Returns:
            float: Angle in degrees between the lines at the intersection point.
        """
        b_proj = b.project(pt)
        s_proj = s.project(pt)
        b_near = b.interpolate(b_proj + 1)
        s_near = s.interpolate(s_proj + 1)
        az_b = azimuth(pt, b_near)
        az_s = azimuth(pt, s_near)
        diff = abs(az_b - az_s)
        return 360 - diff if diff > 180 else diff
    
    def calculate_street_weight(street: gpd.GeoSeries, weights: pd.DataFrame) -> float:
        """Calculates the weight of a street based on its attributes and a weights DataFrame.
        
        Args:
            street (GeoSeries): A GeoSeries representing a street with its attributes.
            weights (pd.DataFrame): DataFrame with columns ["osm_key", "osm_value", "weight"].
        
        Returns:
            float: The calculated weight of the street (sum of all matching weights).
        """
        total_weight = 0.0
        
        # Iterate through each weight rule
        for _, weight_row in weights.iterrows():
            osm_key = weight_row['osm_key']
            osm_value = weight_row['osm_value']
            weight = weight_row['weight']
            
            # Check if the street has this attribute
            if osm_key in street.index:
                street_value = street[osm_key]
                
                # Handle None/NaN values
                if pd.notna(street_value) and street_value == osm_value:
                    total_weight += weight
        
        return total_weight

    
    # Reproject to a metrical CRS for all geometric calculations
    borders = borders.to_crs(metrical_crs)
    streets = streets.to_crs(metrical_crs)
    borders = borders[borders.is_valid] 
    streets = streets[streets.is_valid]
    
    # Build spatial index on original streets (no extension yet)
    street_sindex = streets.sindex
    intersections = []
    
    for _, b_row in borders.iterrows():
        # Buffer the border to find nearby streets
        search_buffer = b_row.geometry.buffer(streets_extension_distance)
        
        # Use spatial index to find candidate streets
        possible_matches_index = list(street_sindex.intersection(search_buffer.bounds))
        possible_matches = streets.iloc[possible_matches_index]
        
        # Only extend the candidate streets (much smaller subset)
        extended_candidates = extend_lines_in_gdf(possible_matches, streets_extension_distance)
        
        for idx, s_row in extended_candidates.iterrows():
            # Check intersection with extended street
            if b_row.geometry.intersects(s_row.geometry):
                pt = b_row.geometry.intersection(s_row.geometry)
                b = b_row.geometry
                s = s_row.geometry
                
                # Only handle simple Point intersections
                if pt.geom_type != 'Point':
                    continue
                
                try:
                    angle = check_angle(pt, b, s)
                    intersections.append({
                        "geometry": pt,
                        "angle": angle,
                        "weight": calculate_street_weight(s_row, weights)
                    })
                except Exception:
                    continue
    
    if not intersections:
        return gpd.GeoDataFrame(columns=['geometry', 'angle'], crs=metrical_crs)
    
    gdf = gpd.GeoDataFrame(intersections, crs=metrical_crs)
    return gdf



def remove_small_angles(intersections: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Filters out intersection points where the angle is too small or too close to 180°,
    based on the configured `config.min_angle`.

    Args:
        intersections (GeoDataFrame): GeoDataFrame with an 'angle' column.

    Returns:
        GeoDataFrame: Filtered intersections.
    """
    return intersections[
        (intersections.angle >= min_angle) &
        (intersections.angle <= 180 - min_angle)
    ]


def remove_close_points(points: gpd.GeoDataFrame, threshold: float) -> gpd.GeoDataFrame:
    """
    Removes points that are closer to each other than a given threshold, using spatial indexing.

    Automatically reprojects to `config.metrical_crs` if necessary for distance calculations.

    Args:
        points (GeoDataFrame): Input points to filter.
        threshold (float): Minimum distance allowed between any two points (in meters).

    Returns:
        GeoDataFrame: Filtered set of points.
    """
    if points.crs != metrical_crs:
        points = points.to_crs(metrical_crs)

    geometries = points.geometry
    sindex = geometries.sindex

    kept = []
    rejected = set()

    for i, geom in enumerate(geometries):
        if i in rejected:
            continue

        kept.append(i)

        # Find candidates within the buffer zone
        candidate_idxs = sindex.query(geom.buffer(threshold))
        for j in candidate_idxs:
            if j == i or j in rejected:
                continue
            if geom.distance(geometries.iloc[j]) < threshold:
                rejected.add(j)

    return points.iloc[kept].copy()



def find_valid_intersections(
    borders: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    weights: pd.DataFrame,
) -> gpd.GeoDataFrame:
    """
    Finds and filters valid intersection points between border and street geometries.

    Includes:
    - Reprojecting to `config.metrical_crs`
    - Computing angle at each intersection
    - Removing intersections with small or near-180° angles
    - Removing points that are too close to each other
    - Returning top weight intersections if needed, specified in logic_config.py

    Args:
        borders (GeoDataFrame): Cadastral or administrative boundary lines.
        streets (GeoDataFrame): Street centerlines.
        weights (DataFrame): Weights for street attributes.

    Returns:
        GeoDataFrame: Cleaned set of intersection points.
    """
    points = find_intersections_with_angle_and_weight(borders, streets, weights)
    points = remove_small_angles(points)
    points = remove_close_points(points, threshold = close_points_treshold)
    if len(points) > max_number_of_intersections:
        print(f' Too many intersections found ({len(points)}), selecting top {max_number_of_intersections} by weight')
        points = points.sort_values(by='weight', ascending=False)
        points = points.head(max_number_of_intersections)
    return points

