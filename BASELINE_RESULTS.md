# 1991–2020 temperature reference

reconstructed, computed on 2026-10-28. Baseline retrieved for all 22 intersecting native ERA5-Land cells: 241076 cell-days, 10958 complete UTC days per cell, no missing daily Tmax.

Baseline annual mean days with Tmax >35°C range 0.00–1.37. The June–August pooled 95th percentile of daily Tmax ranges 26.20–33.60°C. The percentile pools all 2,760 JJA days per cell over 30 years; it is not an ETCCDI calendar-day percentile. No baseline uncertainty interval is inferred.

The pilot's [2023, 2024] per-cell fixed-threshold anomalies relative to this baseline are retained in results/heat_baseline_comparison.csv. Independent retrieval of daily aggregates versus hourly pilot values is a provider-delivery consistency assumption; these are not independent climate products. JJA exceedances are in results/jja_reference_exceedances.csv. These comparisons supplement, and do not replace, the predeclared fixed-threshold asset scores. Rainfall and gust long-term baselines are not yet retrieved.

Raw daily reference responses and their hashes are in data/raw and data_sources.csv. Regenerate with `.venv/Scripts/python scripts/baseline.py` after the main pipeline. A main pipeline rerun rebuilds the core manifest; rerun this script afterwards to re-append baseline lineage.
