# Methodology and variable dictionary

## Study area and assets

The centre is the explicitly chosen Turin reference coordinate 7.6869° E, 45.0703° N. Transform it to ETRS89 / LAEA Europe (EPSG:3035), then construct a square of side sqrt(1,400,000,000) m. The equal-area square provides a contiguous research window of known area. It is unrelated to a historical boundary and is not an operator territory. All lengths and overlay weights are calculated in this projected CRS.

Overpass queries nodes, ways and relations tagged `power=line`, `minor_line`, `substation`, or `transformer` in the bounding box. Full returned geometry is clipped to the exact research polygon. Assets are identified by immutable **OSM element identity**, `osm/type/id`; geometry and tags can change between OSM versions. Relations are polygonized from member outer/inner lines where possible. Unsupported geometry is excluded with a reason. Invalid geometry is repaired. Repeated identities are removed; distinct identities sharing geometry are flagged and retained, since parallel circuits may be legitimate. Node IDs and raw tags are retained but no network redundancy is inferred.

The Overpass spatial selector may miss an unusually long segment crossing the window with no mapped vertex inside its query bounding box; a regional extract is the recommended production acquisition route. Public mapping completeness cannot be measured without an independent asset register. Points and polygons may describe the same facility, so feature counts are not independent facility counts.

## Climate data and temporal support

Analysis is two complete UTC years, 2023 and 2024. The first end-to-end run used 2023 only, then 2024 was added. ERA5-Land temperature uses a 0.1° delivery grid. ERA5 precipitation and actual gust fields use 0.25°. Open-Meteo model selection is explicit (`era5_land`/`era5`), nearest-cell selection is requested, and `elevation=nan` disables statistical elevation downscaling. Returned centres and units are checked. We retain every native cell with positive-area intersection with the study window.

Hourly JSON is transformed into daily indices locally and saved as derived netCDF. UTC avoids daylight-saving ambiguity; all time steps are checked, including leap day. Each retained day requires 24 finite samples. No interpolation fills missing hours. A missing or unexpected value stops processing instead of silently reducing the denominator.

Open-Meteo precipitation is **already an hourly interval depth in mm**, labelled at the end of the preceding hour. Shift the timestamp back one hour before daily sums; retrieve the following January 1 so that December 31 closes. Do not difference these API values again.

Direct ERA5-Land CDS accumulated precipitation has a different convention: 00 UTC is the previous day's 24-hour depth, in m. For UTC daily totals select these 00 UTC values, assign to the preceding day, and multiply by 1,000. Summing the growing within-day ERA5-Land forecast accumulations would overcount. Direct CDS processing is not executed by this pipeline. Temperature from direct CDS would require K − 273.15; the executed API returns °C and is not converted a second time. See [ECMWF accumulation documentation](https://confluence.ecmwf.int/spaces/CKB/pages/462888259/ERA5+family+post-processed+daily+statistics+documentation).

## Variables

All exposure indicators increase with greater screened hazard; this does not establish a damage response.

| Variable | Definition | Unit / support | Missingness |
|---|---|---|---|
| heat | Count of UTC days with daily maximum hourly temperature >35°C | days/year, ERA5-Land cell | stop if incomplete year |
| heatwave_count | Number of maximal runs of >=3 heat days within each calendar year | events/year | incomplete years rejected |
| heatwave_days | Days belonging to those runs | days/year | as above |
| heatwave_max_days | Longest such run; 0 when none | days/year | as above |
| freeze_thaw_days | Count of Tmin <0°C and Tmax >0°C on the same UTC day | air-temperature proxy days/year | as above |
| rain | RX1day = maximum daily precipitation total within the year | mm, ERA5 cell | incomplete years rejected |
| rain_wetday_p95_mm | 95th percentile of same-year wet days >=1 mm | mm, annual descriptive threshold | NaN if no wet days |
| rain_above_annual_p95_mm | Sum on days above that year's wet-day p95 | mm/year; not standard baseline R95p | NaN if threshold unavailable |
| wind | Count of days with maximum hourly 10 m gust >20 m/s | days/year, ERA5 cell | incomplete years rejected |
| max_gust_ms | Annual maximum hourly gust | m/s, ERA5 cell | as above |
| hazard_mean / p90 / max | Spatially weighted mean, weighted empirical 90th percentile, maximum of mean annual cell indicators | original hazard units at asset geometry | NaN outside grid or missing data |
| hazard_coverage | Supported length or area / total asset length or area; point is 0 or 1 | fraction | zero indicates no coverage, not zero hazard |
| hazard_cells | Number of contributing native cells | count | zero when none |
| sensitivity / adaptive_capacity | Unobserved equipment sensitivity and operational capacity | unknown | always null; never zero |
| missing_voltage / missing_operator / missing_topology | Source-tag availability flags | Boolean; not a calibrated confidence score | available for each mapped asset |
| priority_equal | Mean of three normalised hazard exposure indicators | dimensionless screening index | propagates any missing indicator |
| stable_top_decile | Membership in every tested scenario's top-decile set, retaining ties | Boolean scenario stability | not failure probability |

