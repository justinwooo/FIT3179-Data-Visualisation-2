"""FIT3179 DV2: municipality-level green-space and 400m catchment analysis.
Run from project root: python scripts/preprocess_accessibility.py
Requires pandas, geopandas, shapely>=2, pyproj.
"""
from pathlib import Path
import json
import time
import warnings

import pandas as pd
import geopandas as gpd
import shapely
from shapely.geometry import GeometryCollection
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
OUT = ROOT / 'data' / 'processed'
OUT.mkdir(parents=True, exist_ok=True)

CRS_AREA = 'EPSG:7855'  # GDA2020 / MGA Zone 55, metres around Melbourne
BROAD_CATEGORIES = [
    'Parks and gardens',
    'Sportsfields and organised recreation',
    'Recreation corridor',
    'Natural and semi-natural open space',
]
EVERYDAY_CATEGORIES = [
    'Parks and gardens',
    'Sportsfields and organised recreation',
]
EXCLUDED_LGAS = {'Mitchell'}


def load_geo(path):
    if not path.exists():
        raise FileNotFoundError(f'Missing file: {path}')
    g = gpd.read_file(path)
    if g.crs is None:
        raise ValueError(f'Missing CRS: {path.name}')
    return g.to_crs(CRS_AREA)


def valid_polygons(g):
    g = g.loc[g.geometry.notna() & ~g.geometry.is_empty].copy()
    invalid = (~g.geometry.is_valid).sum()
    if invalid:
        print(f'  Fixing {invalid} invalid geometries')
        g['geometry'] = g.geometry.make_valid()
    g = g.loc[~g.geometry.is_empty].copy()
    return g


def union_clipped_area(source, boundary, *, label):
    """Return union area (m²) of input geometries intersected with a single LGA.

    Spatial index reduces the number of costly intersection operations.
    """
    hits = list(source.sindex.query(boundary, predicate='intersects'))
    if not hits:
        return 0.0, 0
    fragments = []
    for geom in source.geometry.iloc[hits]:
        part = geom.intersection(boundary)
        if not part.is_empty:
            fragments.append(part)
    if not fragments:
        return 0.0, len(hits)
    # union_all removes overlaps; no simplifying before the measurement.
    merged = shapely.union_all(fragments)
    return float(merged.area), len(hits)


