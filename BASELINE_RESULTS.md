# 1991–2020 temperature reference

reconstructed, computed on 2026-10-28. Baseline retrieved for all 22 intersecting native ERA5-Land cells: 241076 cell-days, 10958 complete UTC days per cell, no missing daily Tmax.

Baseline annual mean days with Tmax >35°C range 0.00–1.37. The June–August pooled 95th percentile of daily Tmax ranges 26.20–33.60°C. The percentile pools all 2,760 JJA days per cell over 30 years; it is not an ETCCDI calendar-day percentile. No baseline uncertainty interval is inferred.

The fixed-threshold anomalies for 2023 and 2024 are written to `results/heat_baseline_comparison.csv`. Summer percentile exceedances are written to `results/jja_reference_exceedances.csv`. Both CSVs are local outputs. The comparison assumes consistency between the provider's daily aggregates and the pilot's hourly values. The published [scenario sensitivity table](results/sensitivity.csv) covers the predeclared asset scores. Long-term rainfall and gust baselines remain uncomputed.

Run `python scripts/pipeline.py` followed by `python scripts/baseline.py` in the project environment to regenerate the baseline outputs. Provider responses are cached in `data/raw/` and their hashes recorded in `data_sources.csv`. These are local run artifacts. Rerun the baseline after rebuilding the main pipeline so the manifest records both acquisitions.
