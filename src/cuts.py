import requests
import polyline
import geopandas as gpd
from shapely.geometry import LineString, Polygon, MultiPoint
from shapely.ops import split
import warnings
import numpy as np
import pandas as pd
from intersections import find_valid_intersections

import config


def get_adresses(bbox):
    url = (
        "https://mapy.geoportal.gov.pl/wss/ext/KrajowaIntegracjaNumeracjiAdresowej?"
        "service=WFS&"
        "version=2.0.0&"
        "request=GetFeature&"
        "typeNames=ms:prg-adresy&"
        f"bbox={bbox}"
        "outputFormat=GML2"
    )
    gdf = gpd.read_file(url, driver="GML")
    gdf = gdf.to_crs(crs=config.univ_crs)
    return gdf


def get_osrm_route(lon1, lat1, lon2, lat2):
    # docker run -t -i -p 5000:5000 -v "${PWD}:/data" osrm/osrm-backend osrm-routed --algorithm mld /data/mazowieckie-latest.osrm

    # coords must be (lon, lat)
    url = f"http://localhost:5000/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=polyline"
    response = requests.get(url)
    data = response.json()

    if data["code"] == "Ok":
        # polyline gives (lat, lon), we need (lon, lat)
        coords_latlon = polyline.decode(data["routes"][0]["geometry"])
        coords_lonlat = [(lon, lat) for lat, lon in coords_latlon]
        coords_lonlat = gpd.GeoSeries(LineString(coords_lonlat), crs="EPSG:4326")
        coords_lonlat = coords_lonlat.to_crs(config.univ_crs)
        return coords_lonlat
    else:
        print("OSRM Error:", data)
        return None


def find_all_routes(points: gpd.GeoDataFrame):
    '''Returns a GeoDataFrame with geometries of routes connecting all pairs of points from a given set'''

    if len(points) < 2:
        raise Exception("GeoDataGrame 'points' must contain at least 2 entries")
    points = points.to_crs("EPSG:4326")
    routes = []
    for i in range(len(points)):
        for j in range(i+1, len(points)):
            p1 = points.iloc[i]
            p2 = points.iloc[j]
            p1_lon = p1.geometry.x
            p1_lat = p1.geometry.y
            p2_lon = p2.geometry.x
            p2_lat = p2.geometry.y
            route = get_osrm_route(p1_lon, p1_lat, p2_lon, p2_lat)
            routes.append({"geometry": route.geometry.iloc[0], "from": i, "to": j})
    routes = gpd.GeoDataFrame(routes, geometry="geometry", crs=config.univ_crs)
    return routes


def calculate_weight(line, geoms_set, geom_attr_weights: dict):
     
    # buffer the line (to width given by config.buff parameter) to find its intersection with geoms_set
    buffered_line = line.geometry.buffer(config.buff)
    if not isinstance(buffered_line, Polygon):
        buffered_line = buffered_line.union_all()

    # find intersections
    possible_matches = geoms_set.iloc[geoms_set.sindex.query(buffered_line, predicate="intersects")]
    geoms_along_line = possible_matches[possible_matches.intersects(buffered_line)]
    geoms_along_line["intersect_geom"] = geoms_along_line.geometry.intersection(buffered_line)
    geoms_along_line["intersect_length"] = geoms_along_line["intersect_geom"].length
    total_weight = 0
    total_length = 0

    # calculate weight
    # trzeba zaraz zmienić żeby działało też na inne atrybuty niż highway
    for i, row in geoms_along_line.iterrows():
        if row.intersect_geom.length <= config.non_relevant_len:  # ignore non-relevant streets
            continue
        highway_type = row.highway
        segment_weight = geom_attr_weights[("highway", highway_type)]
        total_weight += segment_weight * row.intersect_geom.length
        total_length += row.intersect_geom.length
    return total_weight / total_length


def adresses_inside_polygon(polygon:Polygon, adresses: gpd.GeoDataFrame):
    possible_matches = adresses.iloc[adresses.geometry.sindex.query(polygon, predicate="contains")]
    return possible_matches[possible_matches.within(polygon)]


