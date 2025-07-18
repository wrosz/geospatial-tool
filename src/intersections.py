import geopandas as gpd
import numpy as np
import config
from shapely.geometry import Point, LineString
from typing import Union


def azimuth(p1: Point, p2: Point) -> float:
    """
    Returns the azimuth (bearing) in degrees between two points, measured clockwise from the north.

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



def find_intersections_with_angle(
    borders: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Finds intersection points between cadastral borders and streets, 
    and computes the angle between them at each intersection.

    Reprojects both layers to a projected (metrical) CRS for geometric operations.

    Args:
        borders (GeoDataFrame): GeoDataFrame of border lines (LineStrings).
        streets (GeoDataFrame): GeoDataFrame of street lines (LineStrings).

    Returns:
        GeoDataFrame: Points of intersection with an added 'angle' column.
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

    # Reproject to a metrical CRS for all geometric calculations
    borders = borders.to_crs(config.metrical_crs)
    streets = streets.to_crs(config.metrical_crs)

    borders = borders[borders.is_valid]
    streets = streets[streets.is_valid]

    street_sindex = streets.sindex
    intersections = []

    for _, b_row in borders.iterrows():
        # Spatial index: find streets intersecting the bounding box of the border
        possible_matches_index = list(street_sindex.intersection(b_row.geometry.bounds))
        possible_matches = streets.iloc[possible_matches_index]

        for _, s_row in possible_matches.iterrows():
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
                        "angle": angle
                    })
                except Exception:
                    continue

    gdf = gpd.GeoDataFrame(intersections, geometry=[f["geometry"] for f in intersections], crs=config.metrical_crs)
    gdf["angle"] = [f["angle"] for f in intersections]

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
        (intersections.angle >= config.min_angle) &
        (intersections.angle <= 180 - config.min_angle)
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
    if points.crs != config.metrical_crs:
        points = points.to_crs(config.metrical_crs)

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
    threshold: float = 50
) -> gpd.GeoDataFrame:
    """
    Finds and filters valid intersection points between border and street geometries.

    Includes:
    - Reprojecting to `config.metrical_crs`
    - Computing angle at each intersection
    - Removing intersections with small or near-180° angles
    - Removing points that are too close to each other

    Args:
        borders (GeoDataFrame): Cadastral or administrative boundary lines.
        streets (GeoDataFrame): Street centerlines.
        threshold (float): Minimum distance allowed between valid intersection points (in meters).

    Returns:
        GeoDataFrame: Cleaned set of intersection points.
    """
    points = find_intersections_with_angle(borders, streets)
    points = remove_small_angles(points)
    points = remove_close_points(points, threshold)
    return points