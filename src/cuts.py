import requests
import polyline
import geopandas as gpd
from shapely.geometry import LineString
from shapely.ops import split
from intersections import find_valid_intersections


def get_osrm_route(coord1, coord2):
    # docker run -t -i -p 5000:5000 -v "${PWD}:/data" osrm/osrm-backend osrm-routed --algorithm mld /data/mazowieckie-latest.osrm

    # coords must be (lon, lat)
    url = f"http://localhost:5000/route/v1/driving/{coord1[0]},{coord1[1]};{coord2[0]},{coord2[1]}?overview=full&geometries=polyline"
    response = requests.get(url)
    data = response.json()

    if data["code"] == "Ok":
        # polyline gives (lat, lon), we need (lon, lat)
        coords_latlon = polyline.decode(data["routes"][0]["geometry"])
        coords_lonlat = [(lon, lat) for lat, lon in coords_latlon]
        return LineString(coords_lonlat)
    else:
        print("OSRM Error:", data)
        return None
    

def find_all_cuts(points):
    init_crs=points.crs
    points = points.to_crs(epsg=4326)
    cuts = []
    for i in range(len(points)):
        for j in range(i+1, len(points)):
            coord1 = (points.geometry.iloc[i].x, points.geometry.iloc[i].y)
            coord2 = (points.geometry.iloc[j].x, points.geometry.iloc[j].y)
            line = get_osrm_route(coord1, coord2)
            if line:
                cuts.append({"geometry": line, "from": i, "to": j})
    cuts = gpd.GeoDataFrame(cuts, geometry="geometry", crs="EPSG:4326")
    cuts = cuts.to_crs(init_crs)
    return cuts


def get_adresses(bbox: str):
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
    print(gdf.head())


default_weights = {
    ("highway","primary"): 6,
    ("highway","secondary"): 5,
    ("highway","tertiary"): 4,
    ("highway","unclassified"): 3,
    ("highway","residential"): 2,
    ("highway","living"): 1
}


def calculate_weight(route, weights, streets):
    streets = streets.to_crs(epsg=2180)
    buffered_route = route.geometry.buffer(6)  # route musi tez byc w 2180
    possible_matches = streets.iloc[streets.sindex.query(buffered_route, predicate="intersects")]
    streets_along_route = possible_matches[possible_matches.intersects(buffered_route)]
    streets_along_route["intersect_geom"] = streets_along_route.geometry.intersection(buffered_route)
    streets_along_route["intersect_length"] = streets_along_route["intersect_geom"].length
    total_weight = 0
    total_length = 0
    for i, row in streets_along_route.iterrows():
        if row.intersect_geom.length <= 15:  # ignore non-relevant streets
            continue
        highway_type = row.highway
        segment_weight = weights[("highway", highway_type)]
        total_weight += segment_weight * row.intersect_geom.length
        total_length += row.intersect_geom.length
    return total_weight / total_length


def adresses_inside_polygon(polygon_gdf, adresses):
    polygon_gdf = polygon_gdf.to_crs(adresses.crs)
    possible_matches = adresses.iloc[adresses.geometry.sindex.query(polygon_gdf, predicate="within")]
    return possible_matches[possible_matches.within(polygon_gdf)]



def cut(polygon_gdf, min_adresses, weights, streets, adresses):
    borders = polygon_gdf['geometry'].boundary
    borders = gpd.GeoDataFrame(geometry=borders, crs=polygon_gdf.crs)

    intersections = find_valid_intersections(borders, streets)
    cuts = find_all_cuts(intersections)
    cuts["weight"] = [calculate_weight(row, weights, streets) for i, row in cuts.iterrows()]
    cuts = gpd.clip(cuts, polygon_gdf.unary_union)  
    adresses = adresses.to_crs(polygon_gdf.crs)
    
    cuts_to_keep = []

    polygon = polygon_gdf.geometry.iloc[0]
    for i, row in cuts.iterrows():
        line = row.geometry
        result = split(polygon, line)
        result = gpd.GeoDataFrame(geometry=list(result.geoms), crs="EPSG:2180")
        if result.size < 2:
            continue
        print(adresses_inside_polygon)


        




poly = gpd.read_file("przyklad_routes/przykladowy_obszar.gpkg")
adresses = gpd.read_file("input_data/adresy_warszawa.gpkg")
streets = gpd.read_file("input_data/ulice.gpkg")
print(adresses_inside_polygon(poly, adresses))
cut(poly, 10, default_weights, streets, streets)
print("koniec")
    
    



