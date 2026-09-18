import os
import subprocess
import matplotlib.pyplot as plt
from matplotlib import patches as mpatches
from matplotlib import lines as mlines
import pandas as pd
import geopandas as gpd
import contextily as cx

from Wisl_quert import query_drzewostany_uszk
from matplotlib_map_utils.core.north_arrow import north_arrow
from matplotlib_map_utils.core.scale_bar import scale_bar

# ==============================================================================
# ŚCIEŻKA DO Rscript W ŚRODOWISKU CONDA
# ==============================================================================
RSCRIPT_PATH = "/home/piotr/miniconda3/envs/jupyter_env/bin/Rscript" 

CRS_OBLICZENIOWY = "EPSG:2180"

# Ten sam globalny próg wiarygodności modelu co w kde_uszkodzenia.py /
# kde_martwe_drewno.py / kde_gat.py - poniżej tej liczby traktów mapa w
# ogóle nie jest generowana.
MIN_TRAKTOW_WIARYGODNY = 100

def uszkodzenia(rok_start: int, rok_end: int, prog_nasil_uszk: int = None, gatunek: str = None):
    okres = f"{rok_start}-{rok_end}"
    res = query_drzewostany_uszk(rok_start=rok_start, rok_end=rok_end)
    if not res:
        print(f"Brak danych z bazy dla lat {okres}.")
        return

    df = pd.DataFrame(res, columns=['NR_PUNKTU', 'NR_PODPOW', 'GAT_PAN_PR', 'WSP_Z', 'NASIL_USZK', 'PRZYCZ_USZK'])
    df['NR_TRAKTU'] = df['NR_PUNKTU'].str[:-1]

    trakty = gpd.read_file('data/trakty_wsp.geojson')

    if gatunek is not None:
        df = df[df['GAT_PAN_PR'] == gatunek].copy()

    if df.empty:
        print(f"Brak danych po odfiltrowaniu dla gatunku w latach {okres}.")
        return

    tlo = df.groupby('NR_TRAKTU').agg({'WSP_Z': 'sum'}).reset_index()

    if prog_nasil_uszk is not None:
        df_uszk_filtr = df[df['NASIL_USZK'] > prog_nasil_uszk].copy()
    else:
        df_uszk_filtr = df[df['NASIL_USZK'] > 0].copy()

    # ZAŁOŻENIE DO ZWERYFIKOWANIA (ta sama waga co w kde_uszkodzenia.py):
    # traktujemy NASIL_USZK jako wielkość liniową - jeśli to kod klasy
    # porządkowej, a nie ilorazowej, mnożenie przez WSP_Z wymaga rewizji.
    df_uszk_filtr['iloczyn_nasilenia'] = df_uszk_filtr['WSP_Z'] * df_uszk_filtr['NASIL_USZK']
    df_uszk_trakty = df_uszk_filtr.groupby('NR_TRAKTU').agg(waga_uszk=('iloczyn_nasilenia', 'sum')).reset_index()

    trakty['nr_traktu'] = trakty['nr_punktu'].astype(int).astype(str).str[:-1]
    trakty_geom = trakty[['nr_traktu', 'geometry']].copy()

    tlo['NR_TRAKTU'] = tlo['NR_TRAKTU'].astype(int).astype(str)
    df_uszk_trakty['NR_TRAKTU'] = df_uszk_trakty['NR_TRAKTU'].astype(int).astype(str)

    df_model = pd.merge(tlo, df_uszk_trakty, on='NR_TRAKTU', how='left')
    df_model['waga_uszk'] = df_model['waga_uszk'].fillna(0.0)
    df_model = df_model.rename(columns={'WSP_Z': 'waga_tlo'})

    gdf_model = trakty_geom.merge(df_model, left_on='nr_traktu', right_on='NR_TRAKTU', how='inner')
    gdf_model = gpd.GeoDataFrame(gdf_model, geometry='geometry', crs=trakty.crs).to_crs(CRS_OBLICZENIOWY)
    gdf_model = gdf_model[gdf_model.geometry.notnull() & (gdf_model['waga_tlo'] > 0)].copy()

    if len(gdf_model) < 5:
        print(f"Zbyt mało danych dla lat {okres}.")
        return

    if len(gdf_model) < MIN_TRAKTOW_WIARYGODNY:
        print(
            f"Pominięto mapę: tylko {len(gdf_model)} traktów (wymagane min. "
            f"{MIN_TRAKTOW_WIARYGODNY}, lata {okres})."
        )
        return

    # ==============================================================================
    # 1. PRZYGOTOWANIE DANYCH WEJŚCIOWYCH DLA R
    # ==============================================================================
    os.makedirs("KDE_temp", exist_ok=True)
    os.makedirs("KDE_uszkodzenia_ryzyko", exist_ok=True)

    poland = gpd.read_file("data/poland_land.geojson").to_crs(CRS_OBLICZENIOWY)
    poland.to_file("KDE_temp/poland_bounds.geojson", driver="GeoJSON")

    df_tlo_pts = pd.DataFrame({
        'x': gdf_model.geometry.x,
        'y': gdf_model.geometry.y,
        'waga': gdf_model['waga_tlo']
    })
    df_tlo_pts.to_csv("KDE_temp/tlo_points.csv", index=False)

    gdf_uszk = gdf_model[gdf_model['waga_uszk'] > 0]
    df_uszk_pts = pd.DataFrame({
        'x': gdf_uszk.geometry.x,
        'y': gdf_uszk.geometry.y,
        'waga': gdf_uszk['waga_uszk']
    })
    df_uszk_pts.to_csv("KDE_temp/uszk_points.csv", index=False)

    sufix_gat = f"_{gatunek}" if gatunek else ""
    sufix_nasil = f"_nasil{prog_nasil_uszk}" if prog_nasil_uszk is not None else ""
    file_prefix = f"ryzyko_{okres}{sufix_gat}{sufix_nasil}"

    # ==============================================================================
    # 2. WYWOŁANIE SKRYPTU R
    # ==============================================================================
    print(f"Obliczanie istotności statystycznej w R (sparr) dla lat {okres}...")
    try:
        subprocess.run(
            [RSCRIPT_PATH, "policz_ryzyko.R", file_prefix],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"Błąd podczas wykonywania Rscript:\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}")
        return

    # ==============================================================================
    # 3. ODCZYT WYNIKÓW I REDEFINICJA CRS
    # ==============================================================================
    geojson_path = f"KDE_uszkodzenia_ryzyko/istotne_{file_prefix}.geojson"

    if os.path.exists(geojson_path):
        gdf_istotne = gpd.read_file(geojson_path)
        # R zwraca surowe metry, przypisujemy właściwy CRS siłą
        if not gdf_istotne.empty:
            gdf_istotne = gdf_istotne.set_crs(CRS_OBLICZENIOWY, allow_override=True)
            gdf_istotne.to_file(geojson_path, driver="GeoJSON")  # zapisz poprawiony CRS z powrotem na dysk
    else:
        gdf_istotne = gpd.GeoDataFrame(geometry=[], crs=CRS_OBLICZENIOWY)

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')

    if not gdf_istotne.empty:
        gdf_istotne.plot(
            ax=ax,
            facecolor='#ff7f00',
            edgecolor='#8b0000',
            linewidth=1.5,
            alpha=0.6
        )

    gdf_model.plot(ax=ax, color='gray', markersize=3, alpha=0.3)
    gdf_uszk.plot(ax=ax, color='red', markersize=8, alpha=0.7)
    poland.boundary.plot(ax=ax, color='black', linewidth=1)

    try:
        north_arrow(ax, location="upper left", rotation={"crs": poland.crs, "reference": "center"}, shadow=False, scale=0.4)
        scale_bar(ax, location="upper right", style="ticks", bar={"projection": poland.crs, "unit": "km"}, units={"loc": "bar"})
    except NameError:
        pass

    xmin, ymin, xmax, ymax = poland.total_bounds
    MARGIN = 20_000
    ax.set_xlim(xmin - MARGIN, xmax + MARGIN)
    ax.set_ylim(ymin - MARGIN, ymax + MARGIN)
    ax.grid(True, linestyle='--', alpha=0.5, color='gray')

    tytul_gatunek = f" | Gatunek: {gatunek}" if gatunek else ""
    nasil_opis = prog_nasil_uszk if prog_nasil_uszk is not None else 0
    ax.set_title(f"Istotne ryzyko uszkodzeń p < 0.05 (Lata: {okres}, próg > {nasil_opis}){tytul_gatunek}", fontsize=11)
    # Wynik eksploracyjny: p<0.05 liczone niezależnie w każdym pikselu siatki,
    # bez korekty na wielokrotne testowanie (patrz policz_ryzyko.R) - to
    # akceptowane w literaturze ograniczenie metody tolerance contours
    # (Kelsall & Diggle), ale trzeba je widzieć razem z wynikiem, nie tylko
    # w logu konsoli.
    ax.text(
        0.01, 0.99,
        "Wynik eksploracyjny - bez korekty na wielokrotne testowanie",
        transform=ax.transAxes, fontsize=7, color="#555555",
        va="top", ha="left",
    )
    ax.set_xlabel("X [m] (EPSG:2180)")
    ax.set_ylabel("Y [m] (EPSG:2180)")
    ax.ticklabel_format(style='plain', useOffset=False)

    try:
        cx.add_basemap(ax, crs=poland.crs, source=cx.providers.Esri.WorldGrayCanvas, alpha=1, zoom=8)
    except Exception:
        pass

    legend_elements = [
        mpatches.Patch(facecolor='#ff7f00', edgecolor='#8b0000', linewidth=1.5, alpha=0.6, label='Istotne ryzyko (p < 0.05)'),
        mlines.Line2D([], [], color='red', marker='o', linestyle='None', markersize=6, alpha=0.7, label='Trakt uszkodzony'),
        mlines.Line2D([], [], color='gray', marker='o', linestyle='None', markersize=4, alpha=0.4, label='Trakt badany (tło)'),
        mlines.Line2D([], [], color='black', linewidth=1, label='Granica Polski'),
    ]
    ax.legend(handles=legend_elements, loc='lower left', bbox_to_anchor=(0.01, 0.03), frameon=True, facecolor='white')

    fig.savefig(f"KDE_uszkodzenia_ryzyko/{file_prefix}_sparr.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Zakończono pomyślnie. Wyniki z testem sparr zapisano dla lat {okres}.")

if __name__ == "__main__":
    from Wisl_quert import CYKLE_LATA
    for rok_start, rok_end in CYKLE_LATA.values():
        uszkodzenia(rok_start=rok_start, rok_end=rok_end, prog_nasil_uszk=3, gatunek='ŚW')