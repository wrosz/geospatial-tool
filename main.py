from src.cuts import *
import geopandas as gpd
import numpy as np

def main():
    points = gpd.read_file("przyklad_routes/przykladowe_intersections.gpkg")
    points = points.to_crs(epsg=4326)
    cuts = []
    for i in range(len(points)):
        for j in range(i+1, len(points)):
            coord1 = (points.geometry[i].x, points.geometry[i].y)
            coord2 = (points.geometry[j].x, points.geometry[j].y)
            line = get_osrm_route(coord1, coord2)
            if line:
                cuts.append({"geometry": line, "from": i, "to": j})

    gdf = gpd.GeoDataFrame(cuts, geometry="geometry", crs="EPSG:4326")
    gdf.to_file("przyklad_routes/all_cuts.gpkg", driver="GPKG")




if __name__ == "__main__":
    main()