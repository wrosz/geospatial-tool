import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import cm
import matplotlib.colors as mcolors
from shapely.geometry.base import BaseGeometry

def show_shapes(list_of_shapes, epsg=None, label_attr=None):
    gdfs = []
    colors = []
    labels = []

    if epsg is None:
        crs = "EPSG:3857"  # or use your metrical_crs
    else:
        crs = f"EPSG:{epsg}"

    cmap = cm.get_cmap("tab10", len(list_of_shapes))

    for i, shape in enumerate(list_of_shapes):
        color = mcolors.to_hex(cmap(i))

        if isinstance(shape, gpd.GeoDataFrame):
            gdfs.append(shape)
            colors.extend([color] * len(shape))

            if label_attr and label_attr in shape.columns:
                labels.extend(shape[label_attr].astype(str).tolist())
            else:
                labels.extend([""] * len(shape))

        elif isinstance(shape, gpd.GeoSeries):
            gdf = gpd.GeoDataFrame(geometry=shape, crs=crs)
            gdfs.append(gdf)
            colors.extend([color] * len(gdf))
            labels.extend([""] * len(gdf))

        elif isinstance(shape, pd.Series):  # a row
            gdf = gpd.GeoDataFrame(geometry=[shape.geometry], crs=crs)
            gdfs.append(gdf)
            colors.append(color)
            if label_attr and label_attr in shape:
                labels.append(str(shape[label_attr]))
            else:
                labels.append("")

        elif isinstance(shape, BaseGeometry):
            gdf = gpd.GeoDataFrame(geometry=[shape], crs=crs)
            gdfs.append(gdf)
            colors.append(color)
            labels.append("")

    gdf = pd.concat(gdfs, ignore_index=True)

    # Separate by geometry type
    polygons = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])]
    lines = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])]
    points = gdf[gdf.geometry.type.isin(["Point", "MultiPoint"])]

    fig, ax = plt.subplots(figsize=(8, 6))

    if not polygons.empty:
        polygons.plot(ax=ax, facecolor=[colors[i] for i in polygons.index],
                      edgecolor="black", linewidth=1, alpha=0.4)
    if not lines.empty:
        lines.plot(ax=ax, color=[colors[i] for i in lines.index], linewidth=2)
    if not points.empty:
        points.plot(ax=ax, color=[colors[i] for i in points.index], markersize=100)

    # Add labels if available
    if label_attr:
        for i, (geom, label) in enumerate(zip(gdf.geometry, labels)):
            if label:
                # Use representative_point to place label inside polygons if needed
                point = geom.representative_point()
                ax.text(point.x, point.y, label, fontsize=5, ha='center', va='center')

    ax.set_axis_off()
    plt.axis("equal")
    plt.tight_layout()
    plt.show()
