# Geospatial Partitioning and Merging Tool

This Python-based tool enables spatial optimization of geographic zones by splitting ("cut") and combining ("merge") areas based on address distribution and routing efficiency. It is particularly useful for applications such as courier zone planning or logistics delivery route optimization.

---

## Features

### `cut`: Area Partitioning

The `cut` operation recursively divides spatial areas into smaller sub-regions that each meet a minimum threshold of address points. It uses geographic and OSM-derived attributes to determine optimal cutting lines.

* Retrieves area and address data from a PostgreSQL/PostGIS database.
* Accepts one or more area identifiers (IDs) and splits them based on address count.
* Uses user-defined weights for OpenStreetMap attributes to influence cut lines (e.g., `highway=primary` = weight 5).
* Results include: number of addresses per resulting area, adjacency relationships, and border weights. These are saved back into the database.

### `merge`: Area Aggregation

The `merge` operation combines smaller regions into larger ones while satisfying minimum and maximum thresholds for address count.

* Fetches address and area data from PostgreSQL/PostGIS.
* Uses OSRM (Open Source Routing Machine) to compute shortest travel times between region centroids.
* Merges are optimized for spatial contiguity and time-based proximity.
* Outputs include: number of addresses per merged area, and lists of source area IDs, written to the database.

---

## Requirements

To run the tool, you need the following components:

* Python ≥ 3.13.3
* Required Python libraries (install via `requirements.txt`)
* OpenStreetMap data in `.osm.pbf` format (e.g., from Geofabrik)
* Docker and a running OSRM instance
* PostgreSQL with PostGIS and HStore extensions
* osm2pgsql tool for loading OSM data into Postgres
* A PostgreSQL database with:

  * Table of areas (polygons)
  * Table of addresses (points)
  * Table with street geometries and relevant OSM tags
* A completed config file (`db_config.json`, based on `sample_db_config.json`)

---

## Installation and Setup

### Clone Repository and Install Dependencies

```bash
git clone https://github.com/your-username/geospatial-tool.git
cd geospatial-tool
pip install -r requirements.txt
```

### Download OSM Data

Get the OSM data for your region:

```bash
wget https://download.geofabrik.de/europe/poland/mazowieckie-latest.osm.pbf
```


### Generate `output_profile.lua`

Before starting the OSRM Docker server, you need an `output_profile.lua` in the same directory as your `.osm.pbf` file.

You can use the **default profile** included in the repo (`src\osrm_profiles\output_profile.lua`), or generate a custom one with different weights using the script and a `weights.csv` file:

```powershell
python generate_profile.py weights.csv output_profile.lua
```

See the **Configuration File** section below for the required format of `weights.csv`.

**Note:** This is experimental and may not work well on very large OSM files.



### Set Up Docker and OSRM

1. Install Docker Desktop.
2. In the directory with your `.osm.pbf` file, run:

```bash
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-extract -p /data/output_profile.lua /data/mazowieckie-latest.osm.pbf
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-partition /data/mazowieckie-latest.osrm
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-customize /data/mazowieckie-latest.osrm
```

To start the server:

```bash
docker run -t -i -p 5000:5000 -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-routed --algorithm mld /data/mazowieckie-latest.osrm
```

---

## Setting Up the PostgreSQL Database

### PostGIS and Extensions

Ensure you have the necessary extensions:

```sql
CREATE EXTENSION postgis;
CREATE EXTENSION hstore;
```

### Import OSM Data

Use `osm2pgsql` to import OSM geometries into your database:

```bash
osm2pgsql -d osm -U postgres --create --slim --hstore -C 2000 -G --number-processes 4 mazowieckie-latest.osm.pbf
```

### Required Tables

Your database must include at least three tables required for the area processing workflow. Each table must contain specific types of data, which are outlined in the sections below.
While the example column names are provided for reference, you are free to use your own - just make sure they are correctly specified in the configuration file, as described in the next section.

#### Addresses Table

* Must include:

  * `geom`: Point geometries
* Optional:

  * `timestamp`: for time-based filtering
  * `teryt`: administrative ID for optional filtering

#### Areas Table

* Must include:

  * `id`: unique area identifiers
  * `geom`: geometry column (Polygon)

#### OSM Geometry Table

* Must include:

  * `geom`: LineString or MultiLineString geometries
  * OSM attributes (e.g., `highway`, `waterway`, etc.)


---

## Configuration File (`db_config.json`)

To run the program, you need to provide configuration details in a `db_config.json` file. A sample template is available in `sample_db_config.json`. You should modify it according to your own data. Below is a detailed explanation of each configuration section.

---

### `connection`

Contains the credentials required to connect to your PostgreSQL database.

```json
"connection": {
  "host": "localhost",
  "port": 5432,
  "name": "your_database_name",
  "user": "your_username",
  "password": "your_password"
}
```

---

### `weights`

This section provides the default path to a `.csv` file containing weights for geometry attributes from OpenStreetMap (OSM). These weights are used in computations unless another weights file is explicitly passed as an argument.
You can find an example weights file at `src/osrm_profiles/weights.csv` - you can either use this path or create your own file with the same format.

```json
"weights": {
  "default_weights_path": "path/to/default_weights.csv"
}
```

