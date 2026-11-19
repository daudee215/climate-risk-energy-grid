# Assumptions and limitations

This is new exploratory research. No old location, operator, source register or 2025 result is established. Provenance dates remain in machine metadata and reproducibility records; the user requested no computation-date stamps on diagrams or tables.

| Limitation | Evidence / scope | Likely effect on ranking | Handling |
|---|---|---|---|
| Incomplete OSM grid | No independent asset register | Underrepresents less mapped areas; segmentation changes feature counts | Describe mapped features and lengths; never claim complete operational network |
| Missing voltage/operator | Counts in results/summary.json and data_quality_by_type.csv | Tag-based sensitivity assumptions could bias well-mapped areas | Retain missing flags; no voltage-derived failure score |
| Unknown age, condition, loading | Not in acquired source data | True vulnerability may reverse an exposure ordering | Null sensitivity/capacity; explicit hypothetical stress scenarios only |
| Unknown redundancy | OSM nodes do not establish switch state or operational connectivity | Centrality could be spurious | Omit operational topology and resilience score |
| Coarse ERA5 rainfall/gust | Six 0.25° cells intersect the window | Many tied assets; convective and topographic peaks smoothed | Native grids, weighted summaries, no fine raster interpolation |
| ERA5-Land temperature support | Twenty-two 0.1° intersecting cells | Cannot rank colocated substations by microclimate | Show cells; nearest-cell support uncertainty |
| Short analysis period | Two complete years | Weather variability may dominate long-term priorities | Separate 1991–2020 temperature reference; no inferred climate trend |
| Fixed screening ranges/weights | Analyst-defined constants in config.yaml | Relative contributions and clipping affect ordering | Raw indicators, alternatives, leave-one-out and maximum overlay |
| Gust threshold may be uninformative | All acquired 2023–2024 cells have zero days >20 m/s | Wind contributes a constant zero to baseline ranking | Report this explicitly; do not interpret as no wind risk |
| Point/polygon duplication and mapping density | Multiple OSM objects can describe one facility | Feature-count denominators differ from physical-facility counts | Preserve IDs and geometry type; audit by type and geography |
| Boundary cuts circuits | Analyst-defined square | Excludes external connections and dependencies | No service area or network-wide redundancy claim |
| Bounding-box node selector | Overpass chooses based on mapped nodes | Could miss a crossing segment with no vertex inside bbox | Disclose; regional extract recommended for production |
| Provider-delivery substitution | Open-Meteo API instead of raw CDS | Rounding or provider processing may differ from raw source | Explicit model/cell/elevation settings; cache responses and hashes |
| Population context omitted | GHSL/ISTAT exist but no justified service allocation | No prioritisation by affected customers can be supported | No customers-served or demographic vulnerability score |
| No outage/damage labels | No appropriately licensed matched dataset obtained | No empirical failure calibration or predictive validation | Screening-only framing |
| Independent check has regional support | ARPA report vs local reanalysis cells | Matching a date cannot establish local temperature accuracy | Call it event plausibility only |
| QGIS unavailable through configured tool | get_project_info returned an execution error | Native QGIS inspection unverified | GIS files retained; open manually in QGIS |

Unknown does not mean safe. A zero threshold exceedance is not a zero failure probability. Scenario stability is not statistical certainty.
