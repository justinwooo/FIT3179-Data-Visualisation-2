"""Build a robust, clipped, simplified recreational open-space GeoJSON.
Run from the project root: python scripts/prepare_parks_explorer.py
Source: VPA public open-space polygons, ABS LGA boundaries. Does not change raw data.
"""
from pathlib import Path
import json, re
import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping
from shapely.ops import orient

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
OUT = ROOT / 'data' / 'processed'
OUT.mkdir(parents=True, exist_ok=True)
MAX_MB = 4.0  # byte-size target for park polygons; leave space for roads + other charts
MIN_HA = 1.0  # change to 0.25 if you want smaller neighbourhood parks
CATEGORIES = {
 'Parks and gardens': 'Parks and gardens',
 'Natural and semi-natural open space': 'Natural and semi-natural open space',
 'Recreation corridor': 'Recreation corridors',
 'Sportsfields and organised recreation': 'Sportsfields and organised recreation',
}

def normalise(s):
    s = re.sub(r'\s*\([^)]*\)', '', str(s).upper())
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return {'MORNINGTON':'MORNINGTON PENINSULA'}.get(s,s)

def round_coords(value):
    if isinstance(value, (float,int)):
        return round(float(value),5)
    if isinstance(value, (list,tuple)):
        return [round_coords(x) for x in value]
    return value

print('1/5 Reading VPA polygons and ABS LGA polygons...')
parks = gpd.read_file(RAW/'VPA Melbourne Open Space Data.geojson')
lgas = gpd.read_file(RAW/'LGA_2021_AUST_GDA2020_SHP'/'LGA_2021_AUST_GDA2020.shp')
for c in ['OS_CATEGOR','OS_TYPE','OS_ACCESS','OS_STATUS']:
    parks[c] = parks[c].fillna('').astype(str).str.strip()
parks = parks.loc[
    parks['OS_CATEGOR'].isin(CATEGORIES) &
    parks['OS_TYPE'].eq('Public open space') &
    parks['OS_ACCESS'].eq('Open') &
    parks['OS_STATUS'].eq('Existing') &
    parks.geometry.notna() & ~parks.geometry.is_empty
].copy()
# Exclude exactly named Plenty River records (case-sensitive exact string).
# This is a map-only display exclusion, not a change to analytical summaries.
plenty_count = parks['PARK_NAME'].fillna('').astype(str).eq('Plenty River').sum()
parks = parks.loc[~parks['PARK_NAME'].fillna('').astype(str).eq('Plenty River')].copy()
print(f'  Excluded {plenty_count} records with PARK_NAME exactly Plenty River')
parks['lga_key'] = parks['LGA'].map(normalise)
parks = parks.loc[parks['lga_key'].ne('MITCHELL')].copy()
lgas = lgas.loc[lgas['STE_NAME21'].eq('Victoria')].copy()
lgas['lga_key'] = lgas['LGA_NAME21'].map(normalise)
lgas = lgas.loc[lgas.lga_key.isin(parks.lga_key.unique())].copy()
if set(parks.lga_key)-set(lgas.lga_key):
    raise ValueError('Unmatched LGAs: '+str(set(parks.lga_key)-set(lgas.lga_key)))
parks = parks.to_crs(epsg=7855)
lgas = lgas.to_crs(epsg=7855)
if (~parks.geometry.is_valid).any():
    print('  Repairing invalid park geometries')
    parks.geometry = parks.geometry.make_valid()
if (~lgas.geometry.is_valid).any():
    lgas.geometry = lgas.geometry.make_valid()
boundaries = dict(zip(lgas.lga_key,lgas.geometry))

