"""Run from any directory: python scripts/prepare_all_charts.py
Uses existing preprocess_accessibility.py outputs. No web requests.
"""
from pathlib import Path
import json
import pandas as pd
import geopandas as gpd

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data'/'raw'; OUT=ROOT/'data'/'processed'
OUT.mkdir(parents=True,exist_ok=True)
summary=OUT/'melbourne_lga_summary_final.csv'
geom=OUT/'melbourne_lga_boundaries_final.geojson'
catfile=OUT/'green_space_by_category.csv'
for f in (summary,geom,catfile):
 if not f.exists(): raise FileNotFoundError(f'Missing {f}; run existing scripts/preprocess_accessibility.py first.')
s=pd.read_csv(summary,dtype={'lga_code':str})
g=gpd.read_file(geom)
c=pd.read_csv(catfile)
print('Loaded',len(s),'LGAs and',len(c),'category rows')

# rank change
r=s[['lga_name','everyday_parkland_ha','everyday_ha_per_1000']].copy()
r['rank_total']=r['everyday_parkland_ha'].rank(ascending=False,method='min').astype(int)
r['rank_per_1000']=r['everyday_ha_per_1000'].rank(ascending=False,method='min').astype(int)
a=r[['lga_name','rank_total','everyday_parkland_ha']].rename(columns={'rank_total':'rank','everyday_parkland_ha':'value'});a['measure']='Total parkland'
b=r[['lga_name','rank_per_1000','everyday_ha_per_1000']].rename(columns={'rank_per_1000':'rank','everyday_ha_per_1000':'value'});b['measure']='Per 1,000 residents'
pd.concat([a,b]).to_csv(OUT/'parkland_rank_comparison.csv',index=False)

# bivariate map using tertiles (density and percent everyday parkland)
ss=s.copy()
for key,var in [('density','population_density_km2'),('park','everyday_parkland_pct')]:
 ss[key+'_class']=pd.qcut(ss[var].rank(method='first'),3,labels=['Low','Medium','High']).astype(str)
ss['bivar_label']=ss['density_class']+' density / '+ss['park_class'].str.lower()+' parkland'
g=g.merge(ss[['lga_code','bivar_label']],on='lga_code',validate='one_to_one')
g[['geometry','lga_name','population_density_km2','everyday_parkland_pct','bivar_label']].to_file(OUT/'lga_bivariate.geojson',driver='GeoJSON')

# centroid CSV: approximate map point placement, not actual parks
proj=g.to_crs('EPSG:7855'); pts=proj.geometry.representative_point().to_crs('EPSG:4326')
cent=s[['lga_name','everyday_parkland_ha','walkable_land_pct']].merge(pd.DataFrame({'lga_name':g.lga_name,'longitude':pts.x,'latitude':pts.y}),on='lga_name')
cent.to_csv(OUT/'lga_centroids.csv',index=False)

# category stacked bars show all categories as percentage of sum of categories
c['total_ha']=c.groupby('lga_name')['area_ha'].transform('sum')
c['share_pct']=100*c['area_ha']/c['total_ha'].where(c['total_ha']!=0)
c.to_csv(OUT/'category_shares.csv',index=False)
# For chart 2, normalise by total municipality area, not raw hectares.
# Each cell can be compared across LGAs independently of municipality size.
category_land = c.merge(s[['lga_name','lga_area_km2']], on='lga_name', how='left', validate='many_to_one')
category_land['land_share_pct'] = 100 * category_land['area_ha'] / (category_land['lga_area_km2'] * 100)
if category_land['land_share_pct'].isna().any():
 raise ValueError('Missing LGA area in category calculation')
category_land.to_csv(OUT/'category_land_shares.csv',index=False)
print('Wrote category_land_shares.csv (municipality-normalised area)')

# compare broad and everyday
long=pd.concat([
 s[['lga_name','broad_green_pct']].rename(columns={'broad_green_pct':'value'}).assign(metric='Broad green space'),
 s[['lga_name','everyday_parkland_pct']].rename(columns={'everyday_parkland_pct':'value'}).assign(metric='Everyday parkland')])
