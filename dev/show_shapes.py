import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import cm
import matplotlib.colors as mcolors
from shapely.geometry.base import BaseGeometry
import contextily as ctx


def show_shapes(list_of_shapes, epsg=None, label_attr=None, map_source=ctx.providers.OpenStreetMap.Mapnik, alpha_map=1.0):
    """
    Visualizes a list of geospatial shapes with distinct colors, optional labels, and a map background.
    
    Args:
        list_of_shapes: List of GeoDataFrames, GeoSeries, Series, or BaseGeometry objects
        epsg: EPSG code for coordinate reference system (default: None, uses 3857)
        label_attr: Column name to use for labeling shapes (default: None)
        map_source: Contextily basemap provider (default: OpenStreetMap.Mapnik)
                   Options include:
                   - ctx.providers.OpenStreetMap.Mapnik (default street map)
                   - ctx.providers.CartoDB.Positron (light, minimal)
                   - ctx.providers.CartoDB.DarkMatter (dark theme)
                   - ctx.providers.Esri.WorldImagery (satellite)
                   - ctx.providers.Stamen.Terrain (terrain map)
        alpha_map: Transparency of the basemap (0-1, default: 1.0)
    """
    gdfs = []
    colors = []
    labels = []
    
    if epsg is None:
        crs = "EPSG:3857"  # Web Mercator - required for contextily
    else:
        crs = f"EPSG:{epsg}"
    
    cmap = cm.get_cmap("tab10", len(list_of_shapes))
    
    for i, shape in enumerate(list_of_shapes):
        color = mcolors.to_hex(cmap(i))
        
        if isinstance(shape, gpd.GeoDataFrame):
            # Convert to target CRS if needed
            shape_gdf = shape.to_crs(crs) if shape.crs != crs else shape.copy()
            gdfs.append(shape_gdf)
            colors.extend([color] * len(shape_gdf))
            if label_attr and label_attr in shape.columns:
                labels.extend(shape[label_attr].astype(str).tolist())
            else:
                labels.extend([""] * len(shape_gdf))
                
        elif isinstance(shape, gpd.GeoSeries):
            gdf = gpd.GeoDataFrame(geometry=shape, crs=shape.crs if hasattr(shape, 'crs') else crs)
            gdf = gdf.to_crs(crs) if gdf.crs != crs else gdf
            gdfs.append(gdf)
            colors.extend([color] * len(gdf))
            labels.extend([""] * len(gdf))
            
        elif isinstance(shape, pd.Series):  # a row
            shape_crs = shape.geometry.crs if hasattr(shape.geometry, 'crs') else crs
            gdf = gpd.GeoDataFrame(geometry=[shape.geometry], crs=shape_crs)
            gdf = gdf.to_crs(crs) if gdf.crs != crs else gdf
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
    
    # Ensure data is in Web Mercator (EPSG:3857) for contextily
    if gdf.crs != "EPSG:3857":
        gdf = gdf.to_crs("EPSG:3857")
    
    # Separate by geometry type
    polygons = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])]
    lines = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])]
    points = gdf[gdf.geometry.type.isin(["Point", "MultiPoint"])]
    
    fig, ax = plt.subplots(figsize=(12, 10))
    
    # Plot geometries
    if not polygons.empty:
        polygons.plot(ax=ax, facecolor=[colors[i] for i in polygons.index],
                      edgecolor="black", linewidth=1.5, alpha=0.5)
    if not lines.empty:
        lines.plot(ax=ax, color=[colors[i] for i in lines.index], linewidth=2.5)
    if not points.empty:
        points.plot(ax=ax, color=[colors[i] for i in points.index], markersize=100)
    
    # Add basemap
    try:
        ctx.add_basemap(ax, source=map_source, alpha=alpha_map, attribution_size=6)
    except Exception as e:
        print(f"Warning: Could not add basemap: {e}")
        print("Continuing without basemap...")
    
    # Add labels if available
    if label_attr:
        for i, (geom, label) in enumerate(zip(gdf.geometry, labels)):
            if label:
                point = geom.representative_point()
                ax.text(point.x, point.y, label, fontsize=8, ha='center', va='center',
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7, edgecolor='black'))
    
    ax.set_axis_off()
    plt.axis("equal")
    plt.tight_layout()
    plt.show()


# Example usage with different map styles:
# show_shapes(shapes, label_attr="id")  # Default OpenStreetMap
# show_shapes(shapes, label_attr="id", map_source=ctx.providers.CartoDB.Positron)  # Light theme
# show_shapes(shapes, label_attr="id", map_source=ctx.providers.Esri.WorldImagery)  # Satellite
# show_shapes(shapes, label_attr="id", map_source=ctx.providers.CartoDB.DarkMatter)  # Dark theme
# show_shapes(shapes, label_attr="id", alpha_map=0.5)  # Semi-transparent map