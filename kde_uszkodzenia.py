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
from kde_common import wymus_wspolne_pasmo
import contextily as cx

# Układ obliczeniowy i wyświetlania: PUWG92 (EPSG:2180) - metryczny
CRS_OBLICZENIOWY = "EPSG:2180"
CRS_ZAPISU = "EPSG:4326"

# ==============================================================================
# CO LICZY TEN SKRYPT
# ==============================================================================
# Lokalne, wygładzone przestrzennie ŚREDNIE NASILENIE USZKODZEŃ drzewostanów
# [%] - estymator Nadaraya-Watson (iloraz dwóch KDE o wspólnym paśmie), ten
# sam co w kde_martwe_drewno.py:
#   f = KDE ważone WSP_Z * NASIL_USZK * 10 (tylko NASIL_USZK > prog)
#   g = KDE ważone WSP_Z wszystkich zbadanych drzewostanów
#   wynik = f/g * sum(waga_f)/sum(waga_g)
# NASIL_USZK to skala ciągła (3 = 30%, 5 = 50%); poniżej 30% drzewostan uznaje
# się za nieuszkodzony, stąd w bazie nie ma wartości 1-2. Drzewostany poniżej
# progu wchodzą do średniej jako 0% - to ŚREDNIA po całej powierzchni lasu,
# nie średnia tylko wśród uszkodzonych.
#
# Wcześniejsza wersja zaznaczała 95. percentyl ilorazu f/g. Percentyl to
# wielkość WZGLĘDNA: mapa zawsze pokazywała 5% siatki, niezależnie od tego, czy
# uszkodzeń było dużo, czy mało - a średnia krajowa zmienia się między okresami
# prawie trzykrotnie (2005-2009: 3,8%, 2015-2019: 10,4%, 2020-2025: 5,7%).
# Stałe progi w % (PROGI_NASILENIA_PROC) czynią mapy porównywalnymi między
# okresami - ten sam problem i to samo rozwiązanie co w kde_gat.py.
#
# Usunięto też epsilon 1e-12 z mianownika: gęstości KDE w metrach są rzędu
# 1e-12 (max tła 4,8e-12), więc "zabezpieczenie" było tego samego rzędu co
# dane i zaniżało iloraz średnio o 27%, lokalnie o 57% - najsilniej tam, gdzie
# tło jest słabe, czyli zmieniało kształt obszaru. Dzielenie przez zero i tak
# wyklucza maska niskiego tła (PROG_MIN_TLA).

PROG_MIN_TLA = 0.01           # poniżej tego ułamka maksimum gęstości tła nie ufamy ilorazowi (brzegi)
MIN_TRAKTOW_WIARYGODNY = 100  # globalny próg wiarygodności modelu (ten sam co w pozostałych skryptach KDE)

PROGI_NASILENIA_PROC = [5, 10, 15, 20]

# Kolor przypisany NA STAŁE do wartości progu - pasmo ma ten sam odcień
# niezależnie od okresu i od tego, ile progów akurat się rysuje.
KOLORY_PROGOW_PROC = {
    5: plt.cm.YlOrRd(0.30),
    10: plt.cm.YlOrRd(0.50),
    15: plt.cm.YlOrRd(0.70),
    20: plt.cm.YlOrRd(0.92),
}