print('2/5 Clipping parks to matching council boundaries and removing anomalies...')
records = []
skipped_huge = 0
skipped_small = 0
skipped_outside = 0
for item in parks.itertuples(index=False):
    key = item.lga_key
    boundary = boundaries[key]
    shape = item.geometry
    # An erroneously giant VPA polygon can hide the whole map.
    # Reject source geometry exceeding twice the entire council area.
    if shape.area > 2.0*boundary.area:
        skipped_huge += 1
        continue
    if not shape.intersects(boundary):
        skipped_outside += 1
        continue
    clipped = shape.intersection(boundary)
    if clipped.is_empty:
        skipped_outside += 1
        continue
    clipped_area = clipped.area/10000.0
    if clipped_area < MIN_HA:
        skipped_small += 1
        continue
    # Retain multipart polygon members but exclude artefactual lines/points.
    geoms = [clipped] if clipped.geom_type in ('Polygon','MultiPolygon') else [g for g in getattr(clipped,'geoms',[]) if g.geom_type in ('Polygon','MultiPolygon')]
    if not geoms:
        continue
    raw_name = getattr(item,'PARK_NAME',None)
    name = str(raw_name).strip() if pd.notna(raw_name) else ''
    if not name or name.lower() in ('none','nan','null'):
        name = 'Unnamed public open space'
    for g in geoms:
        if g.area/10000 < MIN_HA:
            continue
        records.append((g,{
            'name':name[:95],
            'category':CATEGORIES[item.OS_CATEGOR],
            'lga':str(item.LGA).strip(),
            'lga_key':key,
            'area_ha':round(g.area/10000,2)
        }))
print(f'  Retained {len(records):,} polygon records >= {MIN_HA:g} ha')
print(f'  Rejected: {skipped_huge} oversized anomalies, {skipped_small} under threshold, {skipped_outside} outside assigned municipality')

print('3/5 Simplifying and sizing GeoJSON...')
outpath = OUT/'parks_explorer.geojson'
for tolerance in [8,15,25,40,60,90,130,180,240,320,450,650]:
    shapes = gpd.GeoSeries([g for g,p in records], crs='EPSG:7855').simplify(tolerance,preserve_topology=True).to_crs(epsg=4326)
    feats=[]
    for geom,(_,props) in zip(shapes,records):
        if geom is None or geom.is_empty:
            continue
        # Vega/D3 geographic rendering expects clockwise outer rings.
        # Shapely orient handles Polygon and MultiPolygon geometries.
        geom = orient(geom, sign=-1.0)
        mapped = mapping(geom)
        feats.append({'type':'Feature','properties':props,'geometry':{'type':mapped['type'],'coordinates':round_coords(mapped['coordinates'])}})
    outpath.write_text(json.dumps({'type':'FeatureCollection','features':feats},separators=(',',':')),encoding='utf-8')
    size=outpath.stat().st_size/1e6
    print(f'  tolerance={tolerance} m; {len(feats):,} features; {size:.2f} MB')
    if size <= MAX_MB:break
if size > MAX_MB:
    print(f'WARNING: parks GeoJSON is {size:.2f} MB, above the {MAX_MB} MB target. Review simplification.')

print('4/5 Writing municipality focus extents...')
focus=[{'label':'All Melbourne','value':'ALL','bounds':[144.15,-38.65,146.35,-37.30]}]
for r in lgas.to_crs(epsg=4326).sort_values('LGA_NAME21').itertuples(index=False):
    w,s,e,n=r.geometry.bounds
    focus.append({'label':str(r.LGA_NAME21),'value':r.lga_key,'bounds':[round(w,6),round(s,6),round(e,6),round(n,6)]})
(OUT/'parks_explorer_focus.json').write_text(json.dumps(focus,indent=2),encoding='utf-8')
print('5/6 Generating municipality label positions...')
# Only a selection of labels will be displayed in the metro overview;
# all labels are available once zoomed in.
METRO_LABELS = {'MELBOURNE', 'MONASH', 'BOROONDARA', 'BRIMBANK', 'WYNDHAM',
                'CASEY', 'HUME', 'WHITTLESEA', 'YARRA RANGES', 'MORNINGTON PENINSULA',
                'MELTON', 'NILLUMBIK'}
labels=[]
for item in lgas.itertuples(index=False):
    pt = item.geometry.representative_point()  # guaranteed inside municipality
    ll = gpd.GeoSeries([pt],crs='EPSG:7855').to_crs(4326).iloc[0]
    labels.append({'lga_key':item.lga_key, 'name':item.LGA_NAME21,
                   'lon':round(ll.x,6), 'lat':round(ll.y,6),
                   'metro_label': item.lga_key in METRO_LABELS})
(OUT/'parks_explorer_labels.json').write_text(json.dumps(labels,separators=(',',':')), encoding='utf-8')
print('6/6 Complete. Files:',outpath.name,'parks_explorer_focus.json, parks_explorer_labels.json')
print('NOTE: 1 ha is a display filter, not a definition of what qualifies as a park.')
