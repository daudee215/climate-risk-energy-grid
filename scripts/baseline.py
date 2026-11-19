"""Retrieve and inspect 1991–2020 ERA5-Land daily Tmax reference data.

API-delivered daily aggregates are kept distinct from locally aggregated pilot hours.
No ETCCDI calendar-day percentile claim is made.
"""
import json
import time
import numpy as np
import pandas as pd
from pipeline import ROOT,CONFIG,STAMP,MANIFEST,study_area,grid,cached_json,record


def main():
    rows=[]
    cells=grid(study_area(),.1,'era5_land')
    for cell in cells.itertuples():
        path=ROOT/f'data/raw/baseline_{cell.cell_id}_1991_2020.json'
        cached=path.exists()
        params=dict(latitude=cell.lat,longitude=cell.lon,start_date='1991-01-01',end_date='2020-12-31',
            models='era5_land',daily='temperature_2m_max',timezone='GMT',elevation='nan',cell_selection='nearest')
        payload,url=cached_json(path,'https://archive-api.open-meteo.com/v1/archive',params=params)
        assert abs(payload['latitude']-cell.lat)<.002 and abs(payload['longitude']-cell.lon)<.002
        assert payload['daily_units']['temperature_2m_max']=='°C'
        daily=pd.Series(payload['daily']['temperature_2m_max'],index=pd.to_datetime(payload['daily']['time']),dtype=float)
        assert daily.index.equals(pd.date_range('1991-01-01','2020-12-31'))
        assert daily.notna().all()
        hot=(daily>CONFIG['heat_threshold_c']).groupby(daily.index.year).sum()
        summer=daily[daily.index.month.isin([6,7,8])]
        rows.append(dict(cell_id=cell.cell_id,baseline='1991-2020',n_days=len(daily),
            heat_days_per_year=float(hot.mean()),jja_tmax_p95_c=float(summer.quantile(.95))))
        record(path,url,'ERA5-Land via Open-Meteo daily reference', 'daily Tmax', 'degree Celsius',
            '1991-01-01/2020-12-31 UTC','EPSG:4326; native 0.1 degree',
            'CC BY 4.0; non-commercial API terms','Open-Meteo; Copernicus C3S/ECMWF')
        print(f'Baseline {cell.cell_id}: {len(daily)} complete days; {hot.mean():.2f} heat days/year',flush=True)
        if not cached:
            time.sleep(12)  # Long-period calls are weighted; keep these requests well spaced.
    baseline=pd.DataFrame(rows)
    baseline.to_csv(ROOT/'results/heat_baseline_1991_2020.csv',index=False)
    annual=pd.read_csv(ROOT/'results/climate_annual.csv')
    compare=annual[annual.model.eq('era5_land')].merge(baseline,on='cell_id',validate='many_to_one')
    compare['heat_days_anomaly']=compare.heat-compare.heat_days_per_year
    compare.to_csv(ROOT/'results/heat_baseline_comparison.csv',index=False)
    pilot=pd.read_csv(ROOT/'data/processed/daily_climate.csv',parse_dates=['date'])
    pilot=pilot[pilot.cell_id.isin(baseline.cell_id)].merge(baseline[['cell_id','jja_tmax_p95_c']],on='cell_id')
    jja=pilot[pilot.date.dt.month.isin([6,7,8])].copy()
    jja['exceed']=jja.tmax_c>jja.jja_tmax_p95_c
    jja.groupby(['cell_id','year']).agg(jja_days=('exceed','size'),jja_days_above_reference_p95=('exceed','sum')).reset_index().to_csv(ROOT/'results/jja_reference_exceedances.csv',index=False)
    existing=pd.read_csv(ROOT/'data_sources.csv')
    combined=pd.concat([existing[~existing.dataset_identifier.str.contains('daily reference')],pd.DataFrame(MANIFEST)],ignore_index=True)
    combined.to_csv(ROOT/'data_sources.csv',index=False)
    (ROOT/'BASELINE_RESULTS.md').write_text(f'''# 1991–2020 temperature reference

{STAMP}. Baseline retrieved for all {len(baseline)} intersecting native ERA5-Land cells: {int(baseline.n_days.sum())} cell-days, {baseline.n_days.iloc[0]} complete UTC days per cell, no missing daily Tmax.

Baseline annual mean days with Tmax >35°C range {baseline.heat_days_per_year.min():.2f}–{baseline.heat_days_per_year.max():.2f}. The June–August pooled 95th percentile of daily Tmax ranges {baseline.jja_tmax_p95_c.min():.2f}–{baseline.jja_tmax_p95_c.max():.2f}°C. The percentile pools all 2,760 JJA days per cell over 30 years; it is not an ETCCDI calendar-day percentile. No baseline uncertainty interval is inferred.

The pilot's {CONFIG['years']} per-cell fixed-threshold anomalies relative to this baseline are retained in results/heat_baseline_comparison.csv. Independent retrieval of daily aggregates versus hourly pilot values is a provider-delivery consistency assumption; these are not independent climate products. JJA exceedances are in results/jja_reference_exceedances.csv. These comparisons supplement, and do not replace, the predeclared fixed-threshold asset scores. Rainfall and gust long-term baselines are not yet retrieved.

Raw daily reference responses and their hashes are in data/raw and data_sources.csv. Regenerate with `.venv/Scripts/python scripts/baseline.py` after the main pipeline. A main pipeline rerun rebuilds the core manifest; rerun this script afterwards to re-append baseline lineage.
''',encoding='utf-8')


if __name__=='__main__':
    main()
