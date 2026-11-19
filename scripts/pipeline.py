"""Open-data screening reconstruction. Run from the repository root.

No credentials required for the non-commercial Open-Meteo delivery route.
Raw provider JSON is cached and hashed; reruns use the same downloaded bytes.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
try:
    from .figure_style import COLORS, INK, SEQUENTIAL
except ImportError:
    from figure_style import COLORS, INK, SEQUENTIAL
import numpy as np
import pandas as pd
import psutil
import rasterio
import requests
import xarray as xr
import yaml
from pyproj import Transformer
from rasterio.transform import from_origin
from scipy.stats import spearmanr
from shapely import make_valid
from shapely.geometry import Point, LineString, Polygon, box
from shapely.ops import polygonize, unary_union

ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / 'config.yaml').read_text())
DATE = datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Europe/Berlin')).date().isoformat()
STAMP = f'reconstructed, computed on {DATE}'
MANIFEST = []
SESSION = requests.Session()
SESSION.headers['User-Agent'] = 'TurinEnergyClimateReconstruction/0.1 (personal reproducible research)'
HAZARDS = ['heat', 'rain', 'wind']


def directories():
    for folder in ['data/raw', 'data/processed', 'results', 'figures', 'webgis', 'api', 'tests', 'notebooks']:
        (ROOT / folder).mkdir(parents=True, exist_ok=True)


def record(path, url, dataset, variable, units, coverage, resolution, licence, attribution, version='provider version not pinned'):
    MANIFEST.append(dict(url=url, dataset_identifier=dataset, variable=variable, units=units,
        temporal_coverage=coverage, crs_resolution=resolution, access_date=DATE,
        release_version=version, licence=licence, attribution=attribution,
        file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        file=str(path.relative_to(ROOT)), intended_use='exploratory infrastructure screening'))


def cached_json(path, url, *, params=None, data=None):
    meta = path.with_suffix('.request.json')
    if path.exists():
        saved = json.loads(meta.read_text())
        if saved.get('params') != params or saved.get('post') != data:
            raise ValueError(f'Cache request differs: archive {path.name} and its request metadata before refreshing')
        return json.loads(path.read_text(encoding='utf-8')), saved['url']
    last = None
    for attempt in range(3):
        try:
            response = SESSION.post(url, data=data, timeout=140) if data else SESSION.get(url, params=params, timeout=100)
            if response.status_code in (429, 502, 503, 504):
                raise RuntimeError(f'transient HTTP {response.status_code}')
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and (payload.get('error') or payload.get('remark')):
                raise RuntimeError(str(payload)[:500])
            path.write_bytes(response.content)
            meta.write_text(json.dumps(dict(url=response.url, params=params, post=data,
                retrieved_utc=datetime.now(timezone.utc).isoformat()), indent=2), encoding='utf-8')
            return payload, response.url
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'Could not retrieve {url}: {last}')


def study_area():
    conf = CONFIG['study_area']
    x, y = Transformer.from_crs(4326, conf['crs'], always_xy=True).transform(conf['centre_lon'], conf['centre_lat'])
    half = math.sqrt(conf['area_km2'] * 1e6) / 2
    study = gpd.GeoDataFrame([dict(name='Turin equal-area research window', provenance='Analyst-defined square; not an administrative or historical boundary')], geometry=[box(x-half, y-half, x+half, y+half)], crs=conf['crs'])
    study['area_km2'] = study.area / 1e6
    study.to_file(ROOT / 'data/processed/study_area.geojson', driver='GeoJSON')
    return study


def relation_geometry(element):
    outer, inner = [], []
    for member in element.get('members', []):
        coords = [(p['lon'], p['lat']) for p in member.get('geometry', []) if 'lon' in p]
        if len(coords) >= 2:
            (inner if member.get('role') == 'inner' else outer).append(LineString(coords))
    shells = list(polygonize(unary_union(outer))) if outer else []
    holes = list(polygonize(unary_union(inner))) if inner else []
    return unary_union(shells).difference(unary_union(holes)) if shells else None


def get_assets(study):
    west, south, east, north = study.to_crs(4326).total_bounds
    bbox = f'{south},{west},{north},{east}'
    query = f'[out:json][timeout:100];nwr[power~"^(line|minor_line|substation|transformer)$"]({bbox});out meta geom;'
    path = ROOT / 'data/raw/osm_power.json'
    last = None
    for endpoint in ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter']:
        try:
            payload, url = cached_json(path, endpoint, data={'data': query})
            break
        except RuntimeError as exc:
            last = exc
    else:
        raise last
    record(path, url, 'OpenStreetMap Overpass power nwr', 'power;voltage;operator;nodes', 'geometry and tags',
        payload.get('osm3s', {}).get('timestamp_osm_base', 'unknown'), 'EPSG:4326; volunteer mapped features',
        'ODbL 1.0', 'OpenStreetMap contributors', payload.get('generator', 'unknown'))
    rows, excluded = [], []
    seen = set()
    for el in payload['elements']:
        uid = f"osm/{el['type']}/{el['id']}"
        if uid in seen:
            continue
        seen.add(uid)
        tags = el.get('tags', {})
        if el['type'] == 'node':
            geom = Point(el['lon'], el['lat'])
        elif el['type'] == 'relation':
            geom = relation_geometry(el)
        else:
            coords = [(p['lon'], p['lat']) for p in el.get('geometry', []) if 'lon' in p]
            if len(coords) < 2:
                geom = None
            elif coords[0] == coords[-1] and tags.get('power') in ['substation', 'transformer']:
                geom = Polygon(coords)
            else:
                geom = LineString(coords)
        if geom is None or geom.is_empty:
            excluded.append(dict(asset_id=uid, reason='missing or unsupported geometry'))
            continue
        rows.append(dict(asset_id=uid, power=tags.get('power'), name=tags.get('name'),
            voltage=tags.get('voltage'), operator=tags.get('operator'),
            circuits=tags.get('circuits'), cables=tags.get('cables'),
            node_ids=json.dumps(el.get('nodes', [])), osm_version=el.get('version'),
            osm_timestamp=el.get('timestamp'), tags_json=json.dumps(tags, ensure_ascii=False),
            repaired=not geom.is_valid, geometry=make_valid(geom)))
    if not rows:
        raise RuntimeError('No OSM assets; do not fabricate replacements')
    assets = gpd.GeoDataFrame(rows, crs=4326).to_crs(study.crs)
    boundary = study.geometry.iloc[0]
    assets['geometry'] = assets.geometry.intersection(boundary)
    assets = assets[~assets.is_empty].copy().reset_index(drop=True)
    assets['geometry_type'] = assets.geom_type
    assets['length_km'] = np.where(assets.geom_type.str.contains('Line'), assets.length/1000, np.nan)
    assets['area_m2'] = np.where(assets.geom_type.str.contains('Polygon'), assets.area, np.nan)
    assets['missing_voltage'] = assets.voltage.isna()
    assets['missing_operator'] = assets.operator.isna()
    assets['missing_topology'] = assets.node_ids.eq('[]')
    assets['sensitivity'] = np.nan
    assets['adaptive_capacity'] = np.nan
    # Same geometries with different OSM identities may be legitimate parallel circuits.
    assets['coincident_geometry'] = assets.geometry.to_wkb().duplicated(keep=False)
    pd.DataFrame(excluded, columns=['asset_id','reason']).to_csv(ROOT/'results/excluded_assets.csv', index=False)
    return assets


def grid(study, step, model):
    w, s, e, n = study.to_crs(4326).total_bounds
    rows = []
    for ilat in range(math.floor(s/step)-1, math.ceil(n/step)+2):
        for ilon in range(math.floor(w/step)-1, math.ceil(e/step)+2):
            lon, lat = round(ilon*step, 5), round(ilat*step, 5)
            shape = box(lon-step/2, lat-step/2, lon+step/2, lat+step/2)
            metric = gpd.GeoSeries([shape], crs=4326).to_crs(study.crs).iloc[0]
            if metric.intersection(study.geometry.iloc[0]).area > 0:
                rows.append(dict(cell_id=f'{model}_{lat:.2f}_{lon:.2f}', lon=lon, lat=lat, model=model, step=step, geometry=shape))
    return gpd.GeoDataFrame(rows, crs=4326)


def heatwaves(values, minimum=3):
    a = np.asarray(values, dtype=bool)
    padded = np.r_[False, a, False].astype(int)
    start = np.where(np.diff(padded) == 1)[0]
    end = np.where(np.diff(padded) == -1)[0]
    durations = (end-start)[end-start >= minimum]
    return len(durations), int(durations.sum()), int(durations.max()) if len(durations) else 0


def daily_aggregate(hourly, variable, kind):
    """Precipitation timestamp denotes the END of the preceding hourly interval."""
    idx = pd.to_datetime(hourly['time'])
    series = pd.Series(hourly[variable], index=idx, dtype=float)
    if series.index.has_duplicates:
        raise ValueError('Duplicate climate timestamps')
    if kind == 'sum':
        series.index = series.index - pd.Timedelta(hours=1)
    grouped = series.resample('D')
    output = grouped.sum(min_count=24) if kind == 'sum' else (grouped.max() if kind == 'max' else grouped.min())
    return output.where(grouped.count() == 24)


def retrieve_climate(cells, years):
    metrics, daily_rows = [], []
    for cell in cells.itertuples():
        for year in years:
            model = cell.model
            # Temperature uses ERA5-Land; rainfall/gust explicitly use ERA5.
            variables = 'temperature_2m' if model == 'era5_land' else 'precipitation,wind_gusts_10m'
            # Include next Jan 1 for end-labelled precipitation intervals.
            params = dict(latitude=cell.lat, longitude=cell.lon, start_date=f'{year}-01-01',
                end_date=f'{year+1}-01-01', models=model, hourly=variables, timezone='GMT',
                temperature_unit='celsius', wind_speed_unit='ms', precipitation_unit='mm', elevation='nan', cell_selection='nearest')
            path = ROOT / f'data/raw/{cell.cell_id}_{year}.json'
            payload, url = cached_json(path, 'https://archive-api.open-meteo.com/v1/archive', params=params)
            if abs(payload['latitude']-cell.lat)>0.002 or abs(payload['longitude']-cell.lon)>0.002:
                raise ValueError(f'Provider returned an unexpected cell: {cell.cell_id}')
            if payload['utc_offset_seconds'] != 0:
                raise ValueError('Expected UTC')
            h, units = payload['hourly'], payload['hourly_units']
            expected = pd.date_range(f'{year}-01-01', f'{year+1}-01-02', freq='h', inclusive='left')
            if not pd.DatetimeIndex(pd.to_datetime(h['time'])).equals(expected):
                raise ValueError('Missing or unordered hourly steps')
            record(path, url, f'Open-Meteo delivery of {model}', variables, json.dumps(units, ensure_ascii=False),
                f'{year}-01-01/{year+1}-01-01 UTC', f'EPSG:4326; {cell.step} degree native delivery grid; hourly',
                'CC BY 4.0; free API non-commercial terms', 'Open-Meteo; Copernicus Climate Change Service/ECMWF')
            index = pd.date_range(f'{year}-01-01', f'{year}-12-31')
            result = dict(cell_id=cell.cell_id, year=year, lon=cell.lon, lat=cell.lat, model=model)
            daily = pd.DataFrame(index=index)
            if model == 'era5_land':
                if units['temperature_2m'] != '°C':
                    raise ValueError('Unexpected temperature units')
                daily['tmax_c'] = daily_aggregate(h, 'temperature_2m', 'max').reindex(index)
                daily['tmin_c'] = daily_aggregate(h, 'temperature_2m', 'min').reindex(index)
                valid = daily.tmax_c.notna() & daily.tmin_c.notna()
                if not valid.all():
                    raise ValueError('Incomplete temperature year')
                hot = daily.tmax_c > CONFIG['heat_threshold_c']
                count, days, duration = heatwaves(hot, CONFIG['heatwave_min_days'])
                result.update(heat=float(hot.sum()), heatwave_count=count, heatwave_days=days,
                    heatwave_max_days=duration, freeze_thaw_days=int(((daily.tmin_c<0)&(daily.tmax_c>0)).sum()),
                    hottest_date=str(daily.tmax_c.idxmax().date()), annual_tmax_c=float(daily.tmax_c.max()))
            else:
                if units['precipitation'] != 'mm' or units['wind_gusts_10m'] != 'm/s':
                    raise ValueError('Unexpected rain or gust units')
                daily['rain_mm'] = daily_aggregate(h, 'precipitation', 'sum').reindex(index)
                daily['gust_ms'] = daily_aggregate(h, 'wind_gusts_10m', 'max').reindex(index)
                if daily.isna().any().any() or (daily.rain_mm<0).any():
                    raise ValueError('Missing/negative precipitation or missing gust')
                wet = daily.rain_mm[daily.rain_mm>=1]
                p95 = wet.quantile(0.95)
                result.update(rain=float(daily.rain_mm.max()), wind=float((daily.gust_ms>CONFIG['gust_threshold_ms']).sum()),
                    rain_wetday_p95_mm=float(p95), rain_above_annual_p95_mm=float(wet[wet>p95].sum()),
                    annual_rain_mm=float(daily.rain_mm.sum()), wettest_date=str(daily.rain_mm.idxmax().date()),
                    max_gust_ms=float(daily.gust_ms.max()))
            result['valid_days'] = len(daily)
            metrics.append(result)
            daily['cell_id'], daily['year'] = cell.cell_id, year
            daily_rows.append(daily.rename_axis('date').reset_index())
            print(f'Climate {cell.cell_id} {year}: {len(daily)} valid days', flush=True)
    annual = pd.DataFrame(metrics)
    all_daily = pd.concat(daily_rows, ignore_index=True)
    annual.to_csv(ROOT/'results/climate_annual.csv', index=False)
    all_daily.to_csv(ROOT/'data/processed/daily_climate.csv', index=False)
    # Keep grids at their own spatial resolution in separate chunked netCDF files.
    for model in cells.model.unique():
        selected = cells[cells.model==model]
        frame = all_daily[all_daily.cell_id.isin(selected.cell_id)].drop(columns='year')
        columns = ['tmax_c','tmin_c'] if model=='era5_land' else ['rain_mm','gust_ms']
        dataset = frame.set_index(['date','cell_id'])[columns].to_xarray().chunk({'date':31,'cell_id':1})
        dataset.attrs.update(provenance=STAMP, source='Open-Meteo API delivery; no claim of direct CDS bytes', timezone='UTC')
        dataset['lon'] = ('cell_id', selected.set_index('cell_id').loc[dataset.cell_id.values,'lon'].values)
        dataset['lat'] = ('cell_id', selected.set_index('cell_id').loc[dataset.cell_id.values,'lat'].values)
        for var in columns:
            dataset[var].attrs['units'] = {'tmax_c':'degree_Celsius','tmin_c':'degree_Celsius','rain_mm':'mm','gust_ms':'m s-1'}[var]
        dataset.to_netcdf(ROOT/f'data/processed/{model}_daily.nc', engine='h5netcdf')
    return annual


def weighted_quantile(values, weights, quantile=0.9):
    order = np.argsort(values)
    v, w = np.asarray(values)[order], np.asarray(weights)[order]
    return float(v[min(np.searchsorted(np.cumsum(w)/w.sum(), quantile), len(v)-1)])


def overlay_one(geometry, cells, variable):
    candidates = cells[cells.intersects(geometry)].sort_values('cell_id')
    values, weights = [], []
    is_line = 'Line' in geometry.geom_type
    is_polygon = 'Polygon' in geometry.geom_type
    total = geometry.length if is_line else geometry.area if is_polygon else 1
    if not is_line and not is_polygon:
        # Points on a boundary get one deterministic cell, never double-counted.
        candidates = candidates.sort_values('cell_id').head(1)
    remaining = geometry
    for cell in candidates.itertuples():
        cut = remaining.intersection(cell.geometry)
        weight = cut.length if is_line else cut.area if is_polygon else 1
        value = getattr(cell, variable)
        if weight > 0 and np.isfinite(value):
            values.append(value)
            weights.append(weight)
            if is_line:
                remaining = remaining.difference(cell.geometry)
    if not weights:
        return dict(mean=np.nan, p90=np.nan, max=np.nan, coverage=0, cells=0)
    # Shared grid-edge line segments belong to the first sorted cell only.
    coverage = min(sum(weights)/total, 1.0)
    return dict(mean=float(np.average(values, weights=weights)), p90=weighted_quantile(values, weights),
        max=float(max(values)), coverage=coverage, cells=len(values))


def overlay(assets, cells, annual):
    result = assets.copy()
    result['analysis_period'] = ', '.join(map(str, CONFIG['years']))
    summaries = annual.groupby('cell_id')[HAZARDS].mean()
    for hazard in HAZARDS:
        model = 'era5_land' if hazard=='heat' else 'era5'
        selected = cells[cells.model==model].merge(summaries[[hazard]], left_on='cell_id', right_index=True).to_crs(assets.crs)
        rows = [overlay_one(geom, selected, hazard) for geom in assets.geometry]
        for stat in ['mean','p90','max','coverage','cells']:
            result[f'{hazard}_{stat}'] = [row[stat] for row in rows]
        for stat in ['mean','max']:
            result[f'{hazard}_score_{stat}'] = np.clip(result[f'{hazard}_{stat}']/CONFIG['normalisation'][hazard],0,1)
    result['data_quality'] = 'Coarse climate; condition, loading, redundancy and service area unknown'
    return result


def score_sensitivity(result):
    base = result[[f'{h}_score_mean' for h in HAZARDS]].to_numpy()
    conservative = result[[f'{h}_score_max' for h in HAZARDS]].to_numpy()
    # Missing indicators propagate; there is no implicit zero or reweighting.
    scenario_scores = {}
    for name, weights in CONFIG['weights'].items():
        scenario_scores[name] = np.average(base, axis=1, weights=weights)
    for i, hazard in enumerate(HAZARDS):
        scenario_scores[f'without_{hazard}'] = np.mean(np.delete(base,i,axis=1), axis=1)
    scenario_scores['maximum_overlay'] = conservative.mean(axis=1)
    # Illustrative unknown sensitivity/capacity assumptions; these are NOT observations.
    overhead = result.power.isin(['line','minor_line']).to_numpy()
    scenario_scores['assumed_line_sensitivity'] = scenario_scores['equal'] * np.where(overhead,1.25,1.0)
    scenario_scores['assumed_line_adaptation'] = scenario_scores['equal'] * np.where(overhead,0.75,1.0)
    baseline = pd.Series(scenario_scores['equal'])
    cutoff = baseline.quantile(0.9)
    baseline_set = set(np.where(baseline>=cutoff)[0])
    sets, rows = [], []
    for name, values in scenario_scores.items():
        result[f'priority_{name}'] = values
        values = pd.Series(values)
        chosen = set(np.where(values>=values.quantile(0.9))[0])
        sets.append(chosen)
        rho = spearmanr(baseline, values).statistic if baseline.nunique()>1 and values.nunique()>1 else np.nan
        rows.append(dict(scenario=name, n=len(values), rank_spearman=rho,
            selected_at_or_above_p90=len(chosen), overlap_with_equal=len(chosen&baseline_set),
            jaccard=len(chosen&baseline_set)/len(chosen|baseline_set) if chosen|baseline_set else np.nan,
            provenance='new reconstruction'))
    stable = set.intersection(*sets)
    result['stable_top_decile'] = [i in stable for i in range(len(result))]
    table = pd.DataFrame(rows)
    table.to_csv(ROOT/'results/sensitivity.csv', index=False)
    return result, table


def export_rasters(cells, annual):
    summaries = annual.groupby('cell_id')[HAZARDS].mean()
    for hazard in HAZARDS:
        model = 'era5_land' if hazard=='heat' else 'era5'
        selected = cells[cells.model==model]
        step = selected.step.iloc[0]
        west, south, east, north = selected.total_bounds
        width, height = round((east-west)/step), round((north-south)/step)
        array = np.full((height,width), -9999., dtype='float32')
        for c in selected.itertuples():
            row, col = round((north-step/2-c.lat)/step), round((c.lon-west-step/2)/step)
            array[row,col] = summaries.loc[c.cell_id,hazard]
        with rasterio.open(ROOT/f'results/hazard_{hazard}.tif', 'w', driver='GTiff', height=height, width=width,
            count=1, dtype='float32', crs='EPSG:4326', transform=from_origin(west,north,step,step), nodata=-9999, compress='deflate') as dst:
            dst.write(array,1)
            dst.update_tags(provenance=STAMP, period=','.join(map(str,CONFIG['years'])),
                units='days/year' if hazard!='rain' else 'mm (mean annual RX1day)', source=f'{model} via Open-Meteo',
                warning='Native grid; cells outside study area are nodata; screening only')


def exports(study, assets, scores, cells, annual):
    gpkg = ROOT/'results/energy_assets.gpkg'
    if gpkg.exists():
        gpkg.unlink()  # Only this known generated file is replaced.
    study.to_file(gpkg, layer='study_area', driver='GPKG')
    assets.to_file(gpkg, layer='assets', driver='GPKG')
    scores.to_file(gpkg, layer='scores', driver='GPKG')
    scores[['asset_id','missing_voltage','missing_operator','missing_topology','coincident_geometry','data_quality','geometry']].to_file(gpkg,layer='data_quality',driver='GPKG')
    cells.to_file(gpkg,layer='climate_cells',driver='GPKG')
    scores.drop(columns='geometry').to_csv(ROOT/'results/asset_scores.csv', index=False)
    scores.to_crs(4326).to_file(ROOT/'webgis/assets.geojson',driver='GeoJSON')
    study.to_crs(4326).to_file(ROOT/'webgis/study_area.geojson',driver='GeoJSON')
    climate = cells.merge(annual.groupby('cell_id')[HAZARDS].mean(), left_on='cell_id',right_index=True)
    climate.to_file(ROOT/'webgis/climate_cells.geojson',driver='GeoJSON')
    export_rasters(cells,annual)
    plot_figures(study,scores,cells,annual)


def plot_figures(study,scores,cells,annual):
    climate = cells.merge(annual.groupby('cell_id')[HAZARDS].mean(), left_on='cell_id',right_index=True)
    figure, ax = plt.subplots(figsize=(10,9))
    climate[climate.model=='era5_land'].to_crs(study.crs).plot(column='heat',ax=ax,cmap=SEQUENTIAL,alpha=.65,legend=True,legend_kwds={'label':'Mean days/year with Tmax > 35 °C'})
    study.boundary.plot(ax=ax,color=INK,linewidth=1.2)
    line = scores[scores.geom_type.str.contains('Line')]
    line.plot(ax=ax,color=COLORS[0],linewidth=.5)
    other = scores[~scores.geom_type.str.contains('Line')]
    other.plot(ax=ax,color=COLORS[1],markersize=8)
    ax.set(title=f'Turin energy infrastructure: {CONFIG["years"]}\nOpen-data reconstruction', xlabel='Easting (EPSG:3035), m',ylabel='Northing (EPSG:3035), m')
    ax.text(.01,.01,'OSM contributors (ODbL); ERA5-Land via Open-Meteo (CC BY 4.0)\nScreening only; public mapped assets are an incomplete grid.',transform=ax.transAxes,fontsize=8,bbox=dict(facecolor='white',alpha=.9))
    figure.tight_layout()
    figure.savefig(ROOT/'figures/study_area_heat.png',dpi=180)
    plt.close(figure)
    for hazard in ['rain','wind']:
        fig, ax = plt.subplots(figsize=(8,7))
        native = climate[climate.model=='era5'].to_crs(study.crs)
        if native[hazard].nunique()==1:
            native.plot(ax=ax,color='#DDEFF3',edgecolor=COLORS[2],linewidth=.6)
            for row in native.itertuples():
                point=row.geometry.representative_point()
                ax.text(point.x,point.y,f'{getattr(row,hazard):.0f}',ha='center',va='center',fontsize=11)
            ax.text(.5,.94,'0 days/year in every cell at the 20 m/s threshold',ha='center',transform=ax.transAxes,fontsize=10)
        else:
            native.plot(column=hazard,ax=ax,cmap=SEQUENTIAL,legend=True,edgecolor=COLORS[2],linewidth=.4,
                legend_kwds={'label':'Mean annual RX1day (mm)' if hazard=='rain' else 'Mean gust exceedance days/year'})
        study.boundary.plot(ax=ax,color=INK)
        ax.set(title=f'{hazard}: {CONFIG["years"]} · Open-data reconstruction',xlabel='EPSG:3035 easting (m)',ylabel='Northing (m)')
        ax.text(.01,.01,'ERA5 via Open-Meteo; native 0.25° grid\n'+('Mean annual RX1day (mm)' if hazard=='rain' else 'Mean days/year with gust > 20 m/s'),transform=ax.transAxes,fontsize=8)
        fig.tight_layout(); fig.savefig(ROOT/f'figures/hazard_{hazard}.png',dpi=160); plt.close(fig)


def report(study, assets, scores, cells, annual, sensitivity, seconds):
    types = assets.power.value_counts().to_dict()
    summary = dict(computed=STAMP, area_km2=float(study.area.sum()/1e6), assets=len(assets), asset_types=types,
        line_length_km=float(assets.length_km.sum()), years=CONFIG['years'],
        climate_cells=cells.model.value_counts().to_dict(), missing_voltage=int(assets.missing_voltage.sum()),
        missing_operator=int(assets.missing_operator.sum()), stable_top_decile=int(scores.stable_top_decile.sum()),
        runtime_seconds=seconds, peak_rss_mb=psutil.Process().memory_info().peak_wset/1e6 if sys.platform=='win32' else psutil.Process().memory_info().rss/1e6)
    (ROOT/'results/summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    rows = ['| Scenario | Spearman vs equal | Selected incl. ties | Jaccard vs equal |','|---|---:|---:|---:|']
    for row in sensitivity.itertuples():
        rows.append(f'| {row.scenario} | {row.rank_spearman:.3f} | {row.selected_at_or_above_p90} | {row.jaccard:.3f} |')
    top = scores.sort_values(['priority_equal','asset_id'],ascending=[False,True]).head(15)
    tops = ['| OSM asset | Type | Heat days/year | RX1day mm | Gust days/year | Priority |','|---|---|---:|---:|---:|---:|']
    for r in top.itertuples():
        tops.append(f'| {r.asset_id} | {r.power} | {r.heat_mean:.2f} | {r.rain_mean:.2f} | {r.wind_mean:.2f} | {r.priority_equal:.3f} |')
    source='https://www.arpa.piemonte.it/notizia/situazione-meteo-climatica-piemonte-nel-2023-suoi-impatti-sulle-risorse-idriche'
    heat_2023=annual[(annual.year==2023)&(annual.model=='era5_land')]
    dates=heat_2023.hottest_date.value_counts().to_dict()
    report_text=f'''# Climate screening of Turin electrical infrastructure

**{STAMP}. New reconstruction; no recovered historical evidence.**

## Research question and scope
Which publicly mapped assets overlap coarse-grid heat, rainfall and gust indicators, and how stable is their relative priority? The analyst-defined contiguous square around Turin (7.6869° E, 45.0703° N) measures **{summary['area_km2']:.6f} km² in EPSG:3035**. Its square shape fixes area without selecting a boundary after viewing hazards. It is not a service territory or administrative unit. Edges can cut networks. Pilot analysis years: {CONFIG['years']}; no multi-decadal climatological inference.

## Data and methods
OpenStreetMap returned **{len(assets)} clipped assets**, {types}, and **{summary['line_length_km']:.3f} km** of mapped line geometry. These counts are mapped features, not complete circuits or independent facilities. Raw query, OSM timestamp, identifiers, versions and hashes are retained. Different OSM identities with coincident geometry are flagged and retained, since they may be parallel circuits.

ERA5-Land temperature is delivered by Open-Meteo on its native 0.1° grid ({summary['climate_cells'].get('era5_land',0)} intersecting cells). ERA5 precipitation and gusts use 0.25° ({summary['climate_cells'].get('era5',0)} cells). This is a documented delivery substitution for direct CDS retrieval, which requires credentials. Native provider JSON is retained; processed daily netCDF is derived locally. Statistical elevation downscaling is disabled; cells are selected by nearest centre and returned coordinates are checked. These fields do not resolve equipment microclimate.

Heat = annual days with hourly-sampled daily Tmax >35°C. Heatwaves = runs of at least 3 such days, computed within each calendar year. Freeze-thaw = days with Tmin <0°C and Tmax >0°C (air-temperature proxy, not material cycles). Rain = annual RX1day from daily sums. Wet-day p95 uses that same year's days >=1 mm, and is explicitly an annual descriptive percentile rather than a 1991–2020 R95p baseline. Wind = days with daily maximum hourly gust >20 m/s. Thresholds are analyst-defined screening choices, never engineering damage limits. All daily temperature/gust metrics require 24 finite hourly samples. End-labelled precipitation is shifted back one hour before UTC-day sums; next January 1 is retrieved to close December 31. Leap days are retained. See METHODOLOGY.md for formulas and missingness.

Lines intersect climate cells and use intersected length weights; polygons use intersected area; points use a deterministic containing cell. Mean, weighted p90 and conservative maximum are retained, together with coverage and number of cells. Mean annual indicators are computed across complete years. The heat/rain/wind normalisation divisors 30 days/year, 100 mm and 10 days/year are fixed screening reference ranges; scores are clipped to [0,1], and averaged at equal weights. They are not failure probabilities or losses.

## Results
Missing voltage: **{summary['missing_voltage']}/{len(assets)}**; missing operator: **{summary['missing_operator']}/{len(assets)}**. Asset condition, loading, age, redundancy, adaptive capacity and customers served are missing for every feature. No operational resilience score or demographic consequence score is asserted. Individual exposure results are in `results/asset_scores.csv` and the GeoPackage `scores` layer.

The following first 15 rows are sorted by equal-weight exposure screening priority, breaking presentation ties by OSM ID. Ties and many colocated features prevent unique asset-scale priority interpretations. Denominator: {len(assets)} mapped features.

{chr(10).join(tops)}

![Study area and heat](figures/study_area_heat.png)

Figure 1. Actual clipped OSM geometry and mean {CONFIG['years']} heat indicator from {summary['climate_cells'].get('era5_land',0)} native cells. Open-data reconstruction. OSM contributors; Copernicus/ECMWF via Open-Meteo. Areas outside the square are shown only to expose cell support.

![Rainfall](figures/hazard_rain.png)

Figure 2. Mean annual RX1day (mm), {CONFIG['years']}, native ERA5 cells; open-data reconstruction.

![Wind gusts](figures/hazard_wind.png)

Figure 3. Mean days/year with hourly gust >20 m/s, {CONFIG['years']}, native ERA5 cells; open-data reconstruction.

## Sensitivity
Weights 2:1:1, 1:2:1 and 1:1:2, leave-one-hazard-out, maximum versus weighted overlay, and two deliberately hypothetical line sensitivity/adaptation multipliers are compared below. Last two scenarios assume respectively 25% greater sensitivity or 25% lower priority through adaptation for line/minor_line features. Neither assumption is measured. Their effect illustrates missing-data dependence; observed sensitivity and adaptive-capacity fields remain null. Every scenario uses all {len(assets)} assets. Top decile means score >= the empirical 90th percentile, retaining all ties; it may contain more than 10% of assets. Stable set = intersection across all scenarios: **{summary['stable_top_decile']} features**. This is scenario stability, not evidence of failure risk.

{chr(10).join(rows)}

## Independent climate check
[ARPA Piemonte's 2023 report]({source}) identifies 23 August as the region's hottest day. The modal hottest dates of our {len(heat_2023)} ERA5-Land cells in 2023 are {dates}. This is an event-date plausibility check across different geographic supports, not station-level statistical validation. ARPA's regional reference period is 1991–2020, which has not been retrieved here; we do not claim agreement on anomalies. ERA5 and ERA5-Land are related products and are not independent validations of each other.

## Limitations and decisions
No failure-outcome validation: an openly licensed, spatially matched asset outage/damage dataset has not been obtained. Do not use scores to claim predicted failure, monetary loss or customers affected. Coarse rainfall/gust grids, incomplete OSM mapping and unknown asset condition dominate asset-scale uncertainty. Asset counts overweight heavily mapped substations and mapped line segmentation; compare types separately before resource allocation. Population, service territories and network redundancy are omitted rather than invented. See the limitations matrix for likely effects.

## Delivery status
Completed: real-data end-to-end pilot over the target study area, two full analysis years, three hazards, asset audit, native-resolution raster layers, daily netCDF, GeoPackage, sensitivity table, local Leaflet source and API, tests and reproduction records.
Partially complete: regional climate event plausibility check; no station-based quantitative check. Direct CDS raw-data path and 1991–2020 baseline await separate execution. No historical project claims.
Not obtained: proprietary asset characteristics, outage labels, actual service territories. No online deployment is claimed. QGIS inspection status is recorded separately.
'''
    (ROOT/'SCIENTIFIC_REPORT.md').write_text(report_text,encoding='utf-8')
    versions={p:importlib.metadata.version(p) for p in ['numpy','pandas','geopandas','shapely','pyproj','rasterio','xarray','dask','scipy','fastapi','pytest','h5netcdf']}
    (ROOT/'results/software_versions.json').write_text(json.dumps(dict(python=sys.version,platform=platform.platform(),packages=versions),indent=2))
    (ROOT/'REPRODUCIBILITY_REPORT.md').write_text(f'''# Reproducibility record

{STAMP}

- Python {platform.python_version()}; versions in results/software_versions.json; all packages pinned in requirements-lock.txt.
- Seed: {CONFIG['seed']} (deterministic analysis; no random sampling).
- Runtime: {seconds:.2f} s; observed process peak working set: {summary['peak_rss_mb']:.1f} MB.
- Equal-area analysis CRS: EPSG:3035. Provider grid and GeoTIFF CRS: EPSG:4326.
- Raw responses, exact requests and SHA-256 values are retained. Raw cache is reused; delete selected generated raw files only to explicitly refresh data. Changing date or extent requires new cache names or a clean data/raw folder.
- Runtime depends on cached downloads and machine. This run's analysis years: {CONFIG['years']}.
- Credential-dependent direct CDS acquisition was not run. Processed netCDF derives from API-delivered hourly values, not downloaded CDS netCDF.
- Tests and QGIS status: see results/validation.txt and results/qgis_status.json when present.
- Regeneration commands and service URLs: README.md. API binds only to 127.0.0.1; publication is not performed.
''',encoding='utf-8')
    return summary


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--years', nargs='+',type=int)
    parser.add_argument('--audit-only',action='store_true')
    args=parser.parse_args()
    if args.years:
        CONFIG['years']=args.years
    start=time.perf_counter()
    directories()
    study=study_area()
    assets=get_assets(study)
    print(f'Study area {study.area.sum()/1e6:.6f} km²; {len(assets)} mapped assets',flush=True)
    if args.audit_only:
        assets.to_file(ROOT/'results/assets_audit.gpkg',layer='assets',driver='GPKG')
        pd.DataFrame(MANIFEST).to_csv(ROOT/'data_sources.csv',index=False)
        return
    cells=gpd.GeoDataFrame(pd.concat([grid(study,.1,'era5_land'),grid(study,.25,'era5')],ignore_index=True),crs=4326)
    annual=retrieve_climate(cells,CONFIG['years'])
    scores=overlay(assets,cells,annual)
    scores,sensitivity=score_sensitivity(scores)
    exports(study,assets,scores,cells,annual)
    pd.DataFrame(MANIFEST).to_csv(ROOT/'data_sources.csv',index=False)
    summary=report(study,assets,scores,cells,annual,sensitivity,time.perf_counter()-start)
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    main()
