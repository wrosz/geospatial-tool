import sqlalchemy
from sqlalchemy import create_engine, text
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from datetime import datetime


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
        area_id: str | list[str]
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
    from sqlalchemy import text

    areas_table_name = areas_cfg["area_table"]
    id_column_name = areas_cfg["area_id_column"]

    if isinstance(area_id, list):
        like_clauses = []
        params = {}

        for i, prefix in enumerate(area_id):
            param_name = f"prefix_{i}"
            like_clauses.append(f"{id_column_name}::text LIKE :{param_name}")
            params[param_name] = f"{prefix}%"

        where_clause = " OR ".join(like_clauses)
        query = text(f"SELECT * FROM {areas_table_name} WHERE {where_clause}")

    else:
        query = text(f"SELECT * FROM {areas_table_name} WHERE {id_column_name}::text LIKE :area_id")
        params = {"area_id": f"{area_id}%"}

    area_geom_column_name = areas_cfg["area_geom_column"]
    gdf = gpd.read_postgis(query, engine, geom_col=area_geom_column_name, params=params)
    if area_geom_column_name != "geometry":
        gdf = gdf.rename_geometry("geometry")
    print(f"Loaded {len(gdf)} areas with ID prefix {area_id} from table {areas_table_name}.")

    if gdf.empty:
        raise ValueError(f"No area found with ID {area_id} in table {areas_table_name}.")
    return gdf


def load_addresses(
    engine: "sqlalchemy.engine.base.Engine",
    addresses_cfg: dict,
    teryt_id: str = None,
    bbox: tuple[float, float, float, float] = None
) -> "gpd.GeoDataFrame":
    """
    Loads address records from a spatial database table using optional filters for TERYT ID, bounding box, and time period.
    Args:
        engine (sqlalchemy.engine.base.Engine): SQLAlchemy engine connected to the spatial database.
        addresses_cfg (dict): Configuration dictionary containing:
            - "addresses_table" (str): Name of the addresses table.
            - "addresses_geom_column" (str): Name of the geometry column.
            - "crs" (str): Coordinate reference system in the format "EPSG:XXXX".
            - "teryt_column" (str, optional): Name of the TERYT column.
            - "date_column" (str, optional): Name of the date column for filtering by time period.
        teryt_id (str, optional): TERYT area identifier to filter addresses by administrative area. Defaults to None.
        bbox (tuple[float, float, float, float], optional): Bounding box (minx, miny, maxx, maxy) to spatially filter addresses. Defaults to None.
    Returns:
        geopandas.GeoDataFrame: GeoDataFrame containing the loaded addresses with geometry column renamed to "geometry".
    Raises:
        ValueError: If no addresses are found matching the given criteria.
    """
    addresses_table_name = addresses_cfg["addresses_table"]
    addresses_geom_column_name = addresses_cfg["addresses_geom_column"]

    where_clauses = []
    params = {}

    filtered_by_teryt_id = False
    filtered_by_time_period = False
    filtered_by_bbox = False

    # Filter by TERYT_ID if provided
    if teryt_id is not None:
        teryt_column_name = addresses_cfg.get("teryt_column")
        if teryt_column_name is None:
            raise ValueError("TERYT ID provided but 'teryt_column' not specified in addresses configuration.")
        else:
            print(f"Filtering addresses by TERYT ID: {teryt_id} using column '{teryt_column_name}'")
            where_clauses.append(f"{teryt_column_name}::text LIKE :area_id")
            params["area_id"] = f"{teryt_id}%"
            filtered_by_teryt_id = True

    # Filter by time period if provided
    time_period_cfg = addresses_cfg.get("time_period")
    if time_period_cfg is not None:
        time_column_name = time_period_cfg.get("column_name")
        start = time_period_cfg.get("start")
        end = time_period_cfg.get("end")
        if time_column_name is None or start is None or end is None:
            print("Time period configuration is incomplete, skipping time filtering.")
        else:
            print(f"Filtering addresses by time period: {start} to {end} using column '{time_column_name}'")
            where_clauses.append(f"{time_column_name} BETWEEN :start_date AND :end_date")
            params["start_date"] = start
            params["end_date"] = end
            filtered_by_time_period = True

    # Filter by bounding box if provided
    if bbox is not None:
        # bbox: (minx, miny, maxx, maxy)
        epsg_num = addresses_cfg.get("crs").split(":")[1]
        where_clauses.append(
            f"ST_Intersects({addresses_geom_column_name}, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, {epsg_num}))"
        )
        params.update({"minx": bbox[0], "miny": bbox[1], "maxx": bbox[2], "maxy": bbox[3]})
        filtered_by_bbox = True

    where_sql = ""
    if where_clauses:
        where_sql = " WHERE " + " AND ".join(where_clauses)

    query = text(f"SELECT * FROM {addresses_table_name}{where_sql}")
    gdf = gpd.read_postgis(query, engine, geom_col=addresses_geom_column_name, params=params)
    
    if addresses_geom_column_name != "geometry":
        gdf = gdf.rename_geometry("geometry")

    print(
        f"Loaded {len(gdf)} addresses from table {addresses_table_name} with criteria:"
        f"{'teryt_id = ' + str(teryt_id) if filtered_by_teryt_id else ''}"
        f"{'time_period = ' + str(time_period_cfg['start']) + ' to ' + str(time_period_cfg['end']) if filtered_by_time_period else ''} "
        f"{'bbox = ' + str(bbox) if filtered_by_bbox else ''}"
    )
    if gdf.empty:
        raise ValueError(f"No addresses found in table {addresses_table_name} with the given criteria: "
                 f"{'teryt_id = ' + str(teryt_id) if filtered_by_teryt_id else ''} "
                 f"{'time_period = ' + str(time_period_cfg['start']) + ' to ' + str(time_period_cfg['end']) if filtered_by_time_period else ''} "
                 f"{'bbox = ' + str(bbox) if filtered_by_bbox else ''}.")
    return gdf


