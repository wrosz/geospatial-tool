# Praktyki Project

This project is a Python-based geospatial data processing toolkit. It leverages GeoPandas and NumPy to analyze, filter, and process spatial data, particularly for urban infrastructure such as streets, addresses, and boundaries.

---

## Project Structure
```bash
.
├── .gitignore
├── sample_db_config.json      # Example config in required format
├── main.py                    # Entry point
├── README.md
├── requirements.txt
└── src/                       # Main source code
    ├── logic_config.py        # Configuration for global variables
    ├── utils.py               # Utility functions
    ├── handle_database/       # Database I/O logic
    │   ├── db_io.py
    │   └── default_weights.csv
    ├── merge/                 # Merging logic and execution
    │   ├── merge_logic.py
    │   └── run_merge.py
    ├── partition/             # Partitioning logic and execution
    │   ├── better_cuts_beta.py
    │   ├── cuts_logic.py
    │   ├── intersections_logic.py
    │   └── run_partition.py

```
---

## Installation

This project requires Python 3. You can install all necessary dependencies using the provided `requirements.txt` file:


pip install -r requirements.txt

```bash
python -m venv .venv
.venv\Scripts\activate      # On Windows
source .venv/bin/activate  # On Linux/macOS
pip install -r requirements.txt
```

---

## Database Requirements & Setup

This project requires access to a **PostgreSQL** database with the **PostGIS** extension enabled. The database is used to store and query spatial data (areas, addresses, OSM data, etc.).

### Required Data in the Database

Your PostgreSQL/PostGIS database must contain the following spatial datasets:

- **OpenStreetMap (OSM) street geometries**: A table with street line geometries (e.g., from OSM extracts), used for routing and partitioning. Each row should represent a street segment with geometry in a supported CRS.
- **Polygon areas with IDs**: A table of polygons (e.g., administrative boundaries, districts, or custom areas) with a unique area ID column. These are the regions to be partitioned/cut.
- **Addresses as points**: A table of address points (e.g., building entrances, address locations) with geometry. Optionally, include a `teryt` column (or similar administrative code) to speed up filtering and calculations for large datasets.

**Summary Table Requirements:**

| Table         | Geometry Type | Required Columns                | Optional Columns |
|---------------|---------------|---------------------------------|------------------|
| OSM Streets   | LineString    | geometry                        | attributes as needed |
| Areas         | Polygon       | geometry, area_id               |                 |
| Addresses     | Point         | geometry                        | teryt           |

All tables should have their geometry columns properly indexed for spatial queries. The CRS (coordinate reference system) for each table must be specified in your config file.

You can import data using tools like `ogr2ogr`, QGIS, or `psql`.


### 1. Install PostgreSQL and PostGIS

- Download and install PostgreSQL: https://www.postgresql.org/download/
- During installation, select the option to install **StackBuilder** and use it to add the **PostGIS** extension.

### 2. Create a Database and Enable PostGIS

After installing PostgreSQL, create a new database (e.g., `spatialdb`) and enable PostGIS:

```sql
CREATE DATABASE spatialdb;
\c spatialdb
CREATE EXTENSION postgis;
```

### 3. Database Configuration

The connection details (host, port, user, password, database name) are specified in a JSON config file (default: `db_config.json`). Example:

```json
{
  "connection": {
    "host": "localhost",
    "port": 5432,
    "user": "your_username",
    "password": "your_password",
    "database": "spatialdb"
  },
  "weights": {...},
  "data_for_partition": {...},
  ...
}
```

**Note:** You must provide the correct table names and CRS (coordinate reference system) for your data in the config file. See the sample config for details.

The calculated cuts (partition or merge results) will be saved to the output table specified in your config file under the `output` section. Make sure this table name is set and you have write access to the database.


---

## Setting Up OSRM (Open Source Routing Machine)

This project uses OSRM to compute driving routes. To run the routing functionality correctly, you'll need to set up a local OSRM server using Docker.

> **Reference**: Official OSRM repository with full documentation and setup:
> [https://github.com/Project-OSRM/osrm-backend](https://github.com/Project-OSRM/osrm-backend)


### 1. Prerequisites

* **Docker Desktop**
  Download and install Docker from: [https://www.docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)
  Make sure Docker is running before continuing.

* **OpenStreetMap data**
  Download the region you're interested in from [Geofabrik](https://download.geofabrik.de/).
  Example (using mazowieckie voivodeship in Poland):

  ```bash
  wget https://download.geofabrik.de/europe/poland/mazowieckie-latest.osm.pbf
  ```

---

### 2. Preprocessing OSM Data

In the folder where your `.osm.pbf` file is located, run the following commands to preprocess the data using Docker (replace filenames accordingly):

```bash
# Extract routing data for car profile
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-extract -p /opt/car.lua /data/mazowieckie-latest.osm.pbf

# Partition the graph
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-partition /data/mazowieckie-latest.osrm

# Customize for efficient routing
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-customize /data/mazowieckie-latest.osrm
```

Once this completes successfully, your data is ready to use.

---

### 3. Running the OSRM Routing Server

To run the OSRM routing server (required for the Python routing scripts), do the following:

1. Ensure **Docker is running** in the background.
2. Open a terminal in the folder that contains your preprocessed `.osrm` files.
3. Start the OSRM routing engine with:

```bash
docker run -t -i -p 5000:5000 -v "${PWD}:/data" osrm/osrm-backend osrm-routed --algorithm mld /data/mazowieckie-latest.osrm
```

4. If successful, you should see a message like:

```
[info] Listening on: 0.0.0.0:5000
[info] running and waiting for requests
```

This means the local OSRM server is ready and listening on `http://localhost:5000`. You can now run the Python scripts that query routes using this server.


---

## Running the Program


Once the database and OSRM server are set up, you can run the main script for either partitioning (cutting) or merging areas.

### Partitioning (Cutting) Areas

The tool supports partitioning (cutting) areas into smaller polygons based on address distribution and OSM street network. This is useful for dividing large service areas into balanced, address-based regions.

**Requirements:**
- The database must contain polygon areas, address points, and OSM street geometries (see database section above).
- The config file must specify the relevant tables and columns under `data_for_partition`.
- A weights CSV file must be provided (or specified in the config) to control the cost of traversing different street types.

**Example usage:**

```bash
python main.py cut --area_id <AREA_ID> --min_addresses <MIN_ADDR> --weights_path <WEIGHTS_CSV>
```

- `<AREA_ID>`: ID prefix of the areas to cut
- `<MIN_ADDR>`: Minimum number of addresses per resulting piece
- `<WEIGHTS_CSV>`: Path to the weights CSV file (optional if set in config)

The partitioned (cut) results will be saved to the output table specified in your config file under the `data_for_partition` section.

See the `main.py` docstring and argument help for more details on available options.

---

### Merging Areas

The tool also supports merging areas based on address density and shortest route calculations. This is useful for aggregating small polygons into larger ones, e.g., for service area optimization.

**Requirements:**
- The database must contain address points with a time period column (see config example).
- The config file must specify the relevant tables and columns under `data_for_merge`.

**Example usage:**

```bash
python main.py merge --area_id <AREA_ID> --min_addresses <MIN_ADDR> --max_addresses <MAX_ADDR>
```

- `<AREA_ID>`: ID prefix of the areas to merge
- `<MIN_ADDR>`: Minimum number of addresses (daily average) required in a merged polygon
- `<MAX_ADDR>`: Maximum number of addresses (daily average) allowed in a merged polygon

The merged results will be saved to the output table specified in your config file under the `data_for_merge` section.

See the `main.py` docstring and argument help for more details on available options.
