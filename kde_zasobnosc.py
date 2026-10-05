import os
import matplotlib.pyplot as plt
from matplotlib import patches as mpatches
from matplotlib import lines as mlines
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from scipy.stats import gaussian_kde
from Wisl_quert import query_zasobnosc, query_zasobnosc_gat
from matplotlib_map_utils.core.north_arrow import north_arrow
from matplotlib_map_utils.core.scale_bar import scale_bar
from kde_common import (
    wymus_wspolne_pasmo,
    kontur_na_zasieg,
    etykietuj_kontury,
)
import contextily as cx

# Układ obliczeniowy i wyświetlania: PUWG92 (EPSG:2180) - metryczny
CRS_OBLICZENIOWY = "EPSG:2180"
CRS_ZAPISU = "EPSG:4326"

# ==============================================================================
# CO LICZY TEN SKRYPT
# ==============================================================================
# Lokalną, wygładzoną przestrzennie ŚREDNIĄ ZASOBNOŚĆ drzewostanów [m3/ha] -
# miąższość drzew ŻYWYCH na hektar. Ten sam estymator Nadaraya-Watson (iloraz
# dwóch KDE o wspólnym paśmie) co w kde_martwe_drewno.py i kde_gat.py:
#   f = KDE ważone ZASOBNOSC * SUMA_WSP_Z (łączna miąższość traktu)
#   g = KDE ważone SUMA_WSP_Z (reprezentowana powierzchnia traktu)
#   wynik = f/g * sum(waga_f)/sum(waga_g)   -> średnia w m3/ha
#
# RÓŻNICA WOBEC MARTWEGO DREWNA: ZASOBNOSC jest już gotową gęstością (m3/ha
# podpowierzchni), a nie surową objętością z koła próbnego - nie ma tu więc
# przelicznika na hektar. Agregacja do traktu (średnia ważona WSP_Z) dzieje
# się po stronie SQL, w Wisl_quert.query_zasobnosc.
#
# ==============================================================================
# DLACZEGO NIE PRZYCINAMY WARTOŚCI SKRAJNYCH
# ==============================================================================
# W bazie ZASOBNOSC sięga 9413 m3/ha, co jest fizycznie niemożliwe. Sprawdzone:
# takie wartości występują WYŁĄCZNIE na podpowierzchniach o maleńkim WSP_Z
# (0,0075-0,0225) - kilka drzew na skrawku powierzchni przeliczone na pełny
# hektar. Ponieważ wchodzą do średniej z wagą równą właśnie WSP_Z, same się
# tłumią: trakty o średniej > 800 m3/ha to łącznie 0,3% całej wagi. Przycinanie
# (jak MAX_ZADRZEW w Wisl_quert) byłoby tu więc zbędne - w przeciwieństwie do
# ZADRZEW, który jest wielkością bezwymiarową i nie miał takiego naturalnego
# tłumika.
#
# ==============================================================================
# WALIDACJA WZGLĘDEM DANYCH BULiGL
# ==============================================================================
# Średnia krajowa z tego potoku wobec zasobności raportowanej przez BULiGL
# (data.py, średnia po RDLP):
#   2005-2009: 262,4 vs 263,2 | 2010-2014: 279,5 vs 276,5
#   2015-2019: 291,7 vs 291,1 | 2020-2025: 302,2 vs 292,9
# Rozjazd w ostatnim okresie wynika głównie z 848 podpowierzchni cyklu 4 bez
# opisu taksacyjnego (patrz query_zasobnosc) - są pomijane jako brak danych,
# co lekko zawyża średnią. Potraktowanie ich jako zera dałoby 295,7 m3/ha,
# ale byłoby nieprawdą, bo te podpowierzchnie mają zmierzone drzewa.
#
# ==============================================================================
# ZASOBNOŚĆ POJEDYNCZEGO GATUNKU (parametr gatunek)
# ==============================================================================
# Ten sam estymator, ale SR_ZASOBNOSC pochodzi z Wisl_quert.query_zasobnosc_gat:
# suma miąższości drzew gatunku (OBL_DRZEWA_OD_7.MIAZSZOSC) przeliczona przez
# WSP_Z i powierzchnię koła pomiarowego. Wynik to m3/ha GATUNKU na hektar
# WSZYSTKICH drzewostanów (nie tylko tych, w których gatunek występuje) -
# podpowierzchnie bez gatunku wchodzą jako 0, więc zasobności wszystkich
# gatunków sumują się do zasobności ogółem. Średnie krajowe (2005-2009 ->
# 2020-2025): SO 151,6 -> 169,1 | DB 19,1 -> 25,5 | BK 17,7 -> 21,8 |
# JD 9,1 -> 14,3 m3/ha.

