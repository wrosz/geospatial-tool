import os
import sqlalchemy
from sqlalchemy import create_engine, text
import geopandas as gpd
import pandas as pd


def connect(connection_config: dict) -> sqlalchemy.engine.Engine:
    '''Create a SQLAlchemy engine using the provided connection configuration.
    Args:
        connection_config (dict): Dictionary containing database connection parameters.
            Expected keys: host, port, name, user, password.
    Returns:
        sqlalchemy.engine.Engine: SQLAlchemy engine object.'''
    db_host = connection_config["host"]
    db_port = connection_config["port"]
    db_name = connection_config["name"]
    db_user = connection_config["user"]
    db_pass = connection_config["password"]
    conn_str = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    return create_engine(conn_str)



def load_area(
        engine: "sqlalchemy.engine.base.Engine",
        areas_cfg: dict,
        area_id: str
    ) -> gpd.GeoDataFrame:
    """
    Loads area geometries from a database table based on a given area ID prefix.
    Args:
        engine (sqlalchemy.engine.base.Engine): SQLAlchemy engine connected to the target database.
        areas_cfg (dict): Configuration dictionary containing table and column names:
            - "area_table": Name of the table containing area data.
            - "area_id_column": Name of the column with area IDs.
            - "area_geom_column": Name of the geometry column.
        area_id (str): Prefix of the area ID to filter the areas.
    Returns:
        geopandas.GeoDataFrame: GeoDataFrame containing the loaded area geometries.
    Raises:
        ValueError: If no areas are found with the specified area ID prefix.
    """
    areas_table_name = areas_cfg["area_table"]
    id_column_name = areas_cfg["area_id_column"]
    query = text(f"SELECT * FROM {areas_table_name} WHERE {id_column_name}::text LIKE :area_id")
    params = {"area_id": f"{area_id}%"}

    area_geom_column_name = areas_cfg["area_geom_column"]
    gdf = gpd.read_postgis(query, engine, geom_col=area_geom_column_name, params=params)
    gdf = gdf.rename_geometry("geometry")
    print(f"Loaded {len(gdf)} areas with ID prefix {area_id} from table {areas_table_name}.")

    if gdf.empty:
        raise ValueError(f"No area found with ID {area_id} in table {areas_table_name}.")
    return gdf


def load_addresses(engine, addresses_cfg, teryt_id=None, bbox=None):
    def load_addresses(
        engine: "sqlalchemy.engine.base.Engine",
        addresses_cfg: dict,
        teryt_id: str = None,
        bbox: tuple[float, float, float, float] = None
    ) -> "gpd.GeoDataFrame":
        """
        Loads address records from a spatial database table using optional filters for TERYT ID and bounding box.
        Args:
            engine (sqlalchemy.engine.base.Engine): SQLAlchemy engine connected to the spatial database.
            addresses_cfg (dict): Configuration dictionary containing:
                - "addresses_table" (str): Name of the addresses table.
                - "addresses_geom_column" (str): Name of the geometry column.
                - "crs" (str): Coordinate reference system in the format "EPSG:XXXX".
                - "teryt_column" (str, optional): Name of the TERYT column.
            teryt_id (str, optional): TERYT area identifier to filter addresses by administrative area. Defaults to None.
            bbox (tuple[float, float, float, float], optional): Bounding box (minx, miny, maxx, maxy) to spatially filter addresses. Defaults to None.
        Returns:
            geopandas.GeoDataFrame: GeoDataFrame containing the loaded addresses with geometry column renamed to "geometry".
        Raises:
            ValueError: If no addresses are found matching the given criteria.
        """
    addresses_table_name = addresses_cfg["addresses_table"]
    addresses_geom_column_name = addresses_cfg["addresses_geom_column"]
    teryt_column_name = addresses_cfg.get("teryt_column")

    where_clauses = []
    params = {}

    if teryt_id is not None and teryt_column_name is not None:
        where_clauses.append(f"{teryt_column_name}::text LIKE :area_id")
        params["area_id"] = f"{teryt_id}%"

    if bbox is not None:
        # bbox: (minx, miny, maxx, maxy)
        epsg_num = addresses_cfg.get("crs").split(":")[1]
        where_clauses.append(
            f"ST_Intersects({addresses_geom_column_name}, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, {epsg_num}))"
        )
        params.update({"minx": bbox[0], "miny": bbox[1], "maxx": bbox[2], "maxy": bbox[3]})

    where_sql = ""
    if where_clauses:
        where_sql = " WHERE " + " AND ".join(where_clauses)

    query = text(f"SELECT * FROM {addresses_table_name}{where_sql}")
    gdf = gpd.read_postgis(query, engine, geom_col=addresses_geom_column_name, params=params)
    gdf = gdf.rename_geometry("geometry")
    print(
        f"Loaded {len(gdf)} addresses from table {addresses_table_name}."
        f"{' teryt_id=' + str(teryt_id) if teryt_id is not None else ''}"
        f"{', bbox=' + str(bbox) if bbox is not None else ''}"
    )
    if gdf.empty:
        raise ValueError(f"No addresses found in table {addresses_table_name} with the given criteria: "
                 f"{'teryt_id=' + str(teryt_id) if teryt_id is not None else ''} "
                 f"{'bbox=' + str(bbox) if bbox is not None else ''}.")
    return gdf


