import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
import cartopy.crs as ccrs
from scipy.stats import gaussian_kde
from heatmap_data import heatmap_gatunki
from Wisl_quert import query_udzial_gat
from shapely.geometry import Polygon
import os

def plot_kde_for_species(gat, cykl=4, drzewostany=True):

    # 1. Inicjalizacja figury i podkładu mapy w EPSG:3857
    fig = plt.figure(figsize=(10, 10))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.epsg(3857))

    # 2. Wczytanie granic Polski i konwersja do EPSG:3857 (metry)
    poland = gpd.read_file("data/poland_land.geojson").to_crs(epsg=3857)
    poland_geom = poland.geometry.union_all()

    udzal_gat = query_udzial_gat(gat, cykl)
    heat_data = heatmap_gatunki(udzal_gat, cykl=cykl, drzewostany=drzewostany)

    if len(heat_data) < 100:
        print(f"Uwaga: Zbyt mała liczba punktów ({len(heat_data)}) dla gatunku {gat}. Analiza może być niewiarygodna.")

    # 3. Konwersja punktów do GeoDataFrame i układu EPSG:3857
    heat_data = gpd.GeoDataFrame(
        np.array(heat_data)[:, 2], 
        geometry=gpd.points_from_xy(np.array(heat_data)[:, 1], np.array(heat_data)[:, 0]), 
        crs='EPSG:4326'
    ).to_crs(epsg=3857)

    x, y = heat_data.geometry.x, heat_data.geometry.y

    # 4. Tworzenie siatki przestrzennej w granicach Polski
    xmin, ymin, xmax, ymax = poland.total_bounds
    X, Y = np.mgrid[xmin:xmax:500j, ymin:ymax:500j]
    positions = np.vstack([X.ravel(), Y.ravel()])
    values = np.vstack([x, y])

    # 5. Obliczenie gęstości jądrowej (KDE) z wagami udziału gatunku
    kernel = gaussian_kde(values, bw_method='scott', weights=heat_data.iloc[:, 0])
    Z = np.reshape(kernel(positions).T, X.shape)

    # 6. Przycięcie gęstości do granic Polski
    mask = shapely.contains_xy(poland_geom, X, Y)
    Z[~mask] = np.nan

    # ==============================================================================
    # --- METODA 1: WYZNACZENIE PROGU NA PODSTAWIE SKUMULOWANEJ BIOMASY (95%) ---
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
    ax.contourf(
        X, Y, Z, 
        cmap=plt.cm.cool,
        levels=[prog_wartosc, np.nanmax(Z_valid)],
        transform=ccrs.epsg(3857),
        alpha=0.5
    )

    # Wypełnienie NaN zerami wyłącznie dla funkcji contour, aby uniknąć przerw na krawędziach
    Z_contour = np.nan_to_num(Z, nan=0.0)

    cs = ax.contour(
        X, Y, Z_contour, 
        levels=[prog_wartosc], 
        colors=['#1b5e20'], 
        linewidths=1.5, 
        transform=ccrs.epsg(3857)
    )

    paths = cs.get_paths() if hasattr(cs, 'get_paths') else cs.collections[0].get_paths()

    polygons = []
    for path in paths:
        # Użycie to_polygons() wymusza poprawne podziały na pod-ścieżki (ignoruje błędne łączenia)
        for poly_pts in path.to_polygons():
            if len(poly_pts) >= 3:
                poly = Polygon(poly_pts)
                if not poly.is_valid:
                    poly = shapely.make_valid(poly)
                polygons.append(poly)

    # Połączenie wszystkich wysepek
    zasieg_geom = shapely.union_all(polygons)

    # Dodatkowe czyszczenie morfologiczne naprawiające mikroskopijne błędy na stykach
    zasieg_geom = zasieg_geom.buffer(0)

    # 8. Utworzenie nowej warstwy GeoDataFrame z atrybutami
    gdf_zasieg = gpd.GeoDataFrame(
        [{
            'gatunek': gat, 
            'cykl': cykl, 
            'pokrycie': TARGET_COVERAGE,
            'prog_kde': prog_wartosc
        }],
        geometry=[zasieg_geom],
        crs='EPSG:3857'  
    )

    # 9. ZAPIS DO PLIKÓW
    if not os.path.exists("KDE_wyniki"):
        os.makedirs("KDE_wyniki")

    gdf_zasieg.to_file(f"KDE_wyniki/zasieg_{gat}_cykl_{cykl}_epsg3857.geojson", driver="GeoJSON")

    # Siatka geograficzna z etykietami
    gl = ax.gridlines(draw_labels=True, dms=True, linewidth=0.5, color='black', alpha=0.6, linestyle='--')
    gl.top_labels = True
    gl.right_labels = False

    heat_data.plot(ax=ax, color='red', markersize=1, alpha=0.4)
    poland.exterior.plot(ax=ax, color='black', linewidth=1)

if __name__ == "__main__":
    gatunki = ['SO','ŚW','JD','MD','DB','BK','GB','BRZ','OL','JS','LP','JW']
    cykle = [1, 2, 3, 4]
    for gat in gatunki:
        for cykl in cykle:
            plot_kde_for_species(gat=gat, cykl=cykl, drzewostany=True)
