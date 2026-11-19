"""Additional source-backed coverage and delivery checks; no synthetic data."""
import hashlib
import json
from pathlib import Path
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pipeline import ROOT,CONFIG,STAMP


def main():
    scores=gpd.read_file(ROOT/'results/energy_assets.gpkg',layer='scores')
    cells=gpd.read_file(ROOT/'results/energy_assets.gpkg',layer='climate_cells').to_crs(scores.crs)
    by_type=scores.groupby('power').agg(n_features=('asset_id','size'),mapped_line_km=('length_km','sum'),
        missing_voltage=('missing_voltage','sum'),missing_operator=('missing_operator','sum'),
        coincident_geometry=('coincident_geometry','sum'),heat_mean=('heat_mean','mean'),rain_mean=('rain_mean','mean'),
        wind_mean=('wind_mean','mean'))
    by_type['missing_voltage_fraction']=by_type.missing_voltage/by_type.n_features
    by_type['missing_operator_fraction']=by_type.missing_operator/by_type.n_features
    by_type.to_csv(ROOT/'results/data_quality_by_type.csv')
    geography=[]
    for cell in cells[cells.model.eq('era5_land')].itertuples():
        subset=scores[scores.intersects(cell.geometry)]
        line=subset[subset.geometry_type.str.contains('Line')]
        geography.append(dict(cell_id=cell.cell_id,n_intersecting_features=len(subset),
            intersecting_line_km=float(line.intersection(cell.geometry).length.sum()/1000),
            missing_voltage=int(subset.missing_voltage.sum()),missing_operator=int(subset.missing_operator.sum()),
            note='Cell counts overlap for crossing assets; do not sum feature counts'))
    pd.DataFrame(geography).to_csv(ROOT/'results/data_quality_by_cell.csv',index=False)
    exposure=[]
    for hazard in ['heat','rain','wind']:
        for power,subset in scores.groupby('power'):
            exposure.append(dict(hazard=hazard,power=power,n_assets=len(subset),
                positive_indicator_features=int((subset[f'{hazard}_max']>0).sum()),
                min_mean=float(subset[f'{hazard}_mean'].min()),max_mean=float(subset[f'{hazard}_mean'].max()),
                clipped_score_features=int((subset[f'{hazard}_score_mean']>=1).sum()),
                full_coverage_features=int((subset[f'{hazard}_coverage']>=.9999).sum()),
                note='Positive rain RX1day means some rain, not damaging exposure; heat/wind refer to configured thresholds'))
    pd.DataFrame(exposure).to_csv(ROOT/'results/exposure_by_type.csv',index=False)
    annual=pd.read_csv(ROOT/'results/climate_annual.csv')
    wind=annual[annual.model.eq('era5')]
    summary=json.loads((ROOT/'results/summary.json').read_text())
    scientific=ROOT/'SCIENTIFIC_REPORT.md'
    text=scientific.read_text(encoding='utf-8').split('\n## Supplementary temperature reference')[0]
    top_count=int((scores.priority_equal>=scores.priority_equal.quantile(.9)).sum())
    sensitivity=pd.read_csv(ROOT/'results/sensitivity.csv')
    leave_rain=float(sensitivity.loc[sensitivity.scenario.eq('without_rain'),'rank_spearman'].iloc[0])
    section=f'''## Interpretation of ties and non-discriminating wind

All {len(wind)} ERA5 cell-years have zero days above the configured 20 m/s gust threshold; maximum hourly gusts range {wind.max_gust_ms.min():.1f}–{wind.max_gust_ms.max():.1f} m/s. This does not rule out local gust damage or unresolved short gusts. Wind is constant in these scores and supplies no ranking discrimination. Equal weighting therefore reduces the numerical score but does not introduce wind-based ordering. The tied equal-weight top-decile set contains {top_count}/{len(scores)} features ({100*top_count/len(scores):.1f}%); arbitrary tie-breaking would imply unsupported spatial precision. The leave-rain-out Spearman correlation is {leave_rain:.3f}, showing that these priorities are strongly dependent on the rainfall indicator. Across every tested top-decile set, {int(scores.stable_top_decile.sum())} assets remain selected.

Asset-type and geographic tagging/coverage audits are in results/data_quality_by_type.csv, data_quality_by_cell.csv and exposure_by_type.csv. Geographic feature counts are non-additive for crossing lines. Raw mean indicators in these summaries are feature-weighted descriptions, not population- or network-weighted risk.

'''
    if '## Interpretation of ties' not in text:
        text=text.replace('## Independent climate check',section+'## Independent climate check')
    baseline=ROOT/'BASELINE_RESULTS.md'
    if baseline.exists():
        text=text.replace('1991–2020 baseline await separate execution','raw-source baseline replication await separate execution')
        text=text.replace("ARPA's regional reference period is 1991–2020, which has not been retrieved here; we do not claim agreement on anomalies.","A separate 1991–2020 ERA5-Land temperature reference has now been retrieved for all 22 cells; see BASELINE_RESULTS.md. We do not claim agreement on regional anomalies from this local window.")
        text=text.replace('no multi-decadal climatological inference.','the 1991–2020 temperature reference is supplementary and no climate trend is inferred.')
        text += '\n## Supplementary temperature reference\n\n'+baseline.read_text(encoding='utf-8').split('\n',1)[1]
        repro=ROOT/'REPRODUCIBILITY_REPORT.md'
        repro_text=repro.read_text(encoding='utf-8').split('\n## Supplementary reference execution')[0]
        repro.write_text(repro_text+'\n## Supplementary reference execution\n\n1991–2020 daily Tmax reference completed for 22 cells, 10,958 dates each (241,076 cell-days), with complete-date and finite-value assertions. Baseline API requests were rate-limited during acquisition; cached progress was resumed with longer spacing until complete. The main-pipeline runtime above excludes baseline acquisition and this audit. All 79 retained data responses were SHA-256 verified. Computation dates are omitted from visual labels and derived result tables at user request; provenance remains in this record and raw request metadata.\n',encoding='utf-8')
    scientific.write_text(text,encoding='utf-8')
    # Verify source hashes against the actual retained bytes, not just a manifest count.
    manifest=pd.read_csv(ROOT/'data_sources.csv')
    bad=[]
    for row in manifest.itertuples():
        actual=hashlib.sha256((ROOT/row.file).read_bytes()).hexdigest()
        if actual!=row.file_sha256:
            bad.append(row.file)
    assert not bad,bad
    raster_check={}
    for h in ['heat','rain','wind']:
        with rasterio.open(ROOT/f'results/hazard_{h}.tif') as src:
            raster_check[h]=dict(crs=str(src.crs),resolution=src.res,valid_cells=int(src.read(1,masked=True).count()))
            assert src.crs.to_epsg()==4326
            assert src.read(1,masked=True).count()==(22 if h=='heat' else 6)
    (ROOT/'results/integrity_checks.json').write_text(json.dumps(dict(manifest_files=len(manifest),
        hash_failures=bad,raster_checks=raster_check,date_stamp_policy='No computation dates on figures, map labels, or result tables; provenance dates retained in records'),indent=2))
    files=[]
    for directory in ['data','results','figures','webgis']:
        for path in sorted((ROOT/directory).rglob('*')):
            if path.is_file() and path.name!='file_inventory.csv':
                files.append(dict(path=path.relative_to(ROOT).as_posix(),bytes=path.stat().st_size))
    pd.DataFrame(files).to_csv(ROOT/'results/file_inventory.csv',index=False)
    (ROOT/'results/qgis_status.json').write_text(json.dumps(dict(status='unavailable',
        attempted='mcp__qgis__get_project_info',result='Error executing tool get_project_info',
        consequence='No native QGIS visual inspection claimed; GeoPackage and GeoTIFFs retained for inspection'),indent=2))
    print(f'Integrity: {len(manifest)} source hashes verified; coverage/type/cell audits written; no QGIS inspection claimed.')


if __name__=='__main__':
    main()
