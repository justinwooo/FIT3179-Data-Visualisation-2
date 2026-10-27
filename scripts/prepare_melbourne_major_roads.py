"""Fetch highways and major arterial roads from OpenStreetMap via OSMnx.
Needs internet; python -m pip install osmnx
Run: python scripts/prepare_melbourne_major_roads.py
Overpass may be busy; this is optional. The map works with an empty roads file.
"""
from pathlib import Path
import geopandas as gpd
import osmnx as ox
import json
ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data'/'raw'; OUT=ROOT/'data'/'processed'; OUT.mkdir(exist_ok=True,parents=True)
lgas=gpd.read_file(RAW/'LGA_2021_AUST_GDA2020_SHP'/'LGA_2021_AUST_GDA2020.shp')
# Use existing 31-council study area (instead of all Victoria).
focus=json.loads((OUT/'parks_explorer_focus.json').read_text())
names={i['label'].split(' (')[0].upper() for i in focus[1:]}
# Also handles name suffixes such as Bayside (Vic.)
lgas=lgas[lgas['LGA_NAME21'].str.replace(r'\s*\([^)]*\)','',regex=True).str.upper().isin(names)].copy()
if lgas.empty:
    raise ValueError('No study municipalities matched; check LGA fields')
print('Matched',len(lgas),'LGAs. Preparing metropolitan road query...')
metro=lgas.to_crs(7855).geometry.union_all().simplify(1200).buffer(0).buffer(1500)
# OSMnx may split this query into multiple Overpass requests.
metro_ll=gpd.GeoSeries([metro],crs='EPSG:7855').to_crs(4326).iloc[0]
ox.settings.use_cache=True
ox.settings.requests_timeout=180
major='["highway"~"motorway|trunk|primary|secondary|motorway_link|trunk_link|primary_link|secondary_link"]'
print('Downloading motorway, trunk, primary, secondary and link roads; internet required...')
G=ox.graph_from_polygon(metro_ll,custom_filter=major,network_type='drive',retain_all=True)
_,edges=ox.graph_to_gdfs(G)
roads=edges.reset_index(drop=True)
roads=roads[roads.geometry.notna()].copy()
if 'highway' not in roads.columns:
    raise ValueError('No highway classifications in OpenStreetMap result')

def classify(v):
    v=' '.join(v) if isinstance(v,list) else str(v)
    return 'Highway/freeway' if ('motorway' in v or 'trunk' in v) else 'Metropolitan arterial'
roads['road_class']=roads.highway.map(classify)
# Remove duplicate directed OSM edges via geometry WKB
roads=roads.to_crs(7855)
roads['geometry']=roads.geometry.simplify(12,preserve_topology=True)
roads=roads.loc[~roads.geometry.is_empty].copy()
roads['wkb']=roads.geometry.to_wkb()
roads=roads.drop_duplicates('wkb').drop(columns='wkb')
roads=roads[['road_class','geometry']].to_crs(4326)
out=OUT/'melbourne_major_roads.geojson'
roads.to_file(out,driver='GeoJSON')
print('Exported',len(roads),'road segments to',out,'(',round(out.stat().st_size/1e6,2),'MB )')
print('OSM road class is a cartographic approximation, not a Victorian statutory designation.')
