"""Build a compact Melbourne major-roads GeoJSON from Geofabrik Victoria roads.

Run from project root:
    python scripts/prepare_geofabrik_roads.py

Requires: geopandas, shapely, pyproj
"""
from pathlib import Path
import json
import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
OUT = ROOT / 'data' / 'processed'
OUT.mkdir(parents=True, exist_ok=True)

ROADS_SHP = RAW / 'gis_osm_roads_free_1.shp'
LGA_GEOJSON = OUT / 'melbourne_lga_boundaries_final.geojson'
OUTPUT = OUT / 'melbourne_major_roads.geojson'

# Include only the three requested hierarchy levels and their links.
ALLOWED = {
    'motorway', 'motorway_link',
    'trunk', 'trunk_link',
    'primary', 'primary_link',
}
PROJECTED_CRS = 'EPSG:7855'  # metres in greater Melbourne
SIMPLIFY_METRES = 60
COORDINATE_PRECISION = 5

if not ROADS_SHP.exists():
    raise FileNotFoundError(f'Missing {ROADS_SHP}. Keep .dbf, .shx, .prj in same folder.')
if not LGA_GEOJSON.exists():
    raise FileNotFoundError(f'Missing study boundary {LGA_GEOJSON}')

print('1/5 Reading Melbourne study LGA boundaries...', flush=True)
lga = gpd.read_file(LGA_GEOJSON)
if lga.empty or lga.crs is None:
    raise ValueError('LGA boundary GeoJSON is empty or lacks a coordinate reference system.')
lga = lga.to_crs(PROJECTED_CRS)
# Exact union is small (~31 polygons) and quick.
study_boundary = lga.geometry.union_all()
# Add small buffer so lines along boundary remain visible.
study_boundary = study_boundary.buffer(75)
print(f'  Study LGAs: {len(lga)}', flush=True)

print('2/5 Reading roads within Melbourne bounding box...', flush=True)
# The source is likely EPSG:4326 but don't assume it.
source_crs = gpd.read_file(ROADS_SHP, rows=1).crs
if not source_crs:
    raise ValueError('Road shapefile has no coordinate system. Check its .prj file.')
study_bbox_src = gpd.GeoSeries([study_boundary], crs=PROJECTED_CRS).to_crs(source_crs).total_bounds
roads = gpd.read_file(ROADS_SHP, bbox=tuple(study_bbox_src))
print(f'  Road segments within bounding box (all classes): {len(roads):,}', flush=True)
if roads.empty:
    raise ValueError('No roads intersect bounding box. Check CRS and file.')

print('3/5 Filtering road classifications...', flush=True)
# Geofabrik free roads normally use 'fclass', with 'code' numeric as fallback.
class_col = next((c for c in ('fclass', 'highway') if c in roads.columns), None)
if class_col is None:
    raise ValueError(f'Cannot identify road class. Available fields: {roads.columns.tolist()}')
roads[class_col] = roads[class_col].astype('string').str.lower().str.strip()
print('  Available classifications:', roads[class_col].value_counts().head(16).to_dict(), flush=True)
roads = roads.loc[roads[class_col].isin(ALLOWED)].copy()
if roads.empty:
    raise ValueError('No motorway/trunk/primary roads found in the selected area.')
roads = roads.rename(columns={class_col:'osm_class'})
roads['road_class'] = roads['osm_class'].apply(
    lambda v: 'Motorway / trunk' if v.startswith(('motorway', 'trunk')) else 'Primary arterial'
)
roads = roads.to_crs(PROJECTED_CRS)
roads = roads.loc[roads.geometry.notna() & ~roads.geometry.is_empty].copy()
print(f'  Matching major-road segments: {len(roads):,}', flush=True)

print('4/5 Clipping to the study area and simplifying...', flush=True)
# Spatial index avoids processing geometries outside the dissolved study boundary.
roads = gpd.clip(roads, study_boundary, keep_geom_type=True)
roads = roads.loc[roads.geometry.notna() & ~roads.geometry.is_empty].copy()
roads['geometry'] = roads.geometry.simplify(SIMPLIFY_METRES, preserve_topology=True)
roads = roads.loc[~roads.geometry.is_empty].copy()
# Thin attributes to keep download small. Name can be useful for tooltips later.
if 'name' not in roads.columns:
    roads['name'] = ''
roads = roads[['name', 'road_class', 'geometry']].copy()
roads['name'] = roads['name'].fillna('').astype(str).str.slice(0, 100)
roads = roads.to_crs('EPSG:4326')
print(f'  Final segments: {len(roads):,}', flush=True)

print('5/5 Exporting GeoJSON...', flush=True)
# Save compact GeoJSON with rounded coordinates (uses GeoPandas to_json precision).
geojson_text = roads.to_json(drop_id=True, to_wgs84=True, show_bbox=False)
# GeoPandas to_json doesn't support fixed coordinate precision; recursively round.
obj = json.loads(geojson_text)
def round_coordinates(value):
    if isinstance(value, list):
        if value and isinstance(value[0], (int, float)):
            return [round(float(v), COORDINATE_PRECISION) for v in value]
        return [round_coordinates(v) for v in value]
    return value
for feature in obj['features']:
    feature['geometry']['coordinates'] = round_coordinates(feature['geometry']['coordinates'])
    feature['properties']['name'] = feature['properties'].get('name') or ''
OUTPUT.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
size_mb = OUTPUT.stat().st_size / (1024 * 1024)
print(f'  Saved: {OUTPUT}', flush=True)
print(f'  Size: {size_mb:.2f} MiB', flush=True)
print('  Breakdown:', roads['road_class'].value_counts().to_dict(), flush=True)
if size_mb > 2:
    print('  NOTE: Exceeds 2 MiB. Increase SIMPLIFY_METRES to 60 and rerun if needed.', flush=True)
print('Finished. Refresh parks-explorer.html using Ctrl+Shift+R.', flush=True)