# NA PÓŹNIEJ: DOKLEJENIE SKRAWKÓW, POLUZOWANIE KRYTERIÓW CUT_IS_VALID()?
# + zoptymalizowanie względem pieces_to_final_data (n_adresses, border_weight liczymy dwa razy)
def cut_polygon_gdf(polygon_gdf, streets, adresses,
        min_adresses=config.default_min_adresses,
        weights=config.default_weights,
        top_weights_percentage=config.default_weights_percentage):
    
    # find possible cuts (routes between streets intersecting polygon's boundary)
    borders = polygon_gdf["geometry"].boundary
    borders = gpd.GeoDataFrame(geometry=borders, crs=config.univ_crs)
    intersections = find_valid_intersections(borders, streets)  # streets można jeszcze lekko przedłużyć, żeby złapać wszystkie intersections
    if len(intersections) < 2:  # if less than two intersections, cutting not possible
        return [polygon_gdf]
    cuts = find_all_routes(intersections)

    # calculate weight of each cut
    cuts["weight"] = [calculate_weight(row, streets, weights) for i, row in cuts.iterrows()]

    # compute list of adresses inside of each polygon's component (cut by given route)
    cuts["n_adresses"] = [None for i, row in cuts.iterrows()]
    polygon = polygon_gdf.geometry.iloc[0]
    for i, row in cuts.iterrows():
        line = row.geometry
        result = split(polygon, line)
        cuts.at[i, "n_adresses"] = [len(adresses_inside_polygon(poly, adresses)) for poly in list(result.geoms)]

    # filter out bad cuts
    def cut_is_valid(n_adresses_list):
        if len(n_adresses_list) < 2:  # cut must split polygon into > 1 component
            return False
        # at least two components must contain adresses inside
        positive_adresses = []
        for x in n_adresses_list:
            if x > 0:
                positive_adresses.append(x)
        if len(positive_adresses) < 2:
            return False
        # a cut should split the polygon into exactly two main parts (with enough adresses inside)
        # and possibly some non-relevant scraps with 0 adresses inside
        elif len(positive_adresses) == 2:
            if positive_adresses[0] < min_adresses or positive_adresses[1] < min_adresses:
                return False
            else:
                return True
        else:
            warnings.warn(f"Cut results in more than 2 polygons with adresses inside: {n_adresses_list}")
            return False
    cuts = cuts[[cut_is_valid(lst) for lst in cuts["n_adresses"]]]
    if len(cuts) == 0:
        return [polygon_gdf]
    
    # select the heaviest cuts
    cuts = cuts[cuts["weight"] >= cuts["weight"].quantile(1-top_weights_percentage)]

    # select the most balanced cut (main parts contain the most equal number of adresses)
    def adresses_difference(valid_adresses_list):
        positive_adresses = []
        for x in valid_adresses_list:
            if x > 0:
                positive_adresses.append(x)
        if len(positive_adresses) != 2:
            raise Exception("Valid n_adresses list should contain exactly two positive entries")
        return abs(positive_adresses[0] - positive_adresses[1])
    cuts["n_adresses_diff"] = [adresses_difference(row.n_adresses) for i, row in cuts.iterrows()]
    best_cut = cuts.loc[cuts["n_adresses_diff"].idxmin()]

    # identify main component geometries
    relevant_polys_idxs = np.array(best_cut.n_adresses) > 0
    best_line = best_cut.geometry
    best_result = split(polygon, best_line)
    best_result = pd.DataFrame(list(best_result.geoms))
    poly1 = (best_result[relevant_polys_idxs]).loc[0]
    poly2 = (best_result[relevant_polys_idxs]).loc[1]
    poly1 = gpd.GeoDataFrame(geometry = poly1, crs = config.univ_crs)
    poly2 = gpd.GeoDataFrame(geometry = poly2, crs = config.univ_crs)

    # cut the polygon recursively as long as possible
    pieces = []
    pieces.extend(cut_polygon_gdf(poly1, streets, adresses_inside_polygon(poly1.geometry.iloc[0], adresses),
                      min_adresses, weights, top_weights_percentage))
    pieces.extend(cut_polygon_gdf(poly2, streets, adresses_inside_polygon(poly2.geometry.iloc[0], adresses),
                      min_adresses, weights, top_weights_percentage))
    return pieces