def get_num_days_from_time_period(addresses_cfg: dict) -> int:
    """
    Calculates the number of days for the given addresses configuration.

    Args:
        addresses_cfg (dict): The addresses configuration dictionary.

    Returns:
        int: The number of days.
    """
    # Calculate number of days in the specified time period if all values are not null
    time_period = addresses_cfg.get("time_period")
    if time_period and all(time_period.get(k) is not None for k in ["start", "end"]):
        start = datetime.fromisoformat(time_period["start"])
        end = datetime.fromisoformat(time_period["end"])
        num_days = (end - start).days
        return num_days + 1
    else:
        raise ValueError("Can't calculate average daily number of addresses. Time period not specified or incomplete in addresses configuration.")


def load_weights_from_csv(path: str | None, weights_config: dict) -> "pd.DataFrame":
    """
    Loads a weights table from a CSV file and validates required columns.

    Args:
        path (str): The file path to the CSV file containing the weights table.

    Returns:
        pd.DataFrame: A pandas DataFrame containing the weights table.

    Raises:
        ValueError: If any of the required columns ('osm_key', 'osm_value', 'weight') are missing in the CSV file.
    """

    if path is None:
        path = weights_config["default_weights_path"]
    weights_table = pd.read_csv(path)
    for colname in ["osm_key", "osm_value", "weight"]:
        if colname not in weights_table.columns:
            raise ValueError(f"Column '{colname}' not found in weights CSV file.")
    print(f"Loaded weights from {path}.")
    return weights_table


def load_osm_data(
        engine: "sqlalchemy.engine.base.Engine",
        osm_data_cfg: dict,
        bbox: tuple[float, float, float, float] | None = None
    ) -> "gpd.GeoDataFrame":
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
          f"{'bbox=' + str(bbox) if bbox is not None else ''}")
    
    if geom_col != "geometry":
        gdf = gdf.rename_geometry("geometry")
    
    return gdf


def load_all_data_with_bbox(engine, config, args):
    '''Loads all relevant data from the database within a specified bounding box.'''

    print("Loading areas...")
    # Load data from database
    area  = load_area(engine, config["areas"], args.area_id)
    # Get bounding box of the union of area geometries
    bbox = area.union_all().bounds  # (minx, miny, maxx, maxy)
    from_crs = config["areas"]["crs"]
    print(f"Bounding box of area: {bbox}")

    def reproject_bbox(bbox, crs_from, crs_to):
        """Reproject bounding box coordinates from one CRS to another."""
        bbox_gdf = gpd.GeoDataFrame(geometry=[box(*bbox)], crs=crs_from)
        bbox_gdf = bbox_gdf.to_crs(crs_to)
        return bbox_gdf.geometry[0].bounds
    
    # Load addresses using bbox and teryt_id if provided
    print("Loading adresses...")

    bbox_reprojected = reproject_bbox(bbox, from_crs, config["addresses"]["crs"])
    teryt_id = args.teryt_id if args.teryt_id else None

    addresses = load_addresses(engine, config["addresses"], teryt_id=teryt_id, bbox=bbox_reprojected)
    if addresses.empty:
        print(f"No addresses found for TERYT ID {teryt_id} in bbox {bbox}, loading all addresses in bbox.")
        addresses = load_addresses(engine, config["addresses"], bbox=bbox)

    if config.get("osm_data") is None:
        return {"area": area, "addresses": addresses}

    # Load OSM data using bounding box
    print("Loading OpenStreetMap data...")
    bbox_reprojected = reproject_bbox(bbox, from_crs, config["osm_data"]["crs"])
    osm_data = load_osm_data(engine, config["osm_data"], bbox=bbox_reprojected)

    return {"area": area, "addresses": addresses, "osm_data": osm_data}


def save_result(
        engine: "sqlalchemy.engine.Engine",
        gdf: "gpd.GeoDataFrame",
        output_cfg: dict,
        output_table: str | None = None
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
    output_table = output_table or output_cfg["table"]
    gdf = gdf.to_crs(output_cfg["crs"])
    gdf.to_postgis(output_cfg["table"], engine, if_exists="replace")
    print(f"Saved result to table {output_cfg['table']}.")
