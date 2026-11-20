# Turin grid climate exposure

A 2023–2024 pilot comparing heat, rainfall and gust exposure for 512 publicly mapped power features in a 1,400 km² window around Turin. The highest-priority groups under equal weights and without rainfall had no members in common. The scores are relative exposure indicators. Outage observations, infrastructure condition and network redundancy were unavailable.

[Portfolio case study](https://www.daudee.com/work/turin-grid-climate)

## Inspect the published results

- [Scenario sensitivity](results/sensitivity.csv) compares exposure rankings under different hazard weights.
- [Temperature baseline notes](BASELINE_RESULTS.md) explain the 1991–2020 reference and the figures derived from it.
- [Figures](figures/) show the mapped exposure and sensitivity results.

## Run

Use Python 3.12 in a clean virtual environment. The main pipeline reacquires weather and OSM data, and the baseline step retrieves the longer temperature reference. The exact historical run depends on the original provider responses and feature geometry. See [methodology](METHODOLOGY.md) for source and scoring details.

```sh
python -m pip install -r requirements-lock.txt
python scripts/pipeline.py
python scripts/baseline.py
python scripts/quality_audit.py
python -m pytest -q
```

## Data and attribution

ERA5 and ERA5-Land via Open-Meteo. Power features from © OpenStreetMap contributors ([ODbL and attribution](https://www.openstreetmap.org/copyright)). Raw provider responses and individual feature rankings live with the original run.
