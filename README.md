# Turin grid climate exposure

A 2023–2024 pilot comparing heat, rainfall and gust exposure for 512 publicly mapped power features in a 1,400 km² window around Turin. The highest-priority groups under equal weights and without rainfall had no members in common. The scores are relative exposure indicators. Outage observations, infrastructure condition and network redundancy were unavailable.

[Portfolio case study](https://www.daudee.com/work/turin-grid-climate)

## Run

Use Python 3.12 in a clean virtual environment. Full pipeline runs may need the original source snapshots or a new acquisition from the documented providers.

```sh
python -m pip install -r requirements-lock.txt
python scripts/pipeline.py
python scripts/baseline.py
python scripts/quality_audit.py
python -m pytest -q
```

## Data and attribution

ERA5 and ERA5-Land via Open-Meteo. Power features from © OpenStreetMap contributors ([ODbL and attribution](https://www.openstreetmap.org/copyright)). Raw provider responses and individual feature rankings live with the original run.