#### Requirements for the weights `.csv` file

* The file **must** have headers exactly named: `osm_key`, `osm_value`, `weight`.
* Each subsequent row should have the format: `<key>,<value>,<weight>`, for example:

  ```
  highway,primary,5
  waterway,river,10
  ```
* You can refer to valid OSM keys and values on the [OSM Wiki - Map Features](https://wiki.openstreetmap.org/wiki/Map_features).


---

### `data_for_partition`

Defines the source tables used for **area partitioning** (splitting geometries). The section consists of three parts: `addresses`, `areas`, and `osm_data`.


#### `addresses`

```json
"addresses": {
  "addresses_table": "your_addresses_table",
  "addresses_geom_column": "your_geom_column",
  "teryt_column": "teryt",
  "time_period": {
    "column_name": "your_time_column",
    "start": "YYYY-MM-DD",
    "end": "YYYY-MM-DD"
  },
  "crs": "EPSG:XXXX"
}
```

**Explanation:**

* **`addresses_table`**: Name of the table containing address points.
* **`addresses_geom_column`**: Name of a column with address geometries (should be of type `POINT`).
* **`teryt_column`** *(optional)*: Column with administrative/territory codes for filtering data; set to `null` if not needed.
* **`time_period`** *(optional)*: Use to filter addresses by a time window:

  * `column_name`: Name of the date column.
  * `start` / `end`: Start and end dates (format: `YYYY-MM-DD`).
* **`crs`**: Coordinate Reference System (e.g., `EPSG:4326` for lat/lon) used in this table.


#### `areas`

```json
"areas": {
  "area_table": "your_areas_table",
  "area_id_column": "your_area_id_column",
  "area_geom_column": "your_area_geom_column",
  "crs": "EPSG:XXXX"
}
```

**Explanation:**

* **`area_table`**: Name of the table containing spatial areas to be partitioned.
* **`area_id_column`**: Name of a column containing area identifiers.
* **`area_geom_column`**: Column with area geometries (should be of type `POLYGON`).
* **`crs`**: Coordinate Reference System used by this table.



#### `osm_data`

```json
"osm_data": {
  "table": "your_osm_streets_table",
  "geom_column": "your_osm_geom_column",
  "crs": "EPSG:XXXX"
}
```

**Explanation:**

* **`table`**: Name of the table containing geometries imported from OpenStreetMap (e.g., roads, waterways).
* **`geom_column`**: Column with OSM geometries.
* **`crs`**: CRS for the OSM geometry data.

---
#### `data_for_merge`

This section is identical in structure to `data_for_partition`, and should be filled in if you're using **different** data sources for merging than for partitioning. Otherwise, you can simply copy the values from the `data_for_partition` section.

```json
"data_for_merge": {
  "addresses": {
    "addresses_table": "your_merge_addresses_table",
    "addresses_geom_column": "your_merge_geom_column",
    "teryt_column": null,
    "crs": "EPSG:XXXX",
    "time_period": {
      "column_name": "your_time_column",
      "start": "YYYY-MM-DD",
      "end": "YYYY-MM-DD"
    }
  },
  "areas": {
    "area_table": "your_merge_areas_table",
    "area_id_column": "your_merge_area_id_column",
    "area_geom_column": "your_merge_area_geom_column",
    "crs": "EPSG:XXXX"
  },
  "output": {
    "table": "your_merge_output_table",
    "crs": "EPSG:XXXX"
  }
}
```

---

### Final Step

After customizing your configuration, save the file as `db_config.json` and place it in the **project root directory**, at the same level as `main.py`.

---


## Running the Program

### Start OSRM Server

Before running the tool, make sure OSRM is running in the background:

```bash
docker run -t -i -p 5000:5000 -v "${PWD}:/data" osrm/osrm-backend osrm-routed --algorithm mld /data/mazowieckie-latest.osrm
```

### Basic Command Structure

#### Cut Operation

```bash
python main.py cut --area_id <ID> --min_addresses <MIN>
```

#### Merge Operation

```bash
python main.py merge --area_id <ID(s)> --min_addresses <MIN> --max_addresses <MAX>
```

### Optional Arguments

* `--weights_path <path>`: Custom CSV for OSM weights
* `--avg`: Use average address count over time period specified in the configuration file
* `--teryt_id <id>`: Filter addresses by administrative ID
* `--output_table <name>`: Override default output table name
* `--config <path>`: Use a different config file

### Examples

```bash
python main.py cut --area_id 1234 --min_addresses 20
python main.py merge --area_id 123 7890 --min_addresses 10 --max_addresses 20 --avg
```

---

## Example Output

### Cut

```
Partitioned polygon 146201_1.0007 into 18 pieces.

Saved result to table cut_results_123.
```

### Merge

```
Merging completed successfully.
Number of merged polygons: 270 out of 477 original polygons.

Saved result to table merge_results_123.
```

Once such message appears, the results will be available in your PostgreSQL database - in the table with the name you specified.

---

## Future Development

* Add support for generating custom OSRM profiles based on user-defined weights
* Enable merge operations based on border weights (similar to cut)
* Combine cut and merge logic into a single adaptive tool

---

## License

MIT License

---

## Contact

For feedback or contributions, please open an issue or contact the project maintainer.
