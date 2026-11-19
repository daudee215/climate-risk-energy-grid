import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box,LineString,Point
from scripts.pipeline import heatwaves,daily_aggregate,overlay_one,weighted_quantile,study_area
from api.main import app
from fastapi.testclient import TestClient


def test_heatwave_runs_and_year_boundary():
    assert heatwaves([0,1,1,1,0,1,1,1,1,0])==(2,7,4)
    assert heatwaves([1,1])==(0,0,0)
    assert heatwaves([])==(0,0,0)


def test_precipitation_end_timestamp_and_leap_day():
    idx=pd.date_range('2024-02-29','2024-03-01 01:00',freq='h')
    h={'time':idx.astype(str).tolist(),'precipitation':np.ones(len(idx)).tolist()}
    daily=daily_aggregate(h,'precipitation','sum')
    assert daily.loc['2024-02-29']==24
    h['precipitation'][10]=None
    assert np.isnan(daily_aggregate(h,'precipitation','sum').loc['2024-02-29'])


def test_incomplete_tmax_is_not_a_valid_day():
    idx=pd.date_range('2023-01-01',periods=24,freq='h')
    h={'time':idx.astype(str).tolist(),'t':[30.]*23+[None]}
    assert np.isnan(daily_aggregate(h,'t','max').iloc[0])


@pytest.fixture
def cells():
    return gpd.GeoDataFrame({'cell_id':['a','b'],'heat':[10.,30.]},geometry=[box(0,0,1,1),box(1,0,2,1)],crs=3035)


def test_line_uses_length_instead_of_centroid(cells):
    result=overlay_one(LineString([(0,.5),(2,.5)]),cells,'heat')
    assert result['mean']==20 and result['max']==30 and result['coverage']==1
    result=overlay_one(LineString([(.5,.5),(2,.5)]),cells,'heat')
    assert result['mean']==pytest.approx(70/3)


def test_polygon_area_and_boundary_point(cells):
    assert overlay_one(box(.5,0,2,1),cells,'heat')['mean']==pytest.approx(70/3)
    point=overlay_one(Point(1,.5),cells,'heat')
    assert point['cells']==1 and point['coverage']==1
    assert overlay_one(Point(10,10),cells,'heat')['coverage']==0


def test_equal_area_window():
    assert study_area().area.sum()/1e6==pytest.approx(1400,abs=1e-6)


def test_weighted_quantile():
    assert weighted_quantile([10,20],[95,5],.9)==10


def test_shared_boundary_line_is_assigned_once(cells):
    result=overlay_one(LineString([(1,0),(1,1)]),cells,'heat')
    assert result['coverage']==1 and result['cells']==1 and result['mean']==10


def test_result_tables_have_no_computation_date_stamps():
    root=Path(__file__).resolve().parents[1]
    for name in ['asset_scores.csv','sensitivity.csv','heat_baseline_1991_2020.csv']:
        path=root/'results'/name
        if path.exists():
            assert 'computed on' not in path.read_text(encoding='utf-8')


def test_completed_temperature_reference():
    root=Path(__file__).resolve().parents[1]
    path=root/'results/heat_baseline_1991_2020.csv'
    if not path.exists():
        pytest.skip('Reference retrieval not completed')
    baseline=pd.read_csv(path)
    assert len(baseline)==22 and baseline.n_days.eq(10958).all()
    assert baseline.cell_id.is_unique
    assert baseline.heat_days_per_year.between(0,366).all()


def test_real_exports_and_api():
    root=Path(__file__).resolve().parents[1]
    if not (root/'results/energy_assets.gpkg').exists():
        pytest.skip('Integration requires executed pipeline')
    assets=gpd.read_file(root/'results/energy_assets.gpkg',layer='scores')
    assert assets.asset_id.is_unique
    assert assets.geometry.is_valid.all()
    assert assets.sensitivity.isna().all() and assets.adaptive_capacity.isna().all()
    for hazard in ['heat','rain','wind']:
        assert assets[f'{hazard}_coverage'].between(.9999,1).all()
        assert (assets[f'{hazard}_mean']<=assets[f'{hazard}_max']+1e-8).all()
        assert assets[f'{hazard}_score_mean'].between(0,1).all()
    client=TestClient(app)
    response=client.get('/assets?limit=2')
    assert response.status_code==200 and len(response.json()['features'])==2
    uid=response.json()['features'][0]['properties']['asset_id']
    assert client.get('/assets/'+uid).status_code==200
    assert client.get('/assets/osm/way/-1').status_code==404
    assert client.get('/scores?hazard=bad').status_code==422
    assert client.get('/assets?offset=-1').status_code==422
    assert client.get('/scores?hazard=rain').json()['units'].startswith('mm')
    assert client.get('/map/').status_code==200
    assert client.get('/openapi.json').status_code==200