long['sort_value']=long.lga_name.map(s.set_index('lga_name').broad_green_pct)
long.to_csv(OUT/'parkland_comparison_long.csv',index=False)

# raw parcel distribution. Select every 1 in 4 deterministic records for lighter charts.
rawfile=RAW/'VPA Melbourne Open Space Data.csv'
if rawfile.exists():
 p=pd.read_csv(rawfile,low_memory=False,usecols=['OS_TYPE','OS_STATUS','OS_ACCESS','OS_CATEGOR','HA'])
 p=p.loc[p.OS_TYPE.eq('Public open space') & p.OS_STATUS.eq('Existing') & p.OS_ACCESS.eq('Open')].copy()
 p['HA']=pd.to_numeric(p.HA,errors='coerce')
 p=p.loc[p.HA.between(.005,1e5)]
 p=p[['OS_CATEGOR','HA']].rename(columns={'OS_CATEGOR':'category','HA':'ha'})
 p=p.loc[p.groupby('category').cumcount().mod(4).eq(0)].reset_index(drop=True)
 p.to_csv(OUT/'park_parcels_sample.csv',index=False)
 print('Wrote parcel sample',len(p))
else: print('WARNING: raw VPA CSV absent; chart 03 requires it.')

# City of Melbourne playground points (parse geo_point_2d, which may be GeoJSON or lat/lon text)
pf=RAW/'City of Melbourne - Playgrounds.csv'
if pf.exists():
 p=pd.read_csv(pf,low_memory=False)
 def getxy(v):
  if pd.isna(v):return (None,None)
  try:
   z=json.loads(v)
   if isinstance(z,dict) and 'coordinates' in z:return z['coordinates'][0],z['coordinates'][1]
   if isinstance(z,list) and len(z)>1:return z[1],z[0]
  except (ValueError,TypeError):pass
  try:
   a,b=[float(x.strip()) for x in str(v).strip('[]()').split(',')[:2]]
   return (b,a) if abs(a)<=90 else (a,b)
  except (ValueError,IndexError):return None,None
 coords=p.geo_point_2d.apply(getxy)
 p['longitude']=coords.apply(lambda x:x[0]);p['latitude']=coords.apply(lambda x:x[1])
 p=p[p.longitude.between(140,150)&p.latitude.between(-40,-35)]
 p[['name','location_d','features','longitude','latitude']].to_csv(OUT/'playground_points.csv',index=False)
 print('Wrote playgrounds',len(p))
else: print('WARNING: playground CSV absent; chart 12 unavailable.')

# detailed 400m overlay, selected City of Melbourne LGA; requires raw GeoJSON
# This step is optional and may take ~1-3 minutes depending on computer.
try:
 import shapely
 rp=RAW/'VPA Melbourne Open Space Data.geojson'
 rc=RAW/'Public Open Space - Walkable Catchment 400m.geojson'
 if rp.exists() and rc.exists():
  mel=g.loc[g.lga_name.eq('Melbourne')].to_crs('EPSG:7855').geometry.iloc[0]
  for path,out,fields in [(rp,'local_open_space.geojson',['PARK_NAME','OS_CATEGOR','OS_TYPE','OS_STATUS','OS_ACCESS']), (rc,'local_catchments.geojson',[])]:
   src=gpd.read_file(path).to_crs('EPSG:7855')
   if 'OS_TYPE' in src:
    src=src.loc[src.OS_TYPE.eq('Public open space') & src.OS_STATUS.eq('Existing') & src.OS_ACCESS.eq('Open')].copy()
   src=src.loc[src.intersects(mel)].copy()
   src['geometry']=src.geometry.intersection(mel)
   src=src.loc[~src.geometry.is_empty]
   src=src[[*fields,'geometry']].to_crs('EPSG:4326')
   src['geometry']=src.geometry.simplify(0.00004,preserve_topology=True)
   src.to_file(OUT/out,driver='GeoJSON')
   print(out,len(src))
 else: print('Optional detailed overlay chart 13: original source GeoJSON files not present.')
except Exception as exc: print('Optional detailed overlay skipped:',exc)
print('Data for charts ready in',OUT)
