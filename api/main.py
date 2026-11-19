"""Local read-only GeoJSON API and Leaflet delivery."""
import json
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

ROOT=Path(__file__).resolve().parents[1]
app=FastAPI(title='Turin energy climate screening reconstruction',version='0.1.0',
    description='Exploratory mapped exposure. No failure probabilities, service territories or outage validation.')


def features():
    path=ROOT/'webgis/assets.geojson'
    if not path.exists():
        raise HTTPException(503,'Run scripts/pipeline.py first')
    return json.loads(path.read_text(encoding='utf-8'))['features']


@app.get('/health')
def health():
    return {'status':'ok','data_ready':(ROOT/'webgis/assets.geojson').exists()}


@app.get('/assets')
def assets(power:Literal['line','minor_line','substation','transformer']|None=None,
           offset:int=Query(0,ge=0),limit:int=Query(200,ge=1,le=5000)):
    rows=[f for f in features() if power is None or f['properties']['power']==power]
    return {'type':'FeatureCollection','total':len(rows),'offset':offset,'features':rows[offset:offset+limit]}


@app.get('/assets/{asset_id:path}')
def asset(asset_id:str):
    for f in features():
        if f['properties']['asset_id']==asset_id:
            return f
    raise HTTPException(404,'Asset ID not found')


@app.get('/scores')
def scores(hazard:Literal['heat','rain','wind']='heat',offset:int=Query(0,ge=0),limit:int=Query(200,ge=1,le=5000)):
    rows=[dict(asset_id=f['properties']['asset_id'],power=f['properties']['power'],
        mean=f['properties'][f'{hazard}_mean'],p90=f['properties'][f'{hazard}_p90'],
        maximum=f['properties'][f'{hazard}_max'],coverage=f['properties'][f'{hazard}_coverage'],
        normalised_score=f['properties'][f'{hazard}_score_mean']) for f in features()]
    rows.sort(key=lambda r: (-(r['normalised_score'] if r['normalised_score'] is not None else -1),r['asset_id']))
    return {'hazard':hazard,'units':'mm (mean annual RX1day)' if hazard=='rain' else 'days/year',
        'warning':'Screening only; coarse grid, incomplete public assets, unknown sensitivity and adaptive capacity',
        'total':len(rows),'rows':rows[offset:offset+limit]}


app.mount('/map',StaticFiles(directory=ROOT/'webgis',html=True),name='map')