def uszkodzenia(rok_start: int, rok_end: int, prog_nasil_uszk: int = None, gatunek: str = None,
                progi: list[float] = PROGI_NASILENIA_PROC):
    okres = f"{rok_start}-{rok_end}"
    res = query_drzewostany_uszk(rok_start=rok_start, rok_end=rok_end)
    if not res:
        print(f"Brak danych z bazy dla lat {okres}.")
        return

    df = pd.DataFrame(res, columns=['NR_PUNKTU', 'NR_PODPOW', 'GAT_PAN_PR', 'WSP_Z', 'NASIL_USZK', 'PRZYCZ_USZK'])
    df['NR_TRAKTU'] = df['NR_PUNKTU'].str[:-1]

    trakty = gpd.read_file('data/trakty_wsp.geojson')

    if gatunek is not None:
        # Podgatunki (DB.S, DB.B, ...) jak gatunek bazowy - to samo dopasowanie
        # co Wisl_quert._dopasowanie_gatunku.
        maska = (df['GAT_PAN_PR'] == gatunek) | df['GAT_PAN_PR'].fillna('').str.startswith(gatunek + '.')
        df = df[maska].copy()

    if df.empty:
        print(f"Brak danych po odfiltrowaniu dla gatunku w latach {okres}.")
        return

    tlo = df.groupby('NR_TRAKTU').agg({'WSP_Z': 'sum'}).reset_index()

    prog = prog_nasil_uszk if prog_nasil_uszk is not None else 0
    df_uszk_filtr = df[df['NASIL_USZK'] > prog].copy()

    # NASIL_USZK * 10 = nasilenie w %, ważone reprezentowaną powierzchnią.
    df_uszk_filtr['iloczyn_nasilenia'] = df_uszk_filtr['WSP_Z'] * df_uszk_filtr['NASIL_USZK'] * 10

    df_uszk_trakty = df_uszk_filtr.groupby('NR_TRAKTU').agg(
        waga_uszk=('iloczyn_nasilenia', 'sum')
    ).reset_index()

    trakty['nr_traktu'] = trakty['nr_punktu'].astype(int).astype(str).str[:-1]
    trakty_geom = trakty[['nr_traktu', 'geometry']].copy()

    tlo['NR_TRAKTU'] = tlo['NR_TRAKTU'].astype(int).astype(str)
    df_uszk_trakty['NR_TRAKTU'] = df_uszk_trakty['NR_TRAKTU'].astype(int).astype(str)

    # ==============================================================================
    # GEOMETRIA TRAKTÓW
    # ==============================================================================
    # LEFT JOIN od tła: trakty bez uszkodzeń zostają z wagą 0 i poprawnie
    # obniżają lokalną średnią przez swój wkład w mianowniku.
    df_model = pd.merge(tlo, df_uszk_trakty, on='NR_TRAKTU', how='left')
    df_model['waga_uszk'] = df_model['waga_uszk'].fillna(0.0)
    df_model = df_model.rename(columns={'WSP_Z': 'waga_tlo'})

    gdf_model = trakty_geom.merge(df_model, left_on='nr_traktu', right_on='NR_TRAKTU', how='inner')
    gdf_model = gpd.GeoDataFrame(gdf_model, geometry='geometry', crs=trakty.crs).to_crs(CRS_OBLICZENIOWY)
    gdf_model = gdf_model[gdf_model.geometry.notnull() & (gdf_model['waga_tlo'] > 0)].copy()

    if len(gdf_model) < 5:
        print(f"Zbyt mało danych przestrzennych do wyznaczenia KDE (lata {okres}, znaleziono: {len(gdf_model)}).")
        return

    if len(gdf_model) < MIN_TRAKTOW_WIARYGODNY:
        print(
            f"Pominięto mapę: tylko {len(gdf_model)} traktów (wymagane min. "
            f"{MIN_TRAKTOW_WIARYGODNY}, lata {okres})."
        )
        return

    mask_uszk = gdf_model['waga_uszk'] > 0
    if mask_uszk.sum() < 3:
        print(f"Za mało traktów z uszkodzeniami do wyznaczenia KDE (lata {okres}: {int(mask_uszk.sum())}).")
        return

    coords = np.vstack([gdf_model.geometry.x, gdf_model.geometry.y])
    waga_tlo = gdf_model['waga_tlo'].to_numpy()
    waga_f = gdf_model['waga_uszk'].to_numpy()

    # ==============================================================================
    # SIATKA ORAZ GRANICE POLSKI
    # ==============================================================================
    poland = gpd.read_file("data/poland_land.geojson").to_crs(CRS_OBLICZENIOWY)
    poland_geom = poland.geometry.union_all()

    xmin, ymin, xmax, ymax = poland.total_bounds
    x_grid = np.linspace(xmin, xmax, 500)
    y_grid = np.linspace(ymin, ymax, 500)
    X, Y = np.meshgrid(x_grid, y_grid)
    positions = np.vstack([X.ravel(), Y.ravel()])

    # ==============================================================================
    # KDE (WSPÓLNE PASMO) + KOREKTA SKALI NORMALIZACJI WAG
    # ==============================================================================
    kernel_tlo = gaussian_kde(coords, weights=waga_tlo, bw_method='scott')
    # Te same współrzędne co tło (trakty bez uszkodzeń z wagą 0 nic nie
    # wnoszą do licznika) i wymuszone TO SAMO fizyczne pasmo - patrz
    # kde_common.wymus_wspolne_pasmo.
    kernel_f = gaussian_kde(coords, weights=waga_f)
    wymus_wspolne_pasmo(kernel_f, kernel_tlo)

    # scipy normalizuje f i g NIEZALEŻNIE do całki=1 - bez tej korekty iloraz
    # byłby przeskalowany przypadkowym współczynnikiem, a nie średnim
    # nasileniem w %. Jednocześnie to jest średnia krajowa ważona powierzchnią.
    wspolczynnik_korekty_skali = waga_f.sum() / waga_tlo.sum()

    f_est = kernel_f(positions).reshape(X.shape)
    g_est = kernel_tlo(positions).reshape(X.shape)

    mask_polska = shapely.contains_xy(poland_geom, X, Y)
    f_est[~mask_polska] = np.nan
    g_est[~mask_polska] = np.nan

    max_tla = np.nanmax(g_est)
    mask_niskie_tlo = g_est < (PROG_MIN_TLA * max_tla)

    with np.errstate(divide='ignore', invalid='ignore'):
        nasilenie = (f_est / g_est) * wspolczynnik_korekty_skali

    nasilenie[mask_niskie_tlo] = np.nan
    wartosci_valid = nasilenie[~np.isnan(nasilenie)]

    if wartosci_valid.size == 0:
        print(f"Brak poprawnych wartości nasilenia dla lat {okres}.")
        return

    max_nasilenia = float(np.nanmax(wartosci_valid))

    # Progi rosnąco, ograniczone do faktycznie osiągniętych w tym okresie.
    progi_nasilenia = sorted(p for p in set(progi) if p < max_nasilenia)

    if not progi_nasilenia:
        print(
            f"Lata {okres}: nasilenie nie przekracza żadnego z progów {sorted(set(progi))} % "
            f"(max={max_nasilenia:.1f}%) - pomijam mapę."
        )
        return

    print(
        f"Uszkodzenia | Lata: {okres} | n_traktow={len(gdf_model)} "
        f"(z uszkodzeniami: {int(mask_uszk.sum())}) | "
        f"srednia krajowa={wspolczynnik_korekty_skali:.2f}% | max lokalny={max_nasilenia:.1f}%"
    )

    # ==============================================================================
    # WIZUALIZACJA I EKSTRAKCJA GEOMETRII
    # ==============================================================================
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')

    kolory_pasm = [KOLORY_PROGOW_PROC[p] for p in progi_nasilenia]

    ax.contourf(
        X, Y, nasilenie,
        levels=progi_nasilenia + [max_nasilenia],
        colors=kolory_pasm,
        alpha=0.7,
    )

    nasilenie_contour = np.nan_to_num(nasilenie, nan=0.0)
    cs = ax.contour(
        X, Y, nasilenie_contour,
        levels=progi_nasilenia,
        colors=['#8b0000'],
        linewidths=1.2,
    )

    # Wielokąty KUMULATYWNE (zagnieżdżone): obszar progu 10% leży w całości
    # wewnątrz obszaru progu 5% - jak w kde_gat.py / kde_martwe_drewno.py.
    zasiegi_geom = []
    for segs in cs.allsegs:
        polygons = []
        for seg in segs:
            if len(seg) >= 3:
                poly = Polygon(seg)
                if not poly.is_valid:
                    poly = shapely.make_valid(poly)
                polygons.append(poly)
        zasiegi_geom.append(shapely.union_all(polygons).buffer(0) if polygons else Polygon())

    gdf_model.plot(ax=ax, color='gray', markersize=3, alpha=0.3)
    gdf_model[mask_uszk].plot(ax=ax, color='red', markersize=6, alpha=0.5)
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
    zakresy_opis = ', '.join(
        (f'{p:.0f}–{progi_nasilenia[i + 1]:.0f}' if i + 1 < len(progi_nasilenia) else f'>{p:.0f}')
        for i, p in enumerate(progi_nasilenia)
    )
    ax.set_title(
        f"Średnie nasilenie uszkodzeń drzewostanów — zakresy {zakresy_opis}% "
        f"(Lata: {okres}, uszk. > {prog * 10}%){tytul_gatunek}",
        fontsize=11,
    )
    ax.set_xlabel("X [m] (EPSG:2180)")
    ax.set_ylabel("Y [m] (EPSG:2180)")
    ax.ticklabel_format(style='plain', useOffset=False)

    try:
        cx.add_basemap(ax, crs=poland.crs, source=cx.providers.Esri.WorldGrayCanvas, alpha=1, zoom=8)
    except Exception:
        pass

    # Etykiety legendy opisują PRZEDZIAŁY - contourf koloruje rozłączne pasma.
    legend_elements = [
        mpatches.Patch(
            facecolor=kolory_pasm[i], edgecolor='#8b0000', linewidth=1.2, alpha=0.7,
            label=(f'{progi_nasilenia[i]:.0f}–{progi_nasilenia[i + 1]:.0f}%'
                   if i + 1 < len(progi_nasilenia) else f'> {progi_nasilenia[i]:.0f}%'),
        )
        for i in range(len(progi_nasilenia) - 1, -1, -1)
    ] + [
        mlines.Line2D([], [], color='red', marker='o', linestyle='None', markersize=6, alpha=0.5, label='Trakt uszkodzony'),
        mlines.Line2D([], [], color='gray', marker='o', linestyle='None', markersize=4, alpha=0.4, label='Trakt badany (tło)'),
        mlines.Line2D([], [], color='black', linewidth=1, label='Granica Polski'),
    ]
    ax.legend(
        handles=legend_elements, loc='center left', bbox_to_anchor=(1.01, 0.5),
        frameon=True, facecolor='white', fontsize=9, title="Legenda", title_fontsize=10,
    )

    # ==============================================================================
    # ZAPIS WYNIKÓW
    # ==============================================================================
    if not os.path.exists("KDE_uszkodzenia"):
        os.makedirs("KDE_uszkodzenia")

    gdf_zasieg = gpd.GeoDataFrame(
        [
            {
                'rok_start': rok_start,
                'rok_end': rok_end,
                'gatunek': gatunek if gatunek else 'Wszystkie',
                'prog_nasilenia': prog,
                'prog_sredniego_nasilenia_proc': p,
                'zakres': f'nasilenie >= {p:.0f}%',
                'srednia_krajowa_proc': float(wspolczynnik_korekty_skali),
                'max_nasilenia_proc': max_nasilenia,
                'liczba_traktow': len(gdf_model),
                'geometry': geom,
            }
            for p, geom in zip(progi_nasilenia, zasiegi_geom)
        ],
        geometry='geometry',
        crs=CRS_OBLICZENIOWY,
    )

    sufix_gat = f"_{gatunek}" if gatunek else ""
    sufix_nasil = f"_nasil{prog_nasil_uszk}" if prog_nasil_uszk is not None else ""
    file_prefix = f"nasilenie_{okres}{sufix_gat}{sufix_nasil}"

    gdf_zasieg.to_crs(CRS_ZAPISU).to_file(
        f"KDE_uszkodzenia/{file_prefix}.geojson", driver="GeoJSON"
    )
    fig.savefig(f"KDE_uszkodzenia/{file_prefix}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Zakończono pomyślnie. Zapisano wyniki dla lat {okres}.")


if __name__ == "__main__":
    from Wisl_quert import CYKLE_LATA
    for rok_start, rok_end in CYKLE_LATA:
        uszkodzenia(rok_start=rok_start, rok_end=rok_end, prog_nasil_uszk=3, gatunek=None)