# Helper sorter for pieces_to_final_data()
def sort_polygons_spatially(gdf):
    '''Returns a sorted geodataframe of polygons (from outermost to innermost, each layer clockwise)'''

    # compute an angle and sort clockwise (by point of origin)
    def compute_angle(point, origin):
        dx = point.x - origin.x
        dy = point.y - origin.y
        angle = np.arctan2(dy, dx)  # radians, from -pi to pi
        return angle
    gdf_sorted = gdf.copy()
    gdf_sorted["centroid"] = gdf_sorted.geometry.centroid
    origin = MultiPoint(gdf_sorted["centroid"].tolist()).centroid  # original polygon centroid
    gdf_sorted["angle"] = gdf_sorted["centroid"].apply(lambda p: compute_angle(p, origin))
    gdf_sorted = gdf_sorted.sort_values("angle", ascending=False)
    gdf_sorted = gdf_sorted.drop(columns=["centroid", "angle"])  # drop helper columns

    # sort from outermost to innermost (identify layers)
    polygons_union = gdf_sorted.geometry.union_all()
    if not isinstance(polygons_union, Polygon):
        return gdf_sorted
    outer_border = polygons_union.exterior
    outer_polygons = gdf_sorted[gdf_sorted.geometry.touches(outer_border)].copy()
    remaining = gdf_sorted.drop(index = outer_polygons.index)
    gdf_sorted = outer_polygons
    while len(remaining) > 0:
        polygons_union = gdf_sorted.geometry.union_all()
        outer_border = polygons_union.boundary
        outer_polygons = remaining[remaining.geometry.touches(outer_border)].copy()
        gdf_sorted = gdf_sorted.concat(outer_polygons)
        remaining = gdf_sorted.drop(index = outer_polygons.index)

    return gdf_sorted


def pieces_to_final_data(pieces, streets, adresses, weights=config.default_weights):

    # make a GeoDataFrame out of polygon's pieces (list of pylogon's dataframes returned by cut_polygon_gdf())
    gdf = pd.concat(pieces, ignore_index=True)
    gdf = gpd.GeoDataFrame(gdf, geometry='geometry', crs=config.univ_crs)

    # id for each component given by the spatial ordering
    gdf = sort_polygons_spatially(gdf)  # sort clockwise, from outermost to innermost
    gdf = gdf.reset_index(drop=True)
    gdf["id"] = gdf.index

    # find neighbors for each piece
    neighbors = gpd.sjoin(gdf, gdf, how="left", predicate="touches")
    neighbors = neighbors.drop(["index_right"], axis=1)
    # column "neighbors" contains a list of neighbors for each polygon
    gdf["neighbors"] = neighbors.groupby(neighbors.index)["id_right"].apply(list)
    gdf["neighbors"] = gdf["neighbors"].apply(lambda x: sorted(x) if isinstance(x, list) else [])

    # calculate weight of a border between neighbots
    def calculate_border_weight(id1, id2):
        poly1 = gdf.geometry.loc[id1]
        poly2 = gdf.geometry.loc[id2]
        border = poly1.intersection(poly2)
        border = gpd.GeoDataFrame(geometry=list(border.geoms), crs=config.univ_crs)
        return calculate_weight(border, streets, weights)
    # column "weights" contains a dictionary of form {neighbor_id: border_weight_value}
    gdf["weights"] = gdf.apply(lambda row: {i: calculate_border_weight(row.name, i) for i in row["neighbors"]}, axis=1)

    # number of adresses inside each component
    gdf["n_adresses"] = gdf["geometry"].apply(lambda geom: len(adresses_inside_polygon(geom, adresses)))
    return gdf


# przyklad działania:
adresses = gpd.read_file("sample_input_data/sample_adresses.gpkg")
area = gpd.read_file("sample_input_data/sample_area.gpkg")
streets = gpd.read_file("sample_input_data/sample_streets.gpkg")

pieces = cut_polygon_gdf(polygon_gdf=area, streets=streets, adresses=adresses)
final_data = pieces_to_final_data(pieces, streets, adresses)
print(final_data)


# # pobranie terytów
# # działa
# url = (
#     "https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries?"
#     "Service=WFS&"
#     "version=2.0.0&"
#     "Request=GetFeature&"
#     "typeNames=ms:A06_Granice_obrebow_ewidencyjnych&"
#     "count=10&"
#     "outputFormat=GML2"
# )
# gdf = gpd.read_file(url, driver = "GML")
# print(gdf)

# # nie działa
# teryt_id='146502_8.0615'
# url2 = (
#     "https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries?"
#     "Service=WFS&"
#     "version=2.0.0&"
#     "Request=GetFeature&"
#     "typeNames=ms:A06_Granice_obrebow_ewidencyjnych&"
#     "cql_filter=JPT_KOD_JE='{teryt_id}'&"
#     "outputFormat=GML2"
# )
# gdf2 = gpd.read_file(url2)
# print(gdf2)