def main():
    start = time.time()
    print('1/5 Reading inputs ...', flush=True)
    base = pd.read_csv(OUT / 'melbourne_lga_summary.csv', dtype={'lga_code': str})
    base = base.loc[~base['lga_name'].isin(EXCLUDED_LGAS)].copy()
    if base.empty or base['lga_code'].duplicated().any():
        raise ValueError('LGA summary is empty or contains duplicate codes.')
    codes = set(base['lga_code'])

    shp = (RAW / 'LGA_2021_AUST_GDA2020_SHP' /
           'LGA_2021_AUST_GDA2020.shp')
    lga = load_geo(shp)
    lga['LGA_CODE21'] = lga['LGA_CODE21'].astype(str)
    lga = lga.loc[lga['LGA_CODE21'].isin(codes),
                  ['LGA_CODE21', 'LGA_NAME21', 'geometry']].copy()
    if len(lga) != len(base):
        raise ValueError(f'Expected {len(base)} boundaries, got {len(lga)}.')
    lga = valid_polygons(lga)
    lga['lga_code'] = lga['LGA_CODE21']

    parks = load_geo(RAW / 'VPA Melbourne Open Space Data.geojson')
    for col in ['OS_TYPE', 'OS_ACCESS', 'OS_STATUS', 'OS_CATEGOR']:
        if col not in parks:
            raise ValueError(f'Open-space GeoJSON missing {col}')
        parks[col] = parks[col].astype('string').str.strip()
    print('  Source classes:', parks['OS_TYPE'].value_counts().head(8).to_dict())
    eligible = parks.loc[
        (parks['OS_TYPE'] == 'Public open space') &
        (parks['OS_ACCESS'] == 'Open') &
        (parks['OS_STATUS'] == 'Existing') &
        (parks['OS_CATEGOR'].isin(BROAD_CATEGORIES))
    ].copy()
    eligible = valid_polygons(eligible)
    print(f'  Eligible park parcels: {len(eligible):,}', flush=True)
    if eligible.empty:
        raise ValueError('No eligible polygons. Check status/type/access values.')

    catchments = load_geo(
        RAW / 'Public Open Space - Walkable Catchment 400m.geojson'
    )
    catchments = valid_polygons(catchments)
    print(f'  Catchment polygons: {len(catchments):,}', flush=True)

    print('2/5 Spatial calculations by LGA ...', flush=True)
    rows = []
    category_rows = []
    for i, (_, r) in enumerate(lga.iterrows(), start=1):
        boundary = r.geometry
        code = r['lga_code']
        name = r['LGA_NAME21']
        lga_area = boundary.area
        broad_m2, n_broad = union_clipped_area(eligible, boundary, label='broad')
        everyday = eligible.loc[eligible['OS_CATEGOR'].isin(EVERYDAY_CATEGORIES)]
        everyday_m2, n_everyday = union_clipped_area(everyday, boundary, label='everyday')
        catchment_m2, n_catch = union_clipped_area(catchments, boundary, label='access')
        rows.append({
            'lga_code': code,
            'broad_green_space_ha': broad_m2 / 10000,
            'everyday_parkland_ha': everyday_m2 / 10000,
            'walkable_catchment_ha': catchment_m2 / 10000,
            'broad_green_pct': 100 * broad_m2 / lga_area,
            'everyday_parkland_pct': 100 * everyday_m2 / lga_area,
            'walkable_land_pct': 100 * catchment_m2 / lga_area,
            'park_parcels_intersecting': n_broad,
            'catchment_polygons_intersecting': n_catch,
            'lga_geometry_area_km2': lga_area / 1e6,
        })
        for category in BROAD_CATEGORIES:
            subset = eligible.loc[eligible['OS_CATEGOR'] == category]
            area, n = union_clipped_area(subset, boundary, label=category)
            category_rows.append({
                'lga_code': code, 'lga_name': name, 'category': category,
                'area_ha': area / 10000, 'intersecting_parcels': n,
            })
        print(f'  [{i:02d}/{len(lga)}] {name}: broad={broad_m2/10000:,.1f} ha; '
              f'everyday={everyday_m2/10000:,.1f} ha; '
              f'400m land coverage={100*catchment_m2/lga_area:.1f}%', flush=True)

    spatial = pd.DataFrame(rows)
    result = base.merge(spatial, on='lga_code', how='left', validate='one_to_one')
    result['broad_ha_per_1000'] = (
        result['broad_green_space_ha'] / result['population_2021'] * 1000
    )
    result['everyday_ha_per_1000'] = (
        result['everyday_parkland_ha'] / result['population_2021'] * 1000
    )
    # Keep original summed-area estimates with a clear name for QA.
    result = result.rename(columns={
        'green_space_ha': 'preliminary_sum_ha',
        'green_space_pct': 'preliminary_sum_pct',
        'green_ha_per_1000': 'preliminary_sum_ha_per_1000',
    })

    print('3/5 Quality checks ...', flush=True)
    for measure in ['broad_green_pct', 'everyday_parkland_pct', 'walkable_land_pct']:
        if result[measure].isna().any() or not result[measure].between(0, 100.001).all():
            raise ValueError(f'Unexpected percentage values in {measure}')
    if (result['everyday_parkland_ha'] > result['broad_green_space_ha'] + 1e-5).any():
        raise ValueError('Everyday space should not exceed broad space.')
    result['area_difference_pct'] = (
        100 * (result['broad_green_space_ha'] - result['preliminary_sum_ha']) /
        result['preliminary_sum_ha'].replace(0, float('nan'))
    )
    result.to_csv(OUT / 'melbourne_lga_summary_final.csv', index=False)
    pd.DataFrame(category_rows).to_csv(
        OUT / 'green_space_by_category.csv', index=False
    )
    result[['lga_code', 'lga_name', 'walkable_catchment_ha',
            'walkable_land_pct', 'catchment_polygons_intersecting']].to_csv(
        OUT / 'accessibility_summary.csv', index=False
    )

    print('4/5 Exporting lightweight GeoJSON ...', flush=True)
    export = lga[['lga_code', 'geometry']].merge(
        result.drop(columns=['lga_geometry_area_km2']),
        on='lga_code', validate='one_to_one'
    )
    export['geometry'] = export.geometry.simplify(75, preserve_topology=True)
    export = export.to_crs('EPSG:4326')
    export.to_file(OUT / 'melbourne_lga_boundaries_final.geojson', driver='GeoJSON')

    print('5/5 Writing diagnostics ...', flush=True)
    deviations = result.loc[result['area_difference_pct'].abs() > 5,
                            ['lga_name', 'preliminary_sum_ha',
                             'broad_green_space_ha', 'area_difference_pct']]
    geojson_size = (OUT / 'melbourne_lga_boundaries_final.geojson').stat().st_size
    diag = [
        'FIT3179 GREEN SPACE PREPROCESSING DIAGNOSTICS',
        f'LGAs analysed: {len(result)} (Mitchell excluded)',
        f'Eligible VPA polygon records: {len(eligible)}',
        f'400m catchment polygon records: {len(catchments)}',
        f'GeoJSON size: {geojson_size / 1024:.1f} KiB',
        'Area calculations: EPSG:7855, spatial intersections + union.',
        'Walkability: % of LGA land inside catchment, NOT % of people.',
        'Everyday category set: parks/gardens + sportsfields.',
        'Broad includes natural/semi-natural areas and recreation corridors.',
        'LIMITATIONS: park and catchment source dates may differ from 2021 Census;',
        'LGA boundaries are ABS 2021; data coverage may vary in fringe LGAs.',
        'Check whether catchment geometries represent valid pedestrian walk access.',
        'Individual-category union areas should not be added to obtain broad area',
        'if categories overlap geographically.',
        '',
        'AREA DEVIATIONS > 5% FROM PRELIMINARY SUM:',
        deviations.to_string(index=False) if len(deviations) else 'None',
        '',
        'TOP FIVE EVERYDAY PARKLAND %:',
        result.nlargest(5, 'everyday_parkland_pct')[
            ['lga_name', 'everyday_parkland_pct']].to_string(index=False),
        '',
        'BOTTOM FIVE WALKABLE LAND COVERAGE %:',
        result.nsmallest(5, 'walkable_land_pct')[
            ['lga_name', 'walkable_land_pct']].to_string(index=False),
    ]
    (OUT / 'preprocessing_diagnostics.txt').write_text(
        '\n'.join(diag), encoding='utf-8'
    )
    print('\n'.join(diag[-10:]))
    print(f'Finished in {time.time()-start:.1f} s.')
    print(f'Outputs: {OUT}')


if __name__ == '__main__':
    main()
