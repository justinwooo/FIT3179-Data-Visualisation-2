"""Download City of Melbourne road centre-lines for Vega-Lite chart 12.
Run from the project root: python scripts/prepare_melbourne_roads.py
Requires: pip install osmnx geopandas shapely
Uses OpenStreetMap/Overpass; requires an internet connection during preparation.
"""
from pathlib import Path
import geopandas as gpd
import osmnx as ox

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
OUT = ROOT / 'data' / 'processed'
OUT.mkdir(parents=True, exist_ok=True)
SHAPE = RAW / 'LGA_2021_AUST_GDA2020_SHP' / 'LGA_2021_AUST_GDA2020.shp'

print('Reading ABS 2021 City of Melbourne boundary...')
lga = gpd.read_file(SHAPE)
city = lga[
    lga["LGA_NAME21"].astype(str).str.strip().str.lower()
    == "melbourne"
].copy()
if len(city) != 1:
    names = lga[lga['LGA_NAME21'].astype(str).str.contains('Melbourne', case=False, na=False)]['LGA_NAME21'].tolist()
    raise ValueError(f'Expected one Melbourne (C) boundary, found {len(city)}. Matches: {names}')
city = city.to_crs(4326)
city_polygon = city.geometry.iloc[0]
print('Fetching driveable street centre-lines from OpenStreetMap (may take a minute)...')
ox.settings.use_cache = True
ox.settings.log_console = False
network = ox.graph_from_polygon(city_polygon, network_type='drive', simplify=True, retain_all=True)
roads = ox.graph_to_gdfs(network, nodes=False, fill_edge_geometry=True).reset_index()
roads = roads.to_crs(7855)
# Keep a single record per geometry and clip to the municipal boundary.
city_projected = city.to_crs(7855)
roads = gpd.clip(roads[['geometry', 'highway']].copy(), city_projected)
roads = roads[roads.geometry.notna() & ~roads.geometry.is_empty].copy()
roads['geometry'] = roads.geometry.simplify(tolerance=8, preserve_topology=True)
# Simplify classifications and omit other metadata, keeping the JSON lightweight.
def classify(v):
    if isinstance(v, list): v = v[0] if v else ''
    if v in {'motorway', 'trunk', 'primary', 'secondary'}: return 'major'
    return 'local'
roads['road_class'] = roads['highway'].map(classify)
roads = roads[['road_class', 'geometry']].to_crs(4326)
output = OUT / 'melbourne_streets.geojson'
roads.to_file(output, driver='GeoJSON')
print(f'Saved {len(roads):,} road segments to {output} ({output.stat().st_size / 1024:.0f} KB)')
print('Source: OpenStreetMap contributors — https://www.openstreetmap.org/copyright')
