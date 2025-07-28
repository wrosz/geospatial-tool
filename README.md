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

### Set Up Docker and OSRM

1. Install Docker Desktop.
2. In the directory with your `.osm.pbf` file, run:

```bash
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-extract -p /opt/car.lua /data/mazowieckie-latest.osm.pbf
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-partition /data/mazowieckie-latest.osrm
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-customize /data/mazowieckie-latest.osrm
```

To start the server:

```bash
docker run -t -i -p 5000:5000 -v "${PWD}:/data" osrm/osrm-backend osrm-routed --algorithm mld /data/mazowieckie-latest.osrm
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

#### Areas Table

* Must include:

  * `id`: unique area identifiers
  * `geom`: geometry column (Polygon)

#### Addresses Table

* Must include:

  * `geom`: Point geometries
* Optional:

  * `timestamp`: for time-based filtering
  * `teryt`: administrative ID for optional filtering

#### OSM Geometry Table

* Must include:

  * `geom`: LineString or MultiLineString geometries
  * OSM attributes (e.g., `highway`, `waterway`, etc.)

---

## Configuration File (`db_config.json`)

See `sample_db_config.json` for structure. Key sections include:

### Database Connection

```json
"connection": {
  "host": "localhost",
  "port": 5432,
  "name": "your_database",
  "user": "your_user",
  "password": "your_password"
}
```

### Weights

```json
"weights": {
  "default_weights_path": "path/to/default_weights.csv"
}
```

CSV must have columns: `osm_key`, `osm_value`, `weight`

### Data for `cut` and `merge`

Defined under `data_for_partition` and `data_for_merge`. Each includes configuration for:

* `addresses`: table, geometry column, optional filters (e.g., `teryt`, `timestamp`)
* `areas`: table, geometry and ID columns
* `osm_data`: OSM geometry table and CRS
* `output`: table name and CRS for storing results

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
* `--avg`: Use average address count over time period
* `--teryt_id <id>`: Filter addresses by administrative ID
* `--output_table <name>`: Override default output table
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
Partitioned polygon 146201_1.0010 into 10 parts.
Saved result to table cut_results_146.
```

### Merge

```
Merged 242 polygons into 44 aggregated regions.
Saved result to table merge_results_123.
```

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
