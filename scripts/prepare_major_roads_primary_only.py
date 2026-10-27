"""Smaller OSMnx road request, focused on the urban core.
Run: python scripts/prepare_major_roads_fast.py
This deliberately does NOT cover every outer metropolitan council.
"""
from pathlib import Path
import geopandas as gpd
import osmnx as ox
from shapely.geometry import box
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'data'/'processed'
OUT.mkdir(parents=True,exist_ok=True)
# Smaller urban-core bbox [west, south, east, north], WGS84
AREA = box(144.80, -38.02, 145.30, -37.64)
ox.settings.use_cache = True
ox.settings.requests_timeout = 120
filter_str = '["highway"~"^(motorway|trunk|primary|motorway_link|trunk_link|primary_link)$"]'
print('Querying urban core only (not all 31 LGAs).')
G = ox.graph_from_polygon(AREA, custom_filter=filter_str, retain_all=True, simplify=True)
_,roads = ox.graph_to_gdfs(G)
roads=roads.reset_index(drop=True).to_crs(7855)
roads=roads[roads.geometry.notna()].copy()
def classify(x):
    val=' '.join(x) if isinstance(x,list) else str(x)
    return 'Highway/freeway' if any(k in val for k in ('motorway','trunk')) else 'Metropolitan arterial'
roads['road_class']=roads['highway'].map(classify)
roads['geometry']=roads.geometry.simplify(20,preserve_topology=True)
roads=roads[['road_class','highway','geometry']].to_crs(4326)
output=OUT/'melbourne_major_roads.geojson'
roads.to_file(output,driver='GeoJSON')
print(f'Wrote {len(roads)} road segments, {output.stat().st_size/1e6:.2f} MB to {output}')
print('Road coverage limited to the bbox in this script.')
