import os
import matplotlib.pyplot as plt
from matplotlib import patches as mpatches
from matplotlib import lines as mlines
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from scipy.stats import gaussian_kde
from shapely.geometry import Polygon
from Wisl_quert import query_drzewostany_uszk
from matplotlib_map_utils.core.north_arrow import north_arrow
from matplotlib_map_utils.core.scale_bar import scale_bar
import contextily as cx

# Układ obliczeniowy i wyświetlania: PUWG92 (EPSG:2180) - metryczny
CRS_OBLICZENIOWY = "EPSG:2180"
CRS_ZAPISU = "EPSG:4326"

# 95. percentyl wyodrębnia 5% siatki o najwyższym stosunku uszkodzeń do tła
PERCENTYL_RYZYKA = 95

# Próg minimalnego tła ustalony na 1% wartości maksymalnej tła
PROG_MIN_TLA = 0.01 

def uszkodzenia(nr_cykl: int = 1, prog_nasil_uszk: int = None, gatunek: str = None):
    res = query_drzewostany_uszk(nr_cykl=nr_cykl)
    if not res:
        print(f"Brak danych z bazy dla cyklu {nr_cykl}.")
        return

    df = pd.DataFrame(res, columns=['NR_PUNKTU', 'NR_PODPOW', 'GAT_PAN_PR','WSP_Z','NASIL_USZK', 'PRZYCZ_USZK'])
    df['NR_TRAKTU'] = df['NR_PUNKTU'].str[:-1]
    
    trakty = gpd.read_file('data/trakty_wsp.geojson')

    if gatunek is not None:
        df = df[df['GAT_PAN_PR'] == gatunek].copy()

    if df.empty:
        print(f"Brak danych po odfiltrowaniu dla gatunku w cyklu {nr_cykl}.")
        return

    tlo = df.groupby('NR_TRAKTU').agg({'WSP_Z':'sum'}).reset_index()

    if prog_nasil_uszk is not None:
        df_uszk_filtr = df[df['NASIL_USZK'] > prog_nasil_uszk].copy()
    else:
        df_uszk_filtr = df[df['NASIL_USZK'] > 0].copy()

    # OBLICZAMY WAGĘ ILOŚCIOWĄ: Udział powierzchni * Stopień nasilenia
    df_uszk_filtr['iloczyn_nasilenia'] = df_uszk_filtr['WSP_Z'] * df_uszk_filtr['NASIL_USZK']

    # Sumujemy iloczyny na poziomie każdego traktu
    df_uszk_trakty = df_uszk_filtr.groupby('NR_TRAKTU').agg(
        waga_uszk=('iloczyn_nasilenia', 'sum')
    ).reset_index()

    trakty['nr_traktu'] = trakty['nr_punktu'].astype(int).astype(str).str[:-1]
    trakty_geom = trakty[['nr_traktu', 'geometry']].copy()

    tlo['NR_TRAKTU'] = tlo['NR_TRAKTU'].astype(int).astype(str)
    df_uszk_trakty['NR_TRAKTU'] = df_uszk_trakty['NR_TRAKTU'].astype(int).astype(str)

    # ==============================================================================
    # 5. UTWORZENIE GEOPANDAS I PRZYGOTOWANIE WSPÓŁRZĘDNYCH DO KDE
    # ==============================================================================
    df_model = pd.merge(tlo, df_uszk_trakty, on='NR_TRAKTU', how='left')
    df_model['waga_uszk'] = df_model['waga_uszk'].fillna(0.0)
    df_model = df_model.rename(columns={'WSP_Z': 'waga_tlo'})

    gdf_model = trakty_geom.merge(df_model, left_on='nr_traktu', right_on='NR_TRAKTU', how='inner')
    
    gdf_model = gpd.GeoDataFrame(gdf_model, geometry='geometry', crs=trakty.crs).to_crs(CRS_OBLICZENIOWY)
    gdf_model = gdf_model[gdf_model.geometry.notnull() & (gdf_model['waga_tlo'] > 0)].copy()

    if len(gdf_model) < 5:
        print(f"Zbyt mało danych przestrzennych do wyznaczenia KDE (cykl {nr_cykl}, znaleziono: {len(gdf_model)}).")
        return

    coords = np.vstack([gdf_model.geometry.x, gdf_model.geometry.y])

    # ==============================================================================
    # 6. DEFINICJA SIATKI ORAZ GRANIC POLSKI
    # ==============================================================================
    poland = gpd.read_file("data/poland_land.geojson").to_crs(CRS_OBLICZENIOWY)
    poland_geom = poland.geometry.union_all()

    xmin, ymin, xmax, ymax = poland.total_bounds
    x_grid = np.linspace(xmin, xmax, 500)
    y_grid = np.linspace(ymin, ymax, 500)
    X, Y = np.meshgrid(x_grid, y_grid)
    positions = np.vstack([X.ravel(), Y.ravel()])

    # ==============================================================================
    # 7. OBLICZENIE KDE (TŁO I USZKODZENIA)
    # ==============================================================================
    kernel_tlo = gaussian_kde(coords, bw_method='scott', weights=gdf_model['waga_tlo'])
    f_tlo = kernel_tlo(positions).reshape(X.shape)

    mask_uszk = gdf_model['waga_uszk'] > 0
    if mask_uszk.sum() >= 3:
        coords_uszk = coords[:, mask_uszk]
        # WYMUSZENIE WSPÓŁCZYNNIKA WYGŁADZANIA TŁA DLA USZKODZEŃ
        bw_factor = kernel_tlo.factor
        kernel_uszk = gaussian_kde(coords_uszk, bw_method=bw_factor, weights=gdf_model.loc[mask_uszk, 'waga_uszk'])
        f_uszk = kernel_uszk(positions).reshape(X.shape)
    else:
        f_uszk = np.zeros_like(X)

    # ==============================================================================
    # 8. WYZNACZENIE ILORAZU RYZYKA I PERCENTYLA
    # ==============================================================================
    mask_polska = shapely.contains_xy(poland_geom, X, Y)
    f_uszk[~mask_polska] = np.nan
    f_tlo[~mask_polska] = np.nan

    # ZABEZPIECZENIE PRZED EFEKTAMI BRZEGOWYMI I ZEROWYMI WARTOŚCIAMI
    max_tla = np.nanmax(f_tlo)
    mask_niskie_tlo = f_tlo < (PROG_MIN_TLA * max_tla)

    with np.errstate(divide='ignore', invalid='ignore'):
        # Dodanie epsilon chroniącego przed dzieleniem przez rygorystyczne zero
        ryzyko = f_uszk / (f_tlo + 1e-12) 
        
    ryzyko[mask_niskie_tlo] = np.nan
    ryzyko_valid = ryzyko[~np.isnan(ryzyko)]

    if ryzyko_valid.size == 0:
        print(f"Brak poprawnych wartości ryzyka dla cyklu {nr_cykl}.")
        return

    prog_ryzyka = np.percentile(ryzyko_valid, PERCENTYL_RYZYKA)

    # ==============================================================================
    # 9. WIZUALIZACJA (MATPLOTLIB)
    # ==============================================================================
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')

    cf = ax.contourf(
        X, Y, ryzyko,
        cmap=plt.cm.autumn_r,
        levels=[prog_ryzyka, np.nanmax(ryzyko_valid)],
        alpha=0.6,
    )
    
    kde_color = cf.get_facecolor()[0] if hasattr(cf, 'get_facecolor') else cf.collections[0].get_facecolor()[0]

    ryzyko_contour = np.nan_to_num(ryzyko, nan=0.0)
    cs = ax.contour(
        X, Y, ryzyko_contour,
        levels=[prog_ryzyka],
        colors=['#8b0000'],
        linewidths=1.5,
    )

    polygons = []
    paths = cs.get_paths() if hasattr(cs, 'get_paths') else cs.collections[0].get_paths()
    for path in paths:
        for poly_pts in path.to_polygons():
            if len(poly_pts) >= 3:
                poly = Polygon(poly_pts)
                if not poly.is_valid:
                    poly = shapely.make_valid(poly)
                polygons.append(poly)

    zasieg_geom = shapely.union_all(polygons).buffer(0) if polygons else Polygon()

    gdf_model.plot(ax=ax, color='gray', markersize=3, alpha=0.3)
    gdf_model[mask_uszk].plot(ax=ax, color='red', markersize=8, alpha=0.7)
    poland.boundary.plot(ax=ax, color='black', linewidth=1)

    try:
        north_arrow(ax, location="upper left", rotation={"crs": poland.crs, "reference": "center"}, shadow=False, scale=0.4)
        scale_bar(ax, location="upper right", style="ticks", bar={"projection": poland.crs, "unit": "km"}, units={"loc": "bar"})
    except NameError:
        pass

    MARGIN = 20_000
    ax.set_xlim(xmin - MARGIN, xmax + MARGIN)
    ax.set_ylim(ymin - MARGIN, ymax + MARGIN)
    ax.grid(True, linestyle='--', alpha=0.5, color='gray')
    
    tytul_gatunek = f" | Gatunek: {gatunek}" if gatunek else ""
    nasil_opis = prog_nasil_uszk if prog_nasil_uszk is not None else 0
    ax.set_title(f"Ryzyko uszkodzeń (Cykl: {nr_cykl}, próg nasil. > {nasil_opis}){tytul_gatunek}", fontsize=11)
    ax.set_xlabel("X [m] (EPSG:2180)")
    ax.set_ylabel("Y [m] (EPSG:2180)")
    ax.ticklabel_format(style='plain', useOffset=False)
    
    try:
        cx.add_basemap(ax, crs=poland.crs, source=cx.providers.Esri.WorldGrayCanvas, alpha=1, zoom=8)
    except Exception:
        pass

    legend_elements = [
        mpatches.Patch(facecolor=kde_color, edgecolor='#8b0000', linewidth=1.5, alpha=0.6, label=f'Ryzyko wzg. ≥ {prog_ryzyka:.2f}×'),
        mlines.Line2D([], [], color='red', marker='o', linestyle='None', markersize=6, alpha=0.7, label='Trakt uszkodzony'),
        mlines.Line2D([], [], color='gray', marker='o', linestyle='None', markersize=4, alpha=0.4, label='Trakt badany (tło)'),
        mlines.Line2D([], [], color='black', linewidth=1, label='Granica Polski'),
    ]
    ax.legend(handles=legend_elements, loc='lower left', bbox_to_anchor=(0.01, 0.03), frameon=True, facecolor='white')

    # ==============================================================================
    # 10. ZAPIS WYNIKÓW
    # ==============================================================================
    if not os.path.exists("KDE_uszkodzenia"):
        os.makedirs("KDE_uszkodzenia")

    gdf_zasieg = gpd.GeoDataFrame(
        [{
            'cykl': nr_cykl,
            'gatunek': gatunek if gatunek else 'Wszystkie',
            'prog_nasilenia': prog_nasil_uszk if prog_nasil_uszk is not None else 0,
            'percentyl': PERCENTYL_RYZYKA,
            'prog_ryzyka': float(prog_ryzyka),
            'liczba_traktow': len(gdf_model),
        }],
        geometry=[zasieg_geom],
        crs=CRS_OBLICZENIOWY,
    )

    sufix_gat = f"_{gatunek}" if gatunek else ""
    sufix_nasil = f"_nasil{prog_nasil_uszk}" if prog_nasil_uszk is not None else ""
    
    file_prefix = f"ryzyko_cykl{nr_cykl}{sufix_gat}{sufix_nasil}"

    gdf_zasieg.to_crs(CRS_ZAPISU).to_file(
        f"KDE_uszkodzenia/{file_prefix}.geojson", driver="GeoJSON"
    )
    fig.savefig(f"KDE_uszkodzenia/{file_prefix}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Zakończono pomyślnie. Zapisano wyniki dla cyklu {nr_cykl}.")


if __name__ == "__main__":
    cykle = [1, 2, 3, 4]
    for cykl in cykle:
        uszkodzenia(nr_cykl=cykl, prog_nasil_uszk=3, gatunek=None)