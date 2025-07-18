# Praktyki Project

This project is a Python-based geospatial data processing toolkit. It leverages GeoPandas and NumPy to analyze, filter, and process spatial data, particularly for urban infrastructure such as streets, addresses, and boundaries.

## Project Structure

- `main.py` — Entry point for running the project.
- `src/` — Source code modules:
  - `config.py` — Configuration settings.
  - `cuts.py` — Functions for processing and filtering geospatial data.
  - `intersections.py` — Functions for finding and analyzing intersections.
- `sample_input_data/` — Sample datasets for testing or demonstration.


## Installation

This project requires Python 3. You can install all necessary dependencies using the provided `requirements.txt` file:


```bash
python -m venv .venv
.venv\Scripts\activate      # On Windows
source .venv/bin/activate  # On Linux/macOS

pip install -r requirements.txt
````

Before running the routing scripts, make sure you have a local OSRM server running. See the next section for detailed instructions.

````markdown
## Installation

This project requires Python 3. You can install all necessary dependencies using the provided `requirements.txt` file:

```bash
python -m venv .venv
.venv\Scripts\activate      # On Windows
source .venv/bin/activate  # On Linux/macOS

pip install -r requirements.txt
````

Before running the routing scripts, make sure you have a local OSRM server running. See the next section for detailed setup instructions.

### Running the Program

To test the program on the provided example files in the `sample_data` directory, you will need to download OpenStreetMap data for the Mazowieckie voivodeship in Poland.

You can get it from [Geofabrik's download site](https://download.geofabrik.de/europe/poland.html), e.g.:

```bash
wget https://download.geofabrik.de/europe/poland/mazowieckie-latest.osm.pbf
```

Then follow the instructions in the next section to set up OSRM with this file.


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
