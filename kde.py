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
from heatmap_data import heatmap_gatunki
from Wisl_quert import query_udzial_gat
from matplotlib_map_utils.core.north_arrow import north_arrow
from matplotlib_map_utils.core.scale_bar import scale_bar
import contextily as cx

# Układ obliczeniowy i wyświetlania: PUWG92 (EPSG:2180) - metryczny
CRS_OBLICZENIOWY = "EPSG:2180"
CRS_ZAPISU = "EPSG:4326"

def plot_kde_for_species(gat, cykl=4, drzewostany=True):

    # 1. Inicjalizacja standardowej figury Matplotlib
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')  # Wymuszenie proporcji 1:1 (mapa nie zostanie rozciągnięta)
    
    # 2. Wczytanie granic Polski i konwersja do układu metrycznego
    poland = gpd.read_file("data/poland_land.geojson").to_crs(CRS_OBLICZENIOWY)
    poland_geom = poland.geometry.union_all()

    udzal_gat = query_udzial_gat(gat, cykl)
    heat_data = heatmap_gatunki(udzal_gat, cykl=cykl, drzewostany=drzewostany)

    if len(heat_data) < 100:
        print(f"Uwaga: Zbyt mała liczba punktów ({len(heat_data)}) dla gatunku {gat}. Analiza może być niewiarygodna.")

    # 3. Konwersja punktów do GeoDataFrame i układu EPSG:2180
    heat_data = gpd.GeoDataFrame(
        np.array(heat_data)[:, 2], 
        geometry=gpd.points_from_xy(np.array(heat_data)[:, 1], np.array(heat_data)[:, 0]), 
        crs='EPSG:4326'
    ).to_crs(CRS_OBLICZENIOWY)

    x, y = heat_data.geometry.x, heat_data.geometry.y

    # 4. Tworzenie siatki przestrzennej
    xmin, ymin, xmax, ymax = poland.total_bounds
    x_grid = np.linspace(xmin, xmax, 500)
    y_grid = np.linspace(ymin, ymax, 500)
    X, Y = np.meshgrid(x_grid, y_grid)

    positions = np.vstack([X.ravel(), Y.ravel()])
    values = np.vstack([x, y])
    
    # 5. Obliczenie gęstości jądrowej (KDE)
    kernel = gaussian_kde(values, bw_method='scott', weights=heat_data.iloc[:, 0])
    Z = kernel(positions).reshape(X.shape)

    # 6. Przycięcie gęstości do granic Polski
    mask = shapely.contains_xy(poland_geom, X, Y)
    Z[~mask] = np.nan

    # ==============================================================================
    # --- PROGOWANIE (95% BIOMASY) ---
    # ==============================================================================
    TARGET_COVERAGE = 0.95  

    Z_valid = Z[~np.isnan(Z)]
    total_mass = np.sum(Z_valid)

    sorted_Z = np.sort(Z_valid)[::-1]
    cumsum_Z = np.cumsum(sorted_Z)

    cutoff_idx = np.searchsorted(cumsum_Z, TARGET_COVERAGE * total_mass)
    cutoff_idx = min(cutoff_idx, len(sorted_Z) - 1)
    prog_wartosc = sorted_Z[cutoff_idx]

    print(f"Gatunek: {gat} | Wyznaczony próg gęstości (95% populacji): {prog_wartosc:.2e}")

    # ==============================================================================
    # 7. WIZUALIZACJA ZASIĘGU I GENEROWANIE GEOMETRII
    # ==============================================================================
    # A) Pola gęstości KDE (bez parametrów transform)
    cf = ax.contourf(
        X, Y, Z, 
        cmap=plt.cm.cool,
        levels=[prog_wartosc, np.nanmax(Z_valid)],
        alpha=0.5
    )

    if hasattr(cf, 'get_facecolor'):
        kde_color = cf.get_facecolor()[0]
    else:
        kde_color = cf.collections[0].get_facecolor()[0]

    # B) Kontury KDE
    Z_contour = np.nan_to_num(Z, nan=0.0)
    cs = ax.contour(
        X, Y, Z_contour, 
        levels=[prog_wartosc], 
        colors=['#1b5e20'], 
        linewidths=1.5
    )

    paths = cs.get_paths() if hasattr(cs, 'get_paths') else cs.collections[0].get_paths()
    polygons = []
    for path in paths:
        for poly_pts in path.to_polygons():
            if len(poly_pts) >= 3:
                poly = Polygon(poly_pts)
                if not poly.is_valid:
                    poly = shapely.make_valid(poly)
                polygons.append(poly)

    zasieg_geom = shapely.union_all(polygons).buffer(0)

    # C) Rysowanie punktów oraz granic Polski
    heat_data.plot(ax=ax, color='red', markersize=1, alpha=0.4)
    poland.boundary.plot(ax=ax, color='black', linewidth=1)
    north_arrow(ax, 
                location="upper left", 
                rotation={"crs": poland.crs, "reference": "center"},
                shadow=False,
                scale=0.4)
    scale_bar(
    ax, 
    location="upper right", 
    style="ticks", 
    bar={"projection": poland.crs, "unit": "km", "tick_loc": "middle"},
    labels={"loc": "above", "fontsize": 8},
    units={"loc": "bar", "fontsize": 8},
    )

    # ==============================================================================
    # 8. USTAWIENIE KADRU MAPY I STYLIZACJA (CZYSTY MATPLOTLIB)
    # ==============================================================================
    MARGIN_X = 20_000
    MARGIN_Y = 20_000

    ax.set_xlim(xmin - MARGIN_X, xmax + MARGIN_X)
    ax.set_ylim(ymin - MARGIN_Y, ymax + MARGIN_Y)

    # Siatka pomocnicza i etykiety osi
    ax.grid(True, linestyle='--', alpha=0.5, color='gray')
    ax.set_title(f"Gatunek: {gat} | Cykl: {cykl}", fontsize=12)
    ax.set_xlabel("X [m] (PUWG92 / EPSG:2180)")
    ax.set_ylabel("Y [m] (PUWG92 / EPSG:2180)")

    # Wyłączenie zapisu surowych wartości numerycznych w notacji naukowej na osiach
    ax.ticklabel_format(style='plain', useOffset=False)

    cx.add_basemap(ax, crs=poland.crs, source=cx.providers.Esri.WorldGrayCanvas, alpha=1, zoom=8)
    # ==============================================================================
    # 9. TWORZENIE LEGENDRY (PROXY ARTISTS)
    # ==============================================================================
    legend_elements = [
        mpatches.Patch(
            facecolor=kde_color,
            edgecolor='#1b5e20', 
            linewidth=1.5, 
            alpha=0.6, 
            label=f'Model KDE (zasięg {int(TARGET_COVERAGE*100)}%)'
        ),
        mlines.Line2D(
            [], [], 
            color='red', 
            marker='o', 
            linestyle='None', 
            markersize=4, 
            alpha=0.6, 
            label='Powierzchnie próbne WISL'
        ),
        mlines.Line2D(
            [], [], 
            color='black', 
            linewidth=1, 
            label='Granica Polski'
        )
    ]

    # Dodanie legendy w prawym górnym rogu mapy
    ax.legend(
    handles=legend_elements, 
    loc='lower left', 
    bbox_to_anchor=(0.01, 0.03),  # (X, Y) -> Podniesienie o 8% wysokości osi w górę
    frameon=True, 
    facecolor='white', 
    framealpha=0.9, 
    fontsize=9,
    title="Legenda",
    title_fontsize=10)


    # ==============================================================================
    # 9. ZAPIS DO PLIKÓW
    # ==============================================================================
    gdf_zasieg = gpd.GeoDataFrame(
        [{
            'gatunek': gat, 
            'cykl': cykl, 
            'pokrycie': TARGET_COVERAGE,
            'prog_kde': prog_wartosc
        }],
        geometry=[zasieg_geom],
        crs=CRS_OBLICZENIOWY
    )
    
    # Eksport do EPSG:4326 (WGS84) dla portalu webowego / Folium
    gdf_zasieg_4326 = gdf_zasieg.to_crs(CRS_ZAPISU)

    if not os.path.exists("KDE_gatunki"):
        os.makedirs("KDE_gatunki")

    gdf_zasieg_4326.to_file(f"KDE_gatunki/zasieg_{gat}_cykl_{cykl}_epsg4326.geojson", driver="GeoJSON")

    fig.savefig(f"KDE_gatunki/mapa_{gat}_cykl_{cykl}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

if __name__ == "__main__":
    gatunki = ['SO','ŚW','JD','MD','DB','BK','BRZ','OL']
    cykle = [1, 2, 3, 4]
    for gat in gatunki:
        for cykl in cykle:
            plot_kde_for_species(gat=gat, cykl=cykl, drzewostany=True)