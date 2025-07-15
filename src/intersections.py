import geopandas as gpd
import numpy as np

def azimuth(p1, p2):
    '''Zwraca azymut odcinka o końcach p1, p2'''
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    angle = np.degrees(np.arctan2(dy, dx)) % 360
    return angle


def check_angle(pt, g, u):
    '''Zwraca kąt pomiędzy odcinkami g, u przecinającymi się w punkcie pt'''

    # Interpolacja punktów dalej na linii
    g_proj = g.project(pt)
    u_proj = u.project(pt)
    g_near = g.interpolate(g_proj + 1)
    u_near = u.interpolate(u_proj + 1)
    
    az_g = azimuth(pt, g_near)
    az_u = azimuth(pt, u_near)
    
    diff = abs(az_g - az_u)
    if diff > 180:
        diff = 360 - diff
    return diff


def find_intersections_with_angle(borders: gpd.GeoDataFrame, streets: gpd.GeoDataFrame):
    '''Zwraca ramkę danych z punktami przecięcia granic obszarów ewidencyjnych i ulic.
    Każdy punkt ma dodatkowy atrybut angle (kąt między ulicą a granicą przecinającymi się w tym punkcie)'''

    # Zgodny układ współrzędnych
    if borders.crs != streets.crs:
        streets = streets.to_crs(borders.crs)

    # Poprawne geometrie
    borders = borders[borders.is_valid]
    streets = streets[streets.is_valid]

    ulice_sindex = streets.sindex  # Spatial index

    intersections = []

    for i, g_row in borders.iterrows():
        # Potencjalne ulice przecinające bounding box granicy
        possible_matches_index = list(ulice_sindex.intersection(g_row.geometry.bounds))
        possible_matches = streets.iloc[possible_matches_index]
        
        # Dokładne przecięcia na possible_matches
        for j, u_row in possible_matches.iterrows():
            if g_row.geometry.intersects(u_row.geometry):
                pt = g_row.geometry.intersection(u_row.geometry)  # punkt przecięcia ulicy z granicą
                g = g_row.geometry  # geometria granicy
                u = u_row.geometry  # geometria ulicy

                if pt.geom_type != 'Point':
                    continue

                try:  # dołącz atrybuty do znalezionego punktu i zapisz w liście intersections
                    angle = check_angle(pt, g, u)
                    intersections.append({
                    "geometry": pt,
                    # "granica_geom": g,
                    # "ulica_geom": u,
                    "angle": angle
                    })
                except Exception as e:
                    continue

    gdf = gpd.GeoDataFrame(intersections, geometry=[f["geometry"] for f in intersections], crs=borders.crs)
    gdf["angle"] = [f["angle"] for f in intersections]
    
    print("find_intersections succeeded")
    return gdf


def remove_small_angles(intersections: gpd.GeoDataFrame):
    return intersections[(intersections.angle >= 20) & (intersections.angle <= 160)]


def remove_close_points(points: gpd.GeoDataFrame, treshold):
    '''Zwraca odfiltrowaną ramkę danych points, w której każdy punkt jest oddalony od pozostałych
    na odległość większą niż treshold'''

    points = points.to_crs("EPSG:2180")
    geometries = points.geometry
    sindex = geometries.sindex

    kept = []
    rejected = set()

    for i, geom in enumerate(geometries):
        if i in rejected:
            continue

        kept.append(i)
        # Kandydaci na punkty bliższe niż treshold
        candidate_idxs = sindex.query(geom.buffer(treshold))
        for j in candidate_idxs:
            if j == i or j in rejected:
                continue
            if geom.distance(geometries.iloc[j]) < treshold:
                rejected.add(j)

    print("remove_close_points succeeded")
    return points.iloc[kept].copy()


def find_valid_intersections(borders: gpd.GeoDataFrame, streets=gpd.read_file("input_data/ulice_extended.gpkg"), treshold=50):
    points = find_intersections_with_angle(borders, streets)
    points = points[(points.angle >= 20) & (points.angle <= 160)]  # remove small angles
    points = remove_close_points(points, treshold)
    return points