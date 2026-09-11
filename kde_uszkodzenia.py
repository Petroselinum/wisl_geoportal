import os
import matplotlib.pyplot as plt
from matplotlib import patches as mpatches
from matplotlib import lines as mlines
import numpy as np
import geopandas as gpd
import shapely
from scipy.stats import gaussian_kde
from shapely.geometry import Polygon
from heatmap_data import heatmap_uszkodzenia, heatmap_gatunki # lub funkcja do ogólnego tła
from Wisl_quert import query_drzewostany_uszk, query_all_wisl_plots # załóżmy istnienie funkcji pobierającej wszystkie punkty cyklu
from matplotlib_map_utils.core.north_arrow import north_arrow
from matplotlib_map_utils.core.scale_bar import scale_bar
import contextily as cx

# Układ obliczeniowy i wyświetlania: PUWG92 (EPSG:2180) - metryczny
CRS_OBLICZENIOWY = "EPSG:2180"
CRS_ZAPISU = "EPSG:4326"

def plot_kde_for_uszkodzenia(cykl=4, nasil_uszk_prog=6, gatunek=''):

    # 1. Inicjalizacja standardowej figury Matplotlib
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')  # Wymuszenie proporcji 1:1

    # 2. Wczytanie granic Polski i konwersja do układu metrycznego
    poland = gpd.read_file("data/poland_land.geojson").to_crs(CRS_OBLICZENIOWY)
    poland_geom = poland.geometry.union_all()

    # --- POBRANIE DANYCH TŁA (WSZYSTKIE POWIERZCHNIE WISL W CYKLU) ---
    # Zakładamy funkcję query_all_wisl_plots(cykl zwracającą współrzędne [lat, lon, ...])
    # Jeśli w bazie masz inną nazwę funkcji dla wszystkich punktów, podmień ją tutaj:
    surowe_wisl = query_all_wisl_plots(nr_cykl=cykl) 
    
    wisl = gpd.GeoDataFrame(
    geometry=gpd.points_from_xy([row.DLUGOSC for row in surowe_wisl], [row.SZEROKOSC for row in surowe_wisl]),
    crs="EPSG:4326").to_crs(CRS_OBLICZENIOWY)

    # --- POBRANIE DANYCH USZKODZEŃ ---
    dane_uszk = query_drzewostany_uszk(nr_cykl=cykl, nasil_uszk=nasil_uszk_prog)
    heat_data = heatmap_uszkodzenia(dane_uszk, gatunek=gatunek)

    if len(heat_data) < 100:
        print(f"Uwaga: Zbyt mała liczba punktów ({len(heat_data)}) dla uszkodzeń (cykl {cykl}). Analiza może być niewiarygodna.")

    # Konwersja punktów uszkodzonych do GeoDataFrame i układu EPSG:2180
    heat_data = gpd.GeoDataFrame(
        np.array(heat_data)[:, 2], 
        geometry=gpd.points_from_xy(np.array(heat_data)[:, 1], np.array(heat_data)[:, 0]), 
        crs='EPSG:4326'
    ).to_crs(CRS_OBLICZENIOWY)

    x, y = heat_data.geometry.x, heat_data.geometry.y

    # 4. Ustalenie granic kadru
    xmin, ymin, xmax, ymax = poland.total_bounds
    MARGIN_X = 20_000
    MARGIN_Y = 20_000

    ax.set_xlim(xmin - MARGIN_X, xmax + MARGIN_X)
    ax.set_ylim(ymin - MARGIN_Y, ymax + MARGIN_Y)

    # ==============================================================================
    # 5. PODKŁAD MAPOWY (CONTEXTILY)
    # ==============================================================================
    cx.add_basemap(ax, crs=poland.crs, source=cx.providers.Esri.WorldGrayCanvas, alpha=0.8)

    # ==============================================================================
    # 6. RYSOWANIE TŁA WISL (Wszystkie powierzchnie leśne w cyklu)
    # ==============================================================================
    wisl.plot(ax=ax, color='gray', markersize=1, alpha=0.25, label='_nolegend_')

    # 7. Tworzenie siatki przestrzennej i obliczenia KDE dla uszkodzeń
    x_grid = np.linspace(xmin, xmax, 500)
    y_grid = np.linspace(ymin, ymax, 500)
    X, Y = np.meshgrid(x_grid, y_grid)

    positions = np.vstack([X.ravel(), Y.ravel()])
    values = np.vstack([x, y])
    
    kernel = gaussian_kde(values, bw_method='scott', weights=heat_data.iloc[:, 0])
    Z = kernel(positions).reshape(X.shape)

    mask = shapely.contains_xy(poland_geom, X, Y)
    Z[~mask] = np.nan

    # --- PROGOWANIE (95% BIOMASY USZKODZEŃ) ---
    TARGET_COVERAGE = 0.95  
    Z_valid = Z[~np.isnan(Z)]
    total_mass = np.sum(Z_valid)

    sorted_Z = np.sort(Z_valid)[::-1]
    cumsum_Z = np.cumsum(sorted_Z)

    cutoff_idx = np.searchsorted(cumsum_Z, TARGET_COVERAGE * total_mass)
    cutoff_idx = min(cutoff_idx, len(sorted_Z) - 1)
    prog_wartosc = sorted_Z[cutoff_idx]

    # ==============================================================================
    # 8. WIZUALIZACJA ZASIĘGU I GEOMETRII USZKODZEŃ
    # ==============================================================================
    cf = ax.contourf(
        X, Y, Z, 
        cmap=plt.cm.cool,
        levels=[prog_wartosc, np.nanmax(Z_valid)],
        alpha=0.4
    )

    if hasattr(cf, 'get_facecolor'):
        kde_color = cf.get_facecolor()[0]
    else:
        kde_color = cf.collections[0].get_facecolor()[0]

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

    # Rysowanie punktów uszkodzonych na wierzchu tła WISL oraz granicy Polski
    heat_data.plot(ax=ax, color='red', markersize=2, alpha=0.6)
    poland.boundary.plot(ax=ax, color='black', linewidth=1)
    
    north_arrow(ax, location="upper left", rotation={"crs": poland.crs, "reference": "center"}, shadow=False, scale=0.4)
    scale_bar(ax, location="upper right", style="ticks", bar={"projection": poland.crs, "unit": "km", "tick_loc": "middle"}, labels={"loc": "above", "fontsize": 8}, units={"loc": "bar", "fontsize": 8})

    ax.grid(True, linestyle='--', alpha=0.3, color='gray')
    opis_gat = f" | Gatunek panujący: {gatunek}" if gatunek else " | Wszystkie gatunki"
    ax.set_title(f"Drzewostany uszkodzone (nasilenie ≥ {nasil_uszk_prog}) | Cykl: {cykl}{opis_gat}", fontsize=12)
    ax.set_xlabel("X [m] (PUWG92 / EPSG:2180)")
    ax.set_ylabel("Y [m] (PUWG92 / EPSG:2180)")
    ax.ticklabel_format(style='plain', useOffset=False)

    # ==============================================================================
    # 9. TWORZENIE LEGENDRY (Z uwzględnieniem tła WISL)
    # ==============================================================================
    legend_elements = [
        mpatches.Patch(
            facecolor=kde_color,
            edgecolor='#1b5e20', 
            linewidth=1.5, 
            alpha=0.6, 
            label=f'Koncentracja uszkodzeń ({int(TARGET_COVERAGE*100)}%)'
        ),
        mlines.Line2D(
            [], [], 
            color='red', 
            marker='o', 
            linestyle='None', 
            markersize=4, 
            alpha=0.8, 
            label='Uszkodzone pow. WISL'
        ),
        mlines.Line2D(
            [], [], 
            color='gray', 
            marker='o', 
            linestyle='None', 
            markersize=3, 
            alpha=0.5, 
            label='Wszystkie pow. WISL (tło)'
        ),
        mlines.Line2D(
            [], [], 
            color='black', 
            linewidth=1, 
            label='Granica Polski'
        )
    ]

    ax.legend(
        handles=legend_elements, 
        loc='lower left', 
        bbox_to_anchor=(0.01, 0.03), 
        frameon=True, 
        facecolor='white', 
        framealpha=0.9, 
        fontsize=9,
        title="Legenda",
        title_fontsize=10
    )

    # ==============================================================================
    # 10. ZAPIS DO PLIKÓW
    # ==============================================================================
    gdf_zasieg = gpd.GeoDataFrame(
        [{
            'typ': 'uszkodzenia',
            'nasil_uszk_prog': nasil_uszk_prog,
            'gatunek_pan': gatunek or 'wszystkie',
            'cykl': cykl, 
            'pokrycie': TARGET_COVERAGE,
            'prog_kde': prog_wartosc
        }],
        geometry=[zasieg_geom],
        crs=CRS_OBLICZENIOWY
    )
    
    gdf_zasieg_4326 = gdf_zasieg.to_crs(CRS_ZAPISU)

    if not os.path.exists("KDE_uszkodzenia"):
        os.makedirs("KDE_uszkodzenia")

    sufiks = f"_{gatunek.strip().lower().replace(' ', '_')}" if gatunek else ""
    gdf_zasieg_4326.to_file(f"KDE_uszkodzenia/zasieg_uszkodzenia{sufiks}_cykl_{cykl}_epsg4326.geojson", driver="GeoJSON")
    fig.savefig(f"KDE_uszkodzenia/mapa_uszkodzenia{sufiks}_cykl_{cykl}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

if __name__ == "__main__":
    cykle = [1, 2, 3, 4]
    for cykl in cykle:
        plot_kde_for_uszkodzenia(cykl=cykl, nasil_uszk_prog=6)
