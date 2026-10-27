"""Fetch major OSM roads covering all study LGAs in manageable tiles.
Only motorways, trunks and primary road types, including links. No Geofabrik.
Run locally: python scripts/prepare_melbourne_major_roads_full.py
OSMnx 2.x required. Each tile is cached locally to resume after an interruption.
"""
from pathlib import Path
import json
import math
import geopandas as gpd
import osmnx as ox
from shapely.geometry import box, LineString, MultiLineString, GeometryCollection
from shapely.ops import unary_union

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data'/'raw'
OUT=ROOT/'data'/'processed'
CACHE=ROOT/'data'/'road_cache'
OUT.mkdir(parents=True,exist_ok=True)
CACHE.mkdir(parents=True,exist_ok=True)

TILE_DEGREES_LON=0.26
TILE_DEGREES_LAT=0.19
TOLERANCE_METRES=30
FILTER='["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link)$"]'

print('Reading study boundaries...')
lga=gpd.read_file(OUT/'melbourne_lga_boundaries_final.geojson').to_crs(4326)
if lga.empty: raise ValueError('Study LGA GeoJSON is empty.')
study_union=unary_union(lga.geometry)
# Tile the actual study envelope, skip tiles not touching the study area.
w,s,e,n=study_union.bounds
lon_edges=[w+i*TILE_DEGREES_LON for i in range(math.ceil((e-w)/TILE_DEGREES_LON)+1)]
lat_edges=[s+i*TILE_DEGREES_LAT for i in range(math.ceil((n-s)/TILE_DEGREES_LAT)+1)]
if lon_edges[-1]<e: lon_edges.append(e)
if lat_edges[-1]<n: lat_edges.append(n)
tiles=[]
for i in range(len(lon_edges)-1):
    for j in range(len(lat_edges)-1):
        geom=box(lon_edges[i],lat_edges[j],min(lon_edges[i+1],e),min(lat_edges[j+1],n))
        if geom.intersects(study_union):tiles.append((i,j,geom))
print(f'Planned {len(tiles)} smaller queries, with cached results for resuming.')
ox.settings.use_cache=True
ox.settings.requests_timeout=180
# Query individual rectangular tiles; avoid a very large 31-LGA request.
for k,(i,j,tile) in enumerate(tiles,1):
    target=CACHE/f'roads_tile_{i:02d}_{j:02d}.geojson'
    if target.exists():
        print(f'[{k}/{len(tiles)}] Tile {i},{j}: cached',flush=True)
        continue
    print(f'[{k}/{len(tiles)}] Tile {i},{j}: requesting OSM...',flush=True)
    try:
        G=ox.graph_from_polygon(tile,custom_filter=FILTER,retain_all=True,simplify=True,truncate_by_edge=True)
        _,edges=ox.graph_to_gdfs(G)
        roads=edges.reset_index(drop=True)
        roads=roads.loc[roads.geometry.notna(),['highway','geometry']].to_crs(4326).copy()
        if roads.empty: target.write_text('{"type":"FeatureCollection","features":[]}')
        else: roads.to_file(target,driver='GeoJSON')
    except Exception as exc:
        print(f'  FAILED: {type(exc).__name__}: {exc}',flush=True)
        print('Previously completed tiles are saved. Rerun later to continue.')
        raise

print('Combining tile outputs...',flush=True)
frames=[]
for i,j,_ in tiles:
    f=CACHE/f'roads_tile_{i:02d}_{j:02d}.geojson'
    r=gpd.read_file(f)
    if len(r):frames.append(r[['highway','geometry']])
if not frames:raise RuntimeError('No roads returned in tiles.')
import pandas as pd
roads=gpd.GeoDataFrame(pd.concat(frames,ignore_index=True),geometry='geometry',crs='EPSG:4326')
roads=roads.to_crs(7855)
study=gpd.GeoSeries([study_union],crs=4326).to_crs(7855).iloc[0]
# Clip to the actual study area: no abruptly ending road coverage in outer LGAs.
roads=gpd.clip(roads,gpd.GeoDataFrame(geometry=[study],crs=7855)).copy()
roads=roads[roads.geometry.geom_type.isin(['LineString','MultiLineString'])].copy()

def group(value):
    xs=value if isinstance(value,list) else [value]
    xs=[str(x) for x in xs]
    return 'Motorway / trunk' if any(x.startswith(('motorway','trunk')) for x in xs) else 'Primary arterial'
roads['road_class']=roads.highway.map(group)
roads.geometry=roads.geometry.simplify(TOLERANCE_METRES,preserve_topology=True)
roads=roads[~roads.geometry.is_empty]
roads=roads[['road_class','geometry']].to_crs(4326)
# Remove exact repeats from neighboring tiles (not legitimate distinct segments).
roads['geom_key']=roads.geometry.to_wkb(hex=True)
roads=roads.drop_duplicates('geom_key').drop(columns='geom_key')
output=OUT/'melbourne_major_roads.geojson'
roads.to_file(output,driver='GeoJSON')
print(f'Complete: {len(roads):,} road pieces, {output.stat().st_size/1e6:.2f} MB -> {output}',flush=True)
print('If file is too large, increase TOLERANCE_METRES and rerun; cached tiles will be reused.')
