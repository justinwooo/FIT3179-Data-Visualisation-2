
from pathlib import Path
import re
import pandas as pd
import geopandas as gpd

# ==================================================
# PATHS
# ==================================================

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

OUT.mkdir(parents=True, exist_ok=True)

# ==================================================
# SETTINGS
# ==================================================

# Starting definition of recreational green space.
# These categories may be adjusted after reviewing
# the first results.

PARK_CATEGORIES = [
    "Parks and gardens",
    "Sportsfields and organised recreation",
    "Recreation corridor",
    "Natural and semi-natural open space"
]

# Older and abbreviated council names in the VPA
# data must be matched against 2021 ABS LGA names.
#
# Moreland was renamed Merri-bek in 2022.
# The ABS 2021 name is expected to be Moreland.

NAME_ALIASES = {
    "MORNINGTON": "MORNINGTON PENINSULA",
}

# ==================================================
# HELPER FUNCTIONS
# ==================================================

def clean_name(value):
    """Standardise municipality names for matching."""

    if pd.isna(value):
        return ""

    name = str(value).upper().strip()

    # Remove ABS council type suffix, e.g. (C), (S)
    name = re.sub(r"\s*\([^)]*\)", "", name)

    # Standardise punctuation and whitespace
    name = re.sub(r"[^A-Z0-9 ]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()

    return NAME_ALIASES.get(name, name)


# ==================================================
# 1. READ INPUTS
# ==================================================

print("Loading input files...")

parks = pd.read_csv(
    RAW / "VPA Melbourne Open Space Data.csv",
    low_memory=False
)

population = pd.read_csv(
    RAW / "VIC_LGA_2021_census_population_clean.csv",
    dtype={"lga_code_2021": str}
)

lga = gpd.read_file(
    RAW
    / "LGA_2021_AUST_GDA2020_SHP"
    / "LGA_2021_AUST_GDA2020.shp"
)

print(f"Open-space records: {len(parks):,}")
print(f"Census population records: {len(population):,}")
print(f"ABS LGA boundary records: {len(lga):,}")

# ==================================================
# 2. FILTER RECREATIONAL PUBLIC GREEN SPACE
# ==================================================

print("\nFiltering public recreational green space...")

parks["HA"] = pd.to_numeric(
    parks["HA"], errors="coerce"
)

parks["lga_key"] = parks["LGA"].apply(clean_name)

parks_filtered = parks.loc[
    (parks["OS_TYPE"] == "Public open space")
    & (parks["OS_ACCESS"] == "Open")
    & (parks["OS_STATUS"] == "Existing")
    & (parks["OS_CATEGOR"].isin(PARK_CATEGORIES))
    & (parks["HA"] > 0)
].copy()

print(f"Selected spatial records: {len(parks_filtered):,}")

# Do not call these records individual parks.
# A park can be represented by multiple parcels.

print("\nSelected categories:")
print(parks_filtered["OS_CATEGOR"].value_counts())

# ==================================================
# 3. AGGREGATE BY MUNICIPALITY
# ==================================================

green_summary = (
    parks_filtered
    .groupby("lga_key", as_index=False)
    .agg(
        green_space_ha=("HA", "sum"),
        open_space_records=("HA", "size"),
        median_parcel_ha=("HA", "median")
    )
)

# Separate dataset for category-based charts.

category_summary = (
    parks_filtered
    .groupby(
        ["lga_key", "OS_CATEGOR"],
        as_index=False
    )
    .agg(
        area_ha=("HA", "sum"),
        parcel_records=("HA", "size")
    )
    .rename(columns={
        "OS_CATEGOR": "category"
    })
)

category_summary.to_csv(
    OUT / "open_space_categories.csv",
    index=False
)

# ==================================================
# 4. PREPARE ABS LGA BOUNDARIES
# ==================================================

print("\nPreparing ABS LGA boundaries...")

vic_lga = lga.loc[
    lga["STE_NAME21"] == "Victoria"
].copy()

vic_lga["lga_key"] = (
    vic_lga["LGA_NAME21"].apply(clean_name)
)

# Use the VPA dataset's municipality list
# to identify the LGAs covered by the study.

study_keys = set(parks["lga_key"].dropna())

study_lga = vic_lga.loc[
    vic_lga["lga_key"].isin(study_keys)
].copy()

matched_keys = set(study_lga["lga_key"])

unmatched = sorted(study_keys - matched_keys)

if unmatched:
    print("\nUnmatched VPA LGA names:")
    for name in unmatched:
        print(" -", name)

    raise ValueError(
        "Resolve unmatched LGA names before continuing."
    )

print(f"Matched LGAs: {len(study_lga)}")

# ==================================================
# 5. JOIN POPULATION AND GREEN SPACE
# ==================================================

print("\nJoining Census population...")

# ABS codes are stored as LGA20110 etc. in the
# cleaned Census dataset.

population["lga_code"] = (
    population["lga_code_2021"]
    .str.replace("LGA", "", regex=False)
)

study_lga["lga_code"] = (
    study_lga["LGA_CODE21"].astype(str)
)

study_lga = study_lga.merge(
    population[
        [
            "lga_code",
            "population_2021",
            "median_age_2021",
            "age_0_14_2021",
            "age_65_plus_2021"
        ]
    ],
    on="lga_code",
    how="left",
    validate="one_to_one"
)

study_lga = study_lga.merge(
    green_summary,
    on="lga_key",
    how="left",
    validate="one_to_one"
)

# A municipality with no matching eligible parks
# should have zero selected area, not an unknown
# population or boundary.

for col in [
    "green_space_ha",
    "open_space_records"
]:
    study_lga[col] = study_lga[col].fillna(0)

# ==================================================
# 6. VALIDATE JOINS
# ==================================================

if study_lga["population_2021"].isna().any():
    missing = study_lga.loc[
        study_lga["population_2021"].isna(),
        "LGA_NAME21"
    ].tolist()

    raise ValueError(
        f"Missing population for: {missing}"
    )

if (study_lga["population_2021"] <= 0).any():
    raise ValueError("Invalid population values found.")

# ==================================================
# 7. CALCULATE INDICATORS
# ==================================================

print("\nCalculating indicators...")

study_lga["lga_area_km2"] = pd.to_numeric(
    study_lga["AREASQKM21"], errors="coerce"
)

if (
    study_lga["lga_area_km2"].isna().any()
    or (study_lga["lga_area_km2"] <= 0).any()
):
    raise ValueError("Invalid LGA area values.")

study_lga["green_space_pct"] = (
    study_lga["green_space_ha"]
    / (study_lga["lga_area_km2"] * 100)
    * 100
)

study_lga["green_ha_per_1000"] = (
    study_lga["green_space_ha"]
    / study_lga["population_2021"]
    * 1000
)

study_lga["population_density_km2"] = (
    study_lga["population_2021"]
    / study_lga["lga_area_km2"]
)

study_lga["children_pct"] = (
    study_lga["age_0_14_2021"]
    / study_lga["population_2021"]
    * 100
)

study_lga["older_residents_pct"] = (
    study_lga["age_65_plus_2021"]
    / study_lga["population_2021"]
    * 100
)

# ==================================================
# 8. CHECK FOR SUSPICIOUS VALUES
# ==================================================

print("\nChecking calculated indicators...")

suspicious = study_lga.loc[
    (study_lga["green_space_pct"] < 0)
    | (study_lga["green_space_pct"] > 100),
    ["LGA_NAME21", "green_space_pct"]
]

if not suspicious.empty:
    print("WARNING: Suspicious green-space percentages:")
    print(suspicious.to_string(index=False))

# ==================================================
# 9. EXPORT SUMMARY CSV
# ==================================================

summary_columns = {
    "LGA_NAME21": "lga_name",
    "LGA_CODE21": "lga_code",
    "population_2021": "population_2021",
    "median_age_2021": "median_age_2021",
    "lga_area_km2": "lga_area_km2",
    "green_space_ha": "green_space_ha",
    "green_space_pct": "green_space_pct",
    "green_ha_per_1000": "green_ha_per_1000",
    "population_density_km2": "population_density_km2",
    "open_space_records": "open_space_records",
    "median_parcel_ha": "median_parcel_ha",
    "children_pct": "children_pct",
    "older_residents_pct": "older_residents_pct",
}

summary = (
    study_lga[list(summary_columns.keys())]
    .rename(columns=summary_columns)
    .sort_values("lga_name")
)

summary.to_csv(
    OUT / "melbourne_lga_summary.csv",
    index=False
)


# ==================================================
# 10. EXPORT LIGHTWEIGHT GEOJSON
# ==================================================

print("\nExporting simplified geographic boundaries...")

# Start with only the original LGA identifiers
# and geometry to avoid duplicate columns.

map_lga = study_lga[
    ["LGA_CODE21", "geometry"]
].copy()

# Convert to projected CRS for simplification.
map_lga = map_lga.to_crs(epsg=7855)

# Simplify boundaries with a 75-metre tolerance.
map_lga["geometry"] = (
    map_lga.geometry.simplify(
        tolerance=75,
        preserve_topology=True
    )
)

# Convert to WGS84 for Vega-Lite GeoJSON.
map_lga = map_lga.to_crs(epsg=4326)

# Merge the calculated summary statistics.
map_lga = map_lga.merge(
    summary,
    left_on="LGA_CODE21",
    right_on="lga_code",
    how="left",
    validate="one_to_one"
)

# Keep only the fields needed for Vega-Lite.
map_columns = ["geometry"] + list(summary.columns)

map_lga = map_lga[map_columns]

# Export GeoJSON.
map_lga.to_file(
    OUT / "melbourne_lga_boundaries.geojson",
    driver="GeoJSON"
)

print(
    f"GeoJSON exported successfully: {len(map_lga)} LGAs"
)


# ==================================================
# 11. FINAL REPORT
# ==================================================

print("\n" + "=" * 50)
print("PREPROCESSING COMPLETE")
print("=" * 50)

print(f"Municipalities: {len(summary)}")
print(f"Eligible open-space records: {len(parks_filtered):,}")

print("\nGreen-space area range (ha):")
print(
    summary["green_space_ha"].agg(["min", "max"])
)

print("\nHighest green-space percentages:")
print(
    summary.nlargest(5, "green_space_pct")[
        ["lga_name", "green_space_pct"]
    ].to_string(index=False)
)

print("\nOutput files:")
for file in sorted(OUT.iterdir()):
    if file.is_file():
        print(f" - {file.name}")

print("\nIMPORTANT:")
print(
    "Green-space areas are sums of the VPA HA field. "
    "Check parcel overlap, geographic coverage and "
    "land classification before publication."
)
print(
    "The VPA study area may include municipalities "
    "that are only partly within metropolitan Melbourne."
)
