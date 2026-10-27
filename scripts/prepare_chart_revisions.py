"""Prepare chart data for the FIT3179 revised figures 03, 04, and 06.
Run: python scripts/prepare_chart_revisions.py
Uses your original VPA CSV and validated LGA summary; no network calls.
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
OUT = ROOT / 'data' / 'processed'
OUT.mkdir(parents=True, exist_ok=True)

PARK_CATS = [
    'Parks and gardens',
    'Natural and semi-natural open space',
    'Recreation corridor',
    'Sportsfields and organised recreation',
]

# Same four-category open/existing/public rule as the green-space analysis.
source = RAW / 'VPA Melbourne Open Space Data.csv'
if not source.exists():
    raise FileNotFoundError(f'Missing {source}')
parks = pd.read_csv(source, usecols=['OS_TYPE','OS_ACCESS','OS_STATUS','OS_CATEGOR','HA','LGA'], low_memory=False)
parks['HA'] = pd.to_numeric(parks['HA'], errors='coerce')
parks = parks.loc[
    parks['OS_TYPE'].eq('Public open space')
    & parks['OS_ACCESS'].eq('Open')
    & parks['OS_STATUS'].eq('Existing')
    & parks['OS_CATEGOR'].isin(PARK_CATS)
    & parks['HA'].gt(0)
    & ~parks['LGA'].astype(str).str.upper().str.strip().eq('MITCHELL')
].copy()

# Viz 3: Full eligible parcel-size distribution, NOT a 1-in-4 sample.
parcels = parks[['OS_CATEGOR', 'HA']].rename(columns={'OS_CATEGOR':'category','HA':'ha'})
parcels.to_csv(OUT / 'park_parcels_four_types.csv', index=False, float_format='%.5f')

# Viz 4: Empirical cumulative share of records with area <= threshold.
# Use 150 log-spaced thresholds to keep the data extremely lightweight.
# Points describe the exact percentage below each threshold; smooth visual
# interpolation between sampled threshold values is not exact stepwise ECDF.
rows=[]
for name,grp in parks.groupby('OS_CATEGOR',sort=False):
    values=np.sort(grp['HA'].to_numpy(dtype=float))
    lower=max(values.min(),0.001)
    upper=values.max()
    edges=np.unique(np.r_[lower,np.geomspace(lower,upper,150),upper])
    counts=np.searchsorted(values,edges,side='right')
    for size,count in zip(edges,counts):
        rows.append({'category':name,'ha_threshold':round(float(size),6),
                     'cumulative_pct':round(float(count/len(values)*100),3),
                     'n_parcels':len(values)})
pd.DataFrame(rows).to_csv(OUT / 'park_area_cumulative.csv',index=False)

# Viz 6: Jittered distribution (one dot per LGA) of everyday hectares/1000,
# grouping LGAs by population density tertile. Jitter is deterministic.
summary_path=OUT/'melbourne_lga_summary_final.csv'
if not summary_path.exists():
    raise FileNotFoundError(f'Missing {summary_path}')
s=pd.read_csv(summary_path)
required=['lga_name','population_density_km2','everyday_ha_per_1000']
missing=set(required)-set(s.columns)
if missing:raise ValueError(f'LGA summary missing fields: {sorted(missing)}')
s=s.dropna(subset=required).copy().sort_values('lga_name').reset_index(drop=True)
s['density_group'] = pd.qcut(s['population_density_km2'].rank(method='first'),3,labels=['Low density','Medium density','High density']).astype(str)
levels={'Low density':0, 'Medium density':1, 'High density':2}
# Tight point jitter within each group, not a force-directed beeswarm.
# This keeps values exact while reducing overplotting in the vertical dimension.
s['y_position']=[levels[g]+(float(i*37%17)-8)/48 for i,g in enumerate(s['density_group'])]
s[['lga_name','population_density_km2','everyday_ha_per_1000','density_group','y_position']].to_csv(OUT/'parkland_density_dotstrip.csv',index=False)

for file in ['park_parcels_four_types.csv','park_area_cumulative.csv','parkland_density_dotstrip.csv']:
    path=OUT/file
    print(f'Created {file}: {path.stat().st_size/1024:.1f} KB')
print(f'Eligible parcel records: {len(parks):,}; LGAs: {len(s)}')
