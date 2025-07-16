import requests
import polyline
import geopandas as gpd
from shapely.geometry import LineString, Polygon, Point
from shapely.ops import split
from intersections import find_valid_intersections
import warnings
import numpy as np
import pandas as pd

import config


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
    

def find_all_cuts(points: gpd.GeoDataFrame):
    if len(points) < 2:
        raise Exception("GeoDataGrame 'points' must contain at least 2 entries")

    print("Calling find_all_cuts...")
    points = points.to_crs("EPSG:4326")
    cuts = []
    for i in range(len(points)):
        for j in range(i+1, len(points)):
            p1 = points.iloc[i]
            p2 = points.iloc[j]
            p1_lon = p1.geometry.x
            p1_lat = p1.geometry.y
            p2_lon = p2.geometry.x
            p2_lat = p2.geometry.y
            route = get_osrm_route(p1_lon, p1_lat, p2_lon, p2_lat)
            cuts.append({"geometry": route.geometry.iloc[0], "from": i, "to": j})
    cuts = gpd.GeoDataFrame(cuts, geometry="geometry", crs=config.univ_crs)
    print("Cuts found successfully.")
    return cuts


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


def calculate_weight(route, streets, weights=config.default_weights):
    buffered_route = route.geometry.buffer(config.buff)
    possible_matches = streets.iloc[streets.sindex.query(buffered_route, predicate="intersects")]
    streets_along_route = possible_matches[possible_matches.intersects(buffered_route)]
    streets_along_route["intersect_geom"] = streets_along_route.geometry.intersection(buffered_route)
    streets_along_route["intersect_length"] = streets_along_route["intersect_geom"].length
    total_weight = 0
    total_length = 0
    for i, row in streets_along_route.iterrows():
        if row.intersect_geom.length <= config.non_relevant_len:  # ignore non-relevant streets
            continue
        highway_type = row.highway
        segment_weight = weights[("highway", highway_type)]
        total_weight += segment_weight * row.intersect_geom.length
        total_length += row.intersect_geom.length
    return total_weight / total_length


def adresses_inside_polygon(polygon:Polygon, adresses):
    possible_matches = adresses.iloc[adresses.geometry.sindex.query(polygon, predicate="contains")]
    return possible_matches[possible_matches.within(polygon)]


def cut_is_valid(n_adresses_list, min_adresses):
        # tutaj sie trzeba bedzie zastanowic gdy sie dorobi czesc z klejeniem,
        # co gdy przez przypadek potniemy obszar na wiecej niż dwie części (z adresami lub bez)

    if len(n_adresses_list) < 2:
        return False
    
    positive_adresses = []
    for x in n_adresses_list:
        if x > 0:
            positive_adresses.append(x)
    
    if len(positive_adresses) < 2:
        return False
    elif len(positive_adresses) == 2:
        if positive_adresses[0] < min_adresses or positive_adresses[1] < min_adresses:
            return False
        else:
            return True
    else:
        warnings.warn(f"Cut results in more than 2 polygons with adresses inside: {n_adresses_list}")
        return False
    

def adresses_difference(valid_adresses_list):
    positive_adresses = []
    for x in valid_adresses_list:
        if x > 0:
            positive_adresses.append(x)
    if len(positive_adresses) != 2:
        raise Exception("Valid n_adresses list should contain exactly two positive entries")
    return abs(positive_adresses[0] - positive_adresses[1])

    

def cut(polygon_gdf, streets, adresses,
        min_adresses = config.default_min_adresses,
        weights=config.default_weights,
        top_weights_percentage=config.default_weights_percentage):
    
    borders = polygon_gdf["geometry"].boundary
    borders = gpd.GeoDataFrame(geometry=borders, crs=config.univ_crs)

    intersections = find_valid_intersections(borders, streets)
    if len(intersections) < 2:
        return [polygon_gdf]

    cuts = find_all_cuts(intersections)
    cuts["weight"] = [calculate_weight(row, streets, weights) for i, row in cuts.iterrows()]
    cuts["n_adresses"] = [None for i, row in cuts.iterrows()]
    polygon = polygon_gdf.geometry.iloc[0]
    for i, row in cuts.iterrows():
        line = row.geometry
        result = split(polygon, line)
        cuts.at[i, "n_adresses"] = [len(adresses_inside_polygon(poly, adresses)) for poly in list(result.geoms)]
    cuts = cuts[[cut_is_valid(lst, min_adresses) for lst in cuts["n_adresses"]]]
    if len(cuts) == 0:
        return [polygon_gdf]
    cuts = cuts[cuts["weight"] >= cuts["weight"].quantile(1-top_weights_percentage)]
    cuts["n_adresses_diff"] = [adresses_difference(row.n_adresses) for i, row in cuts.iterrows()]
    
    best_cut = cuts.loc[cuts["n_adresses_diff"].idxmin()]
    relevant_polys_idxs = np.array(best_cut.n_adresses) > 0
    best_line = best_cut.geometry
    best_result = split(polygon, best_line)
    best_result = pd.DataFrame(list(best_result.geoms))


    poly1 = (best_result[relevant_polys_idxs]).loc[0]
    poly2 = (best_result[relevant_polys_idxs]).loc[1]
    poly1 = gpd.GeoDataFrame(geometry = poly1, crs = config.univ_crs)
    poly2 = gpd.GeoDataFrame(geometry = poly2, crs = config.univ_crs)

    pieces = []
    
    pieces.extend(cut(poly1, streets, adresses_inside_polygon(poly1.geometry.iloc[0], adresses), min_adresses, weights, top_weights_percentage))
    pieces.extend(cut(poly2, streets, adresses_inside_polygon(poly2.geometry.iloc[0], adresses), min_adresses, weights, top_weights_percentage))

    return pieces
    
    

        
polygon_gdf = gpd.read_file("przyklad_routes/przykladowy_obszar.gpkg")
adresses = gpd.read_file("przyklad_routes/przykladowe_adresses.gpkg")
streets = gpd.read_file("przyklad_routes/sample_streets.gpkg")

result = cut(polygon_gdf, streets, adresses)
print(result)

print("koniec")
    
    



