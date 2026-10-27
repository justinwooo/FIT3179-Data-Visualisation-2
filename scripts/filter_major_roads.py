"""Filter existing road GeoJSON without downloading new data.
Run: python scripts/filter_major_roads.py
If OSM highway classification is missing from the original file, secondary
and primary cannot be distinguished. In that case retain motorway/trunk only.
Creates backup on first run.
"""
from pathlib import Path
import json, shutil
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'data'/'processed'/'melbourne_major_roads.geojson'
backup=source.with_name('melbourne_major_roads_before_filter.geojson')
if not source.exists():
    raise FileNotFoundError(f'Missing road file: {source}')
if not backup.exists():
    shutil.copy2(source,backup)
obj=json.loads(backup.read_text(encoding='utf-8'))
features=obj.get('features',[])
with_highway=any('highway' in f.get('properties',{}) for f in features)
if with_highway:
    allowed={'motorway','motorway_link','trunk','trunk_link','primary','primary_link'}
    def keep(f):
        val=f.get('properties',{}).get('highway',[])
        vals=val if isinstance(val,list) else [val]
        return any(v in allowed for v in vals)
    selection='motorway, trunk, primary and their links'
else:
    # Older road GeoJSON kept only two aggregated classifications.
    # Keeping all "Metropolitan arterial" roads would still include secondary.
    def keep(f):
        return f.get('properties',{}).get('road_class')=='Highway/freeway'
    selection='motorway/trunk ONLY (source discarded the primary vs secondary distinction)'
obj['features']=[f for f in features if keep(f)]
source.write_text(json.dumps(obj,separators=(',',':')),encoding='utf-8')
print(f'Kept {len(obj["features"]):,}/{len(features):,} roads: {selection}')
print(f'Output: {source}, {source.stat().st_size/1e6:.2f} MB')
print('Optional: run prepare_major_roads_primary_only.py to obtain primary roads too, with internet.')
