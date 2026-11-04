# Third-party notices

## Software

Argus does not bundle third-party code. The packages below are installed separately as its dependencies and remain
under their own licenses.

| Package | License |
|---|---|
| [httpx](https://github.com/encode/httpx) | BSD-3-Clause |
| [httpcore](https://github.com/encode/httpcore) | BSD-3-Clause |
| [h11](https://github.com/python-hyper/h11) | MIT |
| [anyio](https://github.com/agronholm/anyio) | MIT |
| [idna](https://github.com/kjd/idna) | BSD-3-Clause |
| [certifi](https://github.com/certifi/python-certifi) | MPL-2.0 |
| [DuckDB](https://github.com/duckdb/duckdb) (Python package) | MIT |

[FFmpeg](https://ffmpeg.org/) is used as an external command-line tool for cutting video and extracting frames. It is
not distributed with Argus; its license depends on how it was built.

## Fonts

The console is set in [Inter](https://github.com/rsms/inter) 4.1 (Copyright 2016 The Inter Project Authors) and
[JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) 2.304 (Copyright 2020 The JetBrains Mono Project Authors),
both under the [SIL Open Font License 1.1](https://openfontlicense.org). They are not included in this repository;
`argus/console/get_fonts.sh` fetches them with their licences; without them the console uses the system fonts.

## Services

Argus calls the following services under their providers' terms. Neither license of Argus covers them:
the Meta Model API (Muse Spark, Muse Wonder, SAM 3.1, Muse Voice Transcribe), Muse Spark Open served by Baseten, and
Metantel's Managed Memory Harness.

## Datasets

The datasets are not included in this repository. The scripts in `examples/` download them from their publishers. The
results in `docs/` are derived from them as described below.

**Nationwide Automatic Identification System 2024.** NOAA Office for Coastal Management, MarineCadastre.gov, from U.S.
Coast Guard data. Public domain (CC0 1.0). Used: vessel positions within the Houston Ship Channel and Galveston Bay
area, compiled into hourly traffic, vessel events and slowdowns.

**ASOS observations and Terminal Aerodrome Forecasts.** U.S. National Weather Service data from the Iowa Environmental
Mesonet archive, Iowa State University (https://mesonet.agron.iastate.edu/). Used: hourly visibility at Galveston (GLS)
and Baytown (HPY), and the airport forecasts for Galveston (KGLS).

**MetroPT-3 Dataset.** Davari, N., Veloso, B., Ribeiro, R. P., Gama, J. UCI Machine Learning Repository, 2023.
https://doi.org/10.24432/C5VW3R. Licensed under the Creative Commons Attribution 4.0 International License
(https://creativecommons.org/licenses/by/4.0/). Changes made: compiled into five-minute and daily health measures and
abnormal episodes.

**PhysicalAI-SmartSpaces (MTMC_Tracking_2025).** NVIDIA Corporation.
https://huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces. Licensed under the Creative Commons Attribution 4.0
International License (https://creativecommons.org/licenses/by/4.0/). Changes made: four scenes (Warehouse_000,
Warehouse_010, Warehouse_015, Warehouse_016) shown as the four halls of one site on one clock; videos sampled at two
frames a second and 960×540 pixels; people, vehicles and humanoid robots detected with SAM 3.1 and projected onto the
floor plan; in two scenes the 3D ground truth stands in for location tags (twice a second, for every vehicle, and in
one scene for 70% of the people), elsewhere it is used only to score results; floor plans and videos shown with overlays
in the console.