def load_weights_from_csv(path):
    def load_weights_from_csv(path: str) -> "pd.DataFrame":
        """
        Loads a weights table from a CSV file and validates required columns.

        Args:
            path (str): The file path to the CSV file containing the weights table.

        Returns:
            pd.DataFrame: A pandas DataFrame containing the weights table.

        Raises:
            ValueError: If any of the required columns ('osm_key', 'osm_value', 'weight') are missing in the CSV file.
        """
    weights_table = pd.read_csv(path)
    for colname in ["osm_key", "osm_value", "weight"]:
        if colname not in weights_table.columns:
            raise ValueError(f"Column '{colname}' not found in weights CSV file.")
    print(f"Loaded weights from {path}.")
    return weights_table


def load_osm_data(engine, osm_data_cfg, bbox=None):
    def load_osm_data(
        engine: "sqlalchemy.engine.base.Engine",
        osm_data_cfg: dict,
        bbox: tuple[float, float, float, float] | None = None
    ) -> "geopandas.GeoDataFrame":
        """
        Loads OpenStreetMap (OSM) data from a database table into a GeoDataFrame, optionally filtering by a bounding box.

        Args:
            engine (sqlalchemy.engine.base.Engine): SQLAlchemy engine connected to the database.
            osm_data_cfg (dict): Configuration dictionary containing:
                - 'table' (str): Name of the OSM data table.
                - 'geom_column' (str): Name of the geometry column.
                - 'crs' (str): Coordinate reference system in the format 'EPSG:XXXX'.
            bbox (tuple[float, float, float, float] | None, optional): Bounding box to filter the data,
                specified as (minx, miny, maxx, maxy). If None, no spatial filter is applied.

        Returns:
            geopandas.GeoDataFrame: GeoDataFrame containing the loaded OSM data.

        Raises:
            ValueError: If no data is found in the specified table (and bounding box, if provided).
        """
    query = f"SELECT * FROM {osm_data_cfg['table']}"
    if bbox is not None:
        # bbox: (minx, miny, maxx, maxy)
        epsg_num = osm_data_cfg.get("crs").split(":")[1]
        geom_col = osm_data_cfg["geom_column"]
        bbox_sql = (
            f"ST_Intersects({geom_col}, ST_MakeEnvelope({bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]}, {epsg_num}))"
        )
        query += f" WHERE {bbox_sql}"
    gdf = gpd.read_postgis(query, engine, geom_col=osm_data_cfg["geom_column"])
    if gdf.empty:
        raise ValueError(f"No OSM data found in table {osm_data_cfg['table']}.")
    print(f"Loaded OSM data ({len(gdf)} rows) from table {osm_data_cfg['table']}."
          f"{' with bbox=' + str(bbox) if bbox is not None else ''}")
    gdf = gdf.rename_geometry("geometry")
    return gdf


def save_partition_result(engine, gdf, output_cfg):
    def save_partition_result(
        engine: "sqlalchemy.engine.Engine",
        gdf: "gpd.GeoDataFrame",
        output_cfg: dict
    ):
        """
        Saves a GeoDataFrame to a PostGIS table after reprojecting it to the specified CRS.

        Args:
            engine (sqlalchemy.engine.Engine): SQLAlchemy engine connected to the target database.
            gdf (geopandas.GeoDataFrame): The GeoDataFrame containing spatial data to be saved.
            output_cfg (dict): Configuration dictionary with the following keys:
                - "crs" (str or dict): The target coordinate reference system for reprojection.
                - "table" (str): The name of the target table in the database.

        Returns:
            None
        """
    gdf = gdf.to_crs(output_cfg["crs"])
    gdf.to_postgis(output_cfg["table"], engine, if_exists="replace")
    print(f"Saved partition result to table {output_cfg["table"]}.")