1991–2020 temperature baseline results, when the retrieval completes, are documented in BASELINE_RESULTS.md. `heat_days_per_year` is the mean of the 30 annual fixed-threshold counts; `jja_tmax_p95_c` pools all June–August daily Tmax values at each native cell. It is not a calendar-day ETCCDI percentile. Reference percentiles supplement the fixed-threshold priority rather than changing a predeclared scoring definition after results are known.

## Spatial overlay

For line asset a and cell j, weight w(a,j) is the length of their intersection. Polygon weights are intersection area. The mean is sum(w h)/sum(w); weighted empirical p90 is the first sorted hazard value at cumulative weight >=90%; maximum is max(h) over positive-weight intersections. These three summaries are exported. Clipped asset geometry supplies the denominator. A line segment exactly on a shared cell boundary is assigned once, to the first cell sorted by cell ID, avoiding duplicate length. Boundary points likewise receive one deterministic containing cell. Points inherit cell-scale uncertainty of several km rather than exact-site weather. Cell coverage is explicitly tested.

For each cell and hazard, first average the annual metrics across complete analysis years, then overlay. A per-asset maximum therefore means the spatial maximum of these mean annual cell indicators, not a temporal event maximum. Separate annual maxima remain in climate_annual.csv. The conservative maximum-overlay scenario compares spatial summaries without claiming physical failure consequences.

## Exposure and priority formulations

Hazard-specific exposure E(a,h)=clip(Hmean(a,h)/R(h),0,1). Reference ranges R=(30 heat days/year, 100 mm RX1day, 10 gust days/year) are fixed analyst choices for transparent screening. They are not local damage thresholds or fitted failure rates. Raw physical indicators remain available and clipping can hide high-end differences; report clipping in the quality audit.

Composite priority P(a)=sum_h w(h)E(a,h)/sum_h w(h). Equal weights and 2:1:1 alternatives are predeclared. A weighted mean is appropriate for this explicitly compensatory screening convention; no multiplication of unknown risk components is attempted. Missing scores propagate. No expected loss or physical failure probability is estimated.

Leave-one-indicator-out scenarios expose dependence on a single hazard. Spearman rank correlation uses average ranks for ties. Top-decile membership uses score >= empirical p90 and retains ties; the selected set can be substantially larger than 10%. Jaccard similarity compares sets. Stable top decile is their intersection across all tested scenarios. Hypothetical line-sensitivity and line-adaptation scenarios multiply baseline priority by 1.25 or 0.75 on line/minor_line features. These stress-test unmeasured assumptions; they are not estimates, and the observed sensitivity/capacity fields stay null.

## Validation and limits

The tests use hand-calculable line and polygon overlaps, missing-hour and precipitation-day boundaries, leap day, run lengths, CRS area and API behaviors. ARPA's independent regional report supplies an extreme-date plausibility check, not a complete station validation. No matched outage labels have been acquired: **no failure-outcome validation**. QGIS tool connectivity failed during this session, so there is no claim of QGIS-rendered inspection. The GeoPackage and GeoTIFFs remain directly inspectable in QGIS.