PROG_MIN_TLA = 0.01           # poniżej tego ułamka maksimum gęstości tła nie ufamy ilorazowi (brzegi)
MIN_TRAKTOW_WIARYGODNY = 100  # globalny próg wiarygodności modelu (ten sam co w pozostałych skryptach KDE)

# Progi STAŁE (m3/ha), a nie percentyle rozkładu w danym okresie - z tego
# samego powodu co PROGI_ZASOBNOSCI_M3HA w kde_martwe_drewno.py: percentyl to
# wielkość względna, więc mapy różnych okresów przestałyby być porównywalne.
# Dobrane do zakresu danych: średnia krajowa rośnie z 262 do 302 m3/ha.
PROGI_ZASOBNOSCI_M3HA = [200, 250, 300, 350, 400]

# Kolor przypisany NA STAŁE do konkretnej wartości progu (nie do jej pozycji
# w rankingu) - dzięki temu pasmo ">300" ma zawsze ten sam odcień niezależnie
# od okresu i od tego, ile progów akurat się rysuje.
KOLORY_PROGOW_M3HA = {
    200: plt.cm.YlGn(0.25),
    250: plt.cm.YlGn(0.40),
    300: plt.cm.YlGn(0.55),
    350: plt.cm.YlGn(0.72),
    400: plt.cm.YlGn(0.92),
}

# Progi dla zasobności POJEDYNCZEGO gatunku - wspólne dla wszystkich gatunków,
# żeby mapy różnych gatunków (nie tylko okresów) były porównywalne. Zakres
# od 25 m3/ha (gatunki domieszkowe, np. jodła w Karpatach) do 200 m3/ha
# (sosna na Niżu, średnio 150-170 m3/ha).
PROGI_ZASOBNOSCI_GAT_M3HA = [25, 50, 100, 150, 200]

KOLORY_PROGOW_GAT_M3HA = {
    25: plt.cm.YlGn(0.25),
    50: plt.cm.YlGn(0.40),
    100: plt.cm.YlGn(0.55),
    150: plt.cm.YlGn(0.72),
    200: plt.cm.YlGn(0.92),
}


