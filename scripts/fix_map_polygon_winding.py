"""Fix polygon winding for Vega/D3 geoshape without regenerating VPA data.
Run: python scripts/fix_map_polygon_winding.py
Creates .backup.geojson files before overwriting.
"""
from pathlib import Path
import json
from shapely.geometry import shape, mapping
from shapely.ops import orient

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / 'data' / 'processed'
NAMES = ['parks_explorer.geojson', 'melbourne_lga_boundaries_final.geojson']

for name in NAMES:
    path = DIR / name
    if not path.exists():
        print('SKIP (not found):', path)
        continue
    obj = json.loads(path.read_text(encoding='utf-8'))
    before = 0
    after = 0
    changed = 0
    for feat in obj['features']:
        geo = feat.get('geometry')
        if not geo or geo.get('type') not in ('Polygon', 'MultiPolygon'):
            continue
        geom = shape(geo)
        if geom.is_empty:
            continue
        before += 1
        # D3 geoshape needs CLOCKWISE outer rings and counterclockwise holes.
        # This is intentionally opposite RFC-7946 GeoJSON winding.
        rewound = orient(geom, sign=-1.0)
        new_geo = mapping(rewound)
        if geo['coordinates'] != new_geo['coordinates']:
            changed += 1
        feat['geometry'] = new_geo
        after += 1
    backup = DIR / name.replace('.geojson', '.backup.geojson')
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
    path.write_text(json.dumps(obj, separators=(',', ':')), encoding='utf-8')
    print(f'{name}: {after} polygons checked; {changed} rewound; saved {path.stat().st_size/1e6:.2f} MB')
print('Done. Reload Live Server with Ctrl+Shift+R.')