def zasobnosc_mapa(rok_start: int = 2020, rok_end: int = 2025,
                   progi: list[float] = None, gatunek: str = None):
    """
    Lokalna, wygładzona przestrzennie średnia zasobność drzewostanów (m3/ha),
    z zaznaczeniem obszarów przekraczających stałe progi.

    rok_start, rok_end - zakres lat wykonania pomiaru (ADRES_POW.DATA), nie
        numer formalnego cyklu WISL (patrz Wisl_quert.CYKLE_LATA).

    progi: lista stałych progów zasobności (m3/ha). Progi poza zakresem danych
        okresu (>= max) są automatycznie pomijane. Domyślnie
        PROGI_ZASOBNOSCI_M3HA (ogółem) albo PROGI_ZASOBNOSCI_GAT_M3HA (gatunek).

    gatunek: kod gatunku WISL (np. 'SO', 'DB' - podgatunki DB.* wliczane).
        None = zasobność wszystkich gatunków łącznie.
    """
    if progi is None:
        progi = PROGI_ZASOBNOSCI_GAT_M3HA if gatunek else PROGI_ZASOBNOSCI_M3HA
    kolory_progow = KOLORY_PROGOW_GAT_M3HA if gatunek else KOLORY_PROGOW_M3HA
    opis = f"gatunek {gatunek}" if gatunek else "ogółem"

    okres = f"{rok_start}-{rok_end}"
    if gatunek:
        res = query_zasobnosc_gat(gatunek, rok_start=rok_start, rok_end=rok_end)
    else:
        res = query_zasobnosc(rok_start=rok_start, rok_end=rok_end)
    if not res:
        print(f"Brak danych z bazy dla lat {okres} ({opis}).")
        return

    df = pd.DataFrame(res, columns=['NR_TRAKTU', 'SR_ZASOBNOSC', 'SUMA_WSP_Z'])
    df['NR_TRAKTU'] = df['NR_TRAKTU'].astype(int).astype(str)

    trakty = gpd.read_file('data/trakty_wsp.geojson')
    trakty['nr_traktu'] = trakty['nr_punktu'].astype(int).astype(str).str[:-1]
    trakty_geom = trakty[['nr_traktu', 'geometry']].copy()

    gdf_model = trakty_geom.merge(df, left_on='nr_traktu', right_on='NR_TRAKTU', how='inner')
    gdf_model = gpd.GeoDataFrame(gdf_model, geometry='geometry', crs=trakty.crs).to_crs(CRS_OBLICZENIOWY)
    gdf_model = gdf_model[gdf_model.geometry.notnull() & (gdf_model['SUMA_WSP_Z'] > 0)].copy()

    if len(gdf_model) < 5:
        print(f"Zbyt mało danych przestrzennych do wyznaczenia KDE (lata {okres}, znaleziono: {len(gdf_model)}).")
        return

    if len(gdf_model) < MIN_TRAKTOW_WIARYGODNY:
        print(
            f"Pominięto mapę: tylko {len(gdf_model)} traktów (wymagane min. "
            f"{MIN_TRAKTOW_WIARYGODNY}, lata {okres})."
        )
        return

    coords = np.vstack([gdf_model.geometry.x, gdf_model.geometry.y])

    # WAGI: g (tło) = reprezentowana powierzchnia traktu (SUMA_WSP_Z);
    #       f (licznik) = SR_ZASOBNOSC (średnia ważona na podpowierzchnię)
    #       pomnożona z powrotem przez SUMA_WSP_Z, czyli łączna miąższość
    #       przypadająca na trakt - spójnie z kde_martwe_drewno.py.
    waga_tlo = gdf_model['SUMA_WSP_Z'].to_numpy()
    waga_f = (gdf_model['SR_ZASOBNOSC'] * gdf_model['SUMA_WSP_Z']).to_numpy()

    # ==============================================================================
    # GRANICE POLSKI I SIATKA
    # ==============================================================================
    poland = gpd.read_file("data/poland_land.geojson").to_crs(CRS_OBLICZENIOWY)
    poland_geom = poland.geometry.union_all()
    granica_polski = poland_geom.boundary

    xmin, ymin, xmax, ymax = poland.total_bounds
    x_grid = np.linspace(xmin, xmax, 500)
    y_grid = np.linspace(ymin, ymax, 500)
    X, Y = np.meshgrid(x_grid, y_grid)
    positions = np.vstack([X.ravel(), Y.ravel()])

    # ==============================================================================
    # KDE (WSPÓLNE PASMO) + KOREKTA SKALI NORMALIZACJI WAG
    # ==============================================================================
    kernel_tlo = gaussian_kde(coords, weights=waga_tlo, bw_method='scott')
    # Wymuszamy TO SAMO fizyczne pasmo co dla tła - sam `factor` nie wystarcza,
    # bo scipy przelicza kowariancję z WAŻONEGO rozrzutu (kde_common).
    kernel_f = gaussian_kde(coords, weights=waga_f)
    wymus_wspolne_pasmo(kernel_f, kernel_tlo)

    # scipy normalizuje f i g NIEZALEŻNIE do całki=1 - bez tej korekty iloraz
    # byłby przeskalowany przypadkowym współczynnikiem, a nie średnią w m3/ha.
    # Jednocześnie to jest średnia krajowa ważona powierzchnią.
    srednia_krajowa = waga_f.sum() / waga_tlo.sum()

    f_est = kernel_f(positions).reshape(X.shape)
    g_est = kernel_tlo(positions).reshape(X.shape)

    mask_polska = shapely.contains_xy(poland_geom, X, Y)
    f_est[~mask_polska] = np.nan
    g_est[~mask_polska] = np.nan

    max_tla = np.nanmax(g_est)
    mask_niskie_tlo = g_est < (PROG_MIN_TLA * max_tla)

    with np.errstate(divide='ignore', invalid='ignore'):
        zasobnosc = (f_est / g_est) * srednia_krajowa

    zasobnosc[mask_niskie_tlo] = np.nan
    wartosci_valid = zasobnosc[~np.isnan(zasobnosc)]

    if wartosci_valid.size == 0:
        print(f"Brak poprawnych wartości zasobności dla lat {okres} ({opis}).")
        return

    max_zasobnosci = float(np.nanmax(wartosci_valid))

    # Progi rosnąco, ograniczone do faktycznie osiągniętych w tym okresie.
    progi_zasobnosci = sorted(p for p in set(progi) if p < max_zasobnosci)

    if not progi_zasobnosci:
        print(
            f"Lata {okres} ({opis}): zasobność nie przekracza żadnego z progów {sorted(set(progi))} "
            f"m3/ha (max={max_zasobnosci:.1f} m3/ha) - pomijam mapę."
        )
        return

    print(
        f"Zasobność {opis} | Lata: {okres} | n_traktow={len(gdf_model)} | "
        f"srednia krajowa={srednia_krajowa:.1f} m3/ha | "
        + " | ".join(f"> {p:.0f}" for p in progi_zasobnosci)
        + f" | max lokalny={max_zasobnosci:.1f} m3/ha"
    )

    # ==============================================================================
    # WIZUALIZACJA I EKSTRAKCJA GEOMETRII
    # ==============================================================================
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')

    kolory_pasm = [kolory_progow[p] for p in progi_zasobnosci]

    ax.contourf(
        X, Y, zasobnosc,
        levels=progi_zasobnosci + [max_zasobnosci],
        colors=kolory_pasm,
        alpha=0.7,
    )

    zasobnosc_contour = np.nan_to_num(zasobnosc, nan=0.0)
    cs = ax.contour(
        X, Y, zasobnosc_contour,
        levels=progi_zasobnosci,
        colors=['#1b5e20'],
        linewidths=1.2,
    )

    # Wielokąty KUMULATYWNE (zagnieżdżone): obszar wyższego progu leży w
    # całości wewnątrz niższego - jak w kde_gat.py / kde_martwe_drewno.py.
    zasiegi_geom = [kontur_na_zasieg(segs) for segs in cs.allsegs]

    # Etykiety progów wzdłuż wszystkich pętli konturu (także zamkniętych
    # wokół obszarów poniżej progu) - szczegóły w kde_common.etykietuj_kontury.
    etykietuj_kontury(ax, progi_zasobnosci, zasiegi_geom, granica_polski,
                      lambda p: f"> {p:.0f} m³/ha", kolor='black')

    gdf_model.plot(ax=ax, color='gray', markersize=3, alpha=0.3)
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

    zakresy_opis = ', '.join(
        (f'{p:.0f}–{progi_zasobnosci[i + 1]:.0f}'
         if i + 1 < len(progi_zasobnosci) else f'>{p:.0f}')
        for i, p in enumerate(progi_zasobnosci)
    )
    tytul = f"Zasobność gatunku {gatunek}" if gatunek else "Zasobność drzewostanów"
    ax.set_title(
        f"{tytul} — zakresy {zakresy_opis} m³/ha (Lata: {okres})",
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
    # Etykiety przy liniach konturu zostają progowe ("> 300 m³/ha"), bo linia
    # wyznacza właśnie przekroczenie progu.
    # Najwyższe pasmo nie ma progu górnego: zamiast samego "> p" podajemy też
    # maksimum wygładzonej powierzchni ("> 25 m³/ha (maks. 34,1)") - klasa
    # nadal zdefiniowana progiem (porównywalna między okresami), a czytelnik
    # widzi, gdzie wartości się kończą.
    maks = f'{max_zasobnosci:.1f}'.replace('.', ',')
    legend_elements = [
        mpatches.Patch(
            facecolor=kolory_pasm[i], edgecolor='#1b5e20', linewidth=1.2, alpha=0.7,
            label=(f'{progi_zasobnosci[i]:.0f}–{progi_zasobnosci[i + 1]:.0f} m³/ha'
                   if i + 1 < len(progi_zasobnosci)
                   else f'> {progi_zasobnosci[i]:.0f} m³/ha (maks. {maks})'),
        )
        for i in range(len(progi_zasobnosci) - 1, -1, -1)
    ] + [
        mlines.Line2D([], [], color='gray', marker='o', linestyle='None', markersize=4, alpha=0.4,
                      label='Trakt badany (tło)'),
        mlines.Line2D([], [], color='black', linewidth=1, label='Granica Polski'),
    ]
    ax.legend(
        handles=legend_elements, loc='center left', bbox_to_anchor=(1.01, 0.5),
        frameon=True, facecolor='white', fontsize=9, title="Legenda", title_fontsize=10,
    )

    # ==============================================================================
    # ZAPIS WYNIKÓW
    # ==============================================================================
    if not os.path.exists("KDE_zasobnosc"):
        os.makedirs("KDE_zasobnosc")

    gdf_zasieg = gpd.GeoDataFrame(
        [
            {
                'rok_start': rok_start,
                'rok_end': rok_end,
                'gatunek': gatunek,
                'prog_zasobnosci_m3ha': p,
                'zakres': f'zasobnosc >= {p:.0f} m3/ha',
                'srednia_krajowa_m3ha': float(srednia_krajowa),
                'max_zasobnosci_m3ha': max_zasobnosci,
                'n_traktow': len(gdf_model),
                'geometry': geom,
            }
            for p, geom in zip(progi_zasobnosci, zasiegi_geom)
        ],
        geometry='geometry',
        crs=CRS_OBLICZENIOWY,
    )

    sufiks_prog = "_".join(str(int(p)) for p in progi_zasobnosci)
    sufiks_gat = f"_{gatunek}" if gatunek else ""
    file_prefix = f"zasobnosc{sufiks_gat}_{okres}_prog{sufiks_prog}"

    gdf_zasieg.to_crs(CRS_ZAPISU).to_file(
        f"KDE_zasobnosc/{file_prefix}.geojson", driver="GeoJSON"
    )
    fig.savefig(f"KDE_zasobnosc/{file_prefix}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Zakończono pomyślnie. Zapisano wyniki dla lat {okres} ({opis}).")


if __name__ == "__main__":
    from Wisl_quert import CYKLE_LATA
    gatunki = [None, 'SO', 'ŚW', 'JD', 'MD', 'DB', 'BK', 'BRZ', 'OL']
    for gat in gatunki:
        for rok_start, rok_end in CYKLE_LATA:
            zasobnosc_mapa(rok_start=rok_start, rok_end=rok_end, gatunek=gat)
