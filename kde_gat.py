import os
import matplotlib.pyplot as plt
from matplotlib import patches as mpatches
from matplotlib import lines as mlines
from matplotlib import patheffects
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from scipy.stats import gaussian_kde
from shapely.geometry import Polygon
from Wisl_quert import query_udzial_gat, query_tlo_drzewostany
from kde_common import (
    wymus_wspolne_pasmo,
    TekstWzdlugKonturu,
    wytnij_fragment_konturu,
    dlugosc_tekstu_w_danych,
)
from matplotlib_map_utils.core.north_arrow import north_arrow
from matplotlib_map_utils.core.scale_bar import scale_bar
import contextily as cx

# Układ obliczeniowy i wyświetlania: PUWG92 (EPSG:2180) - metryczny
CRS_OBLICZENIOWY = "EPSG:2180"
CRS_ZAPISU = "EPSG:4326"

# ==============================================================================
# DLACZEGO ILORAZ DWÓCH GĘSTOŚCI, A NIE POJEDYNCZE KDE GATUNKU
# ==============================================================================
# Wcześniejsza wersja liczyła JEDNĄ gęstość KDE ważoną reprezentatywnością
# gatunku i wycinała z niej obszar skupiający 95% masy. To jest wielkość
# WZGLĘDNA: scipy.stats.gaussian_kde zawsze normalizuje się do całki 1, więc
# cała "masa" gatunku w Polsce sumuje się do stałej niezależnie od tego, ile
# faktycznie jest dębu. Udział względny danego miejsca w tej stałej sumie to
# gra o sumie zerowej - jeśli gatunku przybędzie GDZIEKOLWIEK indziej,
# wartości we wszystkich pozostałych regionach muszą spaść, choć nic się tam
# fizycznie nie zmieniło.
#
# Sprawdzone testem kontrolowanym na prawdziwych współrzędnych traktów:
# region o NIEZMIENNYM udziale 0,4 dostawał gęstość 2,77e-11, a po samym
# tylko podwojeniu udziału w odległym regionie - 1,88e-11 (spadek o 32%);
# margines nad progiem 95% spadał z 7,73x do 4,82x. Przy słabszym sygnale
# region "zanika" z mapy bez żadnej realnej zmiany. To dyskwalifikowało
# metodę dla porównań MIĘDZY CYKLAMI, czyli dokładnie tego, po co te mapy
# powstają.
#
# Rozwiązanie to ten sam estymator Nadaraya-Watson, który sprawdził się już
# w kde_martwe_drewno.py: iloraz dwóch KDE o WSPÓLNYM paśmie.
#   f = KDE ważone reprezentatywnoscia gatunku (UDZIAL_MIAZSZOSC * ZADRZEW * WSP_Z)
#   g = KDE ważone reprezentatywnością WSZYSTKICH zbadanych drzewostanów
#       (ZADRZEW * WSP_Z), niezależnie od gatunku - query_tlo_drzewostany
# Wynik f/g to lokalny, wygładzony przestrzennie UDZIAŁ gatunku w miąższości
# drzewostanów (0-1) - wielkość bezwzględna o sensie fizycznym. Ten sam test
# kontrolowany daje dla niezmienionego regionu 0,3672 w OBU scenariuszach.
#
# Te same dwie pułapki co przy martwym drewnie są tu obsłużone tak samo:
# wspólne pasmo licznika i mianownika (wymus_wspolne_pasmo - sam `factor` nie
# wystarcza) oraz korekta skali normalizacji wag (scipy normalizuje f i g
# niezależnie do całki 1, więc surowy iloraz jest przeskalowany przypadkowym
# współczynnikiem, a nie udziałem w jednostkach fizycznych).
#
# Korekta brzegowa Diggle'a (kde_common.korekta_brzegowa), potrzebna przy
# pojedynczej gęstości, nie jest tu już stosowana: przy ilorazie dwóch
# gęstości o tym samym paśmie błąd brzegowy w przybliżeniu się kasuje
# (licznik i mianownik tracą przy granicy tę samą część masy jądra) - tak
# samo jak w kde_uszkodzenia.py i kde_martwe_drewno.py.

PROG_MIN_TLA = 0.01           # poniżej tego ułamka maksimum gęstości tła nie ufamy ilorazowi (brzegi)
MIN_TRAKTOW_WIARYGODNY = 100  # globalny próg wiarygodności modelu (ten sam co w pozostałych skryptach KDE)

# Progi STAŁE (udział gatunku w miąższości drzewostanów), a nie percentyle
# rozkładu w danym cyklu - z tego samego powodu co PROGI_ZASOBNOSCI_M3HA w
# kde_martwe_drewno.py: percentyl to znowu wielkość względna, więc mapy
# różnych cykli przestałyby być porównywalne, czyli wróciłby dokładnie ten
# problem, który ta metoda ma rozwiązywać.
# Najniższy próg (5%) pełni rolę dawnego "zasięgu gatunku": obszar, na którym
# gatunek stanowi co najmniej 5% miąższości lokalnego lasu.
PROGI_UDZIALU = [0.05, 0.10, 0.25, 0.50]

# Kolor przypisany NA STAŁE do konkretnej wartości progu (nie do jej pozycji
# w rankingu) - dzięki temu pasmo ">25%" ma zawsze ten sam odcień niezależnie
# od cyklu i od tego, ile innych progów akurat się rysuje.
KOLORY_PROGOW = {
    0.05: plt.cm.YlGn(0.30),
    0.10: plt.cm.YlGn(0.50),
    0.25: plt.cm.YlGn(0.70),
    0.50: plt.cm.YlGn(0.92),
}


def plot_kde_for_species(gat, cykl=4, drzewostany=True, progi=PROGI_UDZIALU):
    """
    Lokalny, wygładzony przestrzennie udział gatunku w miąższości drzewostanów,
    z zaznaczeniem obszarów przekraczających stałe progi udziału.

    drzewostany=True  - licznik ograniczony do powierzchni, na których gatunek
        DOMINUJE (udział miąższości > 50%, ZADRZEW >= 0,3): mapa zasięgu
        drzewostanów danego gatunku.
    drzewostany=False - licznik obejmuje każde wystąpienie gatunku, także jako
        domieszki: mapa zasięgu samego gatunku.

    Mianownik (tło) jest w OBU przypadkach ten sam - wszystkie zbadane
    drzewostany - więc obie mapy są wyrażone w tej samej, porównywalnej skali.
    """
    adnotacja = "drzewostany" if drzewostany else "gatunek"

    # ==============================================================================
    # 1. DANE: LICZNIK (GATUNEK) I MIANOWNIK (WSZYSTKIE DRZEWOSTANY)
    # ==============================================================================
    udzial_gat = query_udzial_gat(gat, cykl)
    if not udzial_gat:
        print(f"Brak danych z bazy dla gatunku {gat} w cyklu {cykl}.")
        return

    df_gat = pd.DataFrame(udzial_gat, columns=[
        'NR_PODPOW', 'NR_CYKLU', 'UDZIAL_MIAZSZOSC', 'reprezentatywnosc_gat',
        'ZADRZEW', 'SUMA_MIAZSZOSC_gat', 'SUMA_MIAZSZOSC'])

    # Ten sam filtr dominacji co w heatmap_data.heatmap_gatunki - gatunek
    # tworzy drzewostan, a nie jest tylko domieszką.
    if drzewostany:
        df_gat = df_gat.query("UDZIAL_MIAZSZOSC > 0.5 & ZADRZEW >= 0.3")

    if df_gat.empty:
        print(f"Brak powierzchni po odfiltrowaniu ({adnotacja}) dla gatunku {gat} w cyklu {cykl}.")
        return

    tlo = query_tlo_drzewostany(cykl)
    if not tlo:
        print(f"Brak danych tła dla cyklu {cykl}.")
        return

    df_tlo = pd.DataFrame(tlo, columns=['NR_PODPOW', 'waga_tlo', 'SUMA_MIAZSZOSC'])

    # ==============================================================================
    # 2. AGREGACJA DO TRAKTU
    # ==============================================================================
    for df in (df_gat, df_tlo):
        df['NR_TRAKTU'] = pd.to_numeric(df['NR_PODPOW']).astype('int64') // 1000

    f_trakty = df_gat.groupby('NR_TRAKTU', as_index=False)['reprezentatywnosc_gat'].sum()
    g_trakty = df_tlo.groupby('NR_TRAKTU', as_index=False)['waga_tlo'].sum()

    # LEFT JOIN od tła: trakty bez gatunku zostają w modelu z wagą licznika 0.
    # To nie jest kosmetyka - bez nich iloraz liczyłby lokalną średnią tylko
    # po powierzchniach, na których gatunek już jest, więc wszędzie wychodziłby
    # zawyżony udział (a obszary bez gatunku w ogóle nie obniżałyby wyniku).
    df_model = g_trakty.merge(f_trakty, on='NR_TRAKTU', how='left')
    df_model['reprezentatywnosc_gat'] = df_model['reprezentatywnosc_gat'].fillna(0.0)
    df_model['NR_TRAKTU'] = df_model['NR_TRAKTU'].astype(str)

    # ==============================================================================
    # 3. GEOMETRIA TRAKTÓW
    # ==============================================================================
    trakty = gpd.read_file('data/trakty_wsp.geojson')
    trakty['nr_traktu'] = trakty['nr_punktu'].astype(int).astype(str).str[:-1]
    trakty_geom = trakty[['nr_traktu', 'geometry']].drop_duplicates(subset=['nr_traktu'])

    gdf_model = trakty_geom.merge(df_model, left_on='nr_traktu', right_on='NR_TRAKTU', how='inner')
    gdf_model = gpd.GeoDataFrame(gdf_model, geometry='geometry', crs=trakty.crs).to_crs(CRS_OBLICZENIOWY)
    gdf_model = gdf_model[gdf_model.geometry.notnull() & (gdf_model['waga_tlo'] > 0)].copy()

    maska_gat = gdf_model['reprezentatywnosc_gat'] > 0
    n_traktow_gat = int(maska_gat.sum())

    if len(gdf_model) < 5:
        print(f"Zbyt mało danych przestrzennych do wyznaczenia KDE (cykl {cykl}, znaleziono: {len(gdf_model)}).")
        return

    if n_traktow_gat < MIN_TRAKTOW_WIARYGODNY:
        print(
            f"Pominięto mapę: gatunek {gat} ({adnotacja}) występuje tylko na "
            f"{n_traktow_gat} traktach (wymagane min. {MIN_TRAKTOW_WIARYGODNY}, cykl {cykl})."
        )
        return

    # ==============================================================================
    # 4. SIATKA PRZESTRZENNA I GRANICE POLSKI
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
    # 5. KDE (WSPÓLNE PASMO) + KOREKTA SKALI NORMALIZACJI WAG
    # ==============================================================================
    coords = np.vstack([gdf_model.geometry.x, gdf_model.geometry.y])
    waga_tlo = gdf_model['waga_tlo'].to_numpy()
    waga_f = gdf_model['reprezentatywnosc_gat'].to_numpy()

    kernel_tlo = gaussian_kde(coords, weights=waga_tlo, bw_method='scott')
    kernel_f = gaussian_kde(coords, weights=waga_f)
    wymus_wspolne_pasmo(kernel_f, kernel_tlo)

    wspolczynnik_korekty_skali = waga_f.sum() / waga_tlo.sum()

    f_est = kernel_f(positions).reshape(X.shape)
    g_est = kernel_tlo(positions).reshape(X.shape)

    mask_polska = shapely.contains_xy(poland_geom, X, Y)
    f_est[~mask_polska] = np.nan
    g_est[~mask_polska] = np.nan

    max_tla = np.nanmax(g_est)
    mask_niskie_tlo = g_est < (PROG_MIN_TLA * max_tla)

    with np.errstate(divide='ignore', invalid='ignore'):
        udzial_gatunku = (f_est / g_est) * wspolczynnik_korekty_skali

    udzial_gatunku[mask_niskie_tlo] = np.nan
    wartosci_valid = udzial_gatunku[~np.isnan(udzial_gatunku)]

    if wartosci_valid.size == 0:
        print(f"Brak poprawnych wartości udziału dla gatunku {gat} w cyklu {cykl}.")
        return

    max_udzialu = float(np.nanmax(wartosci_valid))

    # Progi rosnąco, ograniczone do faktycznie osiągniętych w tym cyklu
    # (próg >= max nie wyznaczyłby żadnego obszaru na contourf/contour).
    progi_udzialu = sorted(p for p in set(progi) if p < max_udzialu)

    if not progi_udzialu:
        print(
            f"Gatunek {gat} ({adnotacja}), cykl {cykl}: udział nie przekracza żadnego z progów "
            f"{sorted(set(progi))} (max={max_udzialu:.3f}) - pomijam mapę."
        )
        return

    print(
        f"Gatunek: {gat} ({adnotacja}) | Cykl: {cykl} | n_traktow={len(gdf_model)} "
        f"(z gatunkiem: {n_traktow_gat}) | udział krajowy={wspolczynnik_korekty_skali:.3f} | "
        f"max lokalny={max_udzialu:.3f}"
    )

    # Etykiety muszą opisywać PRZEDZIAŁY, a nie progi: contourf koloruje
    # rozłączne pasma (levels = progi + [max]), więc najjaśniejszy kolor to
    # np. 5-10%, a nie "wszystko powyżej 5%". Wielokąty zapisywane do GeoJSON są
    # natomiast kumulatywne (zagnieżdżone) - tam prog_udzialu=0,05 to faktycznie
    # cały obszar powyżej 5%. Dwie różne konwencje w dwóch różnych wynikach.
    def etykieta_pasma(i):
        prog = progi_udzialu[i]
        if i + 1 < len(progi_udzialu):
            return f'{prog:.0%}–{progi_udzialu[i + 1]:.0%} miąższości'
        return f'> {prog:.0%} miąższości'

    # ==============================================================================
    # 6. WIZUALIZACJA I EKSTRAKCJA GEOMETRII
    # ==============================================================================
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')

    kolory_pasm = [KOLORY_PROGOW[prog] for prog in progi_udzialu]

    ax.contourf(
        X, Y, udzial_gatunku,
        levels=progi_udzialu + [max_udzialu],
        colors=kolory_pasm,
        alpha=0.7,
    )

    udzial_contour = np.nan_to_num(udzial_gatunku, nan=0.0)
    cs = ax.contour(
        X, Y, udzial_contour,
        levels=progi_udzialu,
        colors=['#1b5e20'],
        linewidths=1.2,
    )

    # Geometria każdego zakresu osobno - cs.allsegs[i] to segmenty konturu
    # dla i-tego progu z `progi_udzialu`, w tej samej kolejności.
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

    # Etykiety KSZTAŁTEM I POŁOŻENIEM DOPASOWANE DO PRZEBIEGU KONTURU - ta sama
    # metoda co w kde_martwe_drewno.py: każdy znak jest osobno pozycjonowany
    # i obracany wzdłuż wyciętego fragmentu linii konturu (TekstWzdlugKonturu
    # w kde_common.py), więc napis "podąża" za krzywizną granicy zasięgu
    # zamiast przecinać ją pod przypadkowym kątem.
    #
    # Etykieta linii jest PROGOWA ("> 5%"), a nie przedziałowa jak w legendzie -
    # linia wyznacza właśnie przekroczenie progu, więc to jest tu poprawny opis.
    #
    # Punkt kotwiczący dla progu N trafia w PIERŚCIEŃ tego pasma (obszar
    # >= prog_N, ale poza zagnieżdżonym obszarem >= prog_N+1) - inaczej punkty
    # zagnieżdżonych progów zbiegałyby się w tym samym, najbardziej wewnętrznym
    # miejscu i etykiety nakładałyby się na siebie. Kandydatów filtrujemy po
    # odległości od granicy Polski, żeby napis nie wyglądał jak opis granicy
    # kraju.
    MIN_POWIERZCHNIA_ETYKIETY = 3e8  # m^2 (300 km^2) - nie etykietujemy znikomych strzępków zakresu
    BORDER_TOL_ETYKIETY = 15_000  # m - punkt kotwiczący musi leżeć dalej od granicy Polski niż to
    MIN_ODSTEP_ETYKIET = 150_000  # m - minimalny odstęp między powtórzeniami etykiety tego samego pasma
    kandydaci_etykiet = []
    for i, prog in enumerate(progi_udzialu):
        geom = zasiegi_geom[i]
        if i + 1 < len(zasiegi_geom):
            geom = geom.difference(zasiegi_geom[i + 1])
        if geom.is_empty:
            continue
        czesci = [g for g in getattr(geom, 'geoms', [geom]) if isinstance(g, Polygon)]
        for czesc in czesci:
            if czesc.is_empty or czesc.area < MIN_POWIERZCHNIA_ETYKIETY:
                continue
            wierzcholki = np.array(czesc.exterior.coords)
            odleglosc_od_granicy = shapely.distance(shapely.points(wierzcholki), granica_polski)
            maska_daleko = odleglosc_od_granicy > BORDER_TOL_ETYKIETY
            if not maska_daleko.any():
                continue
            idx_wg_odleglosci = np.argsort(-np.where(maska_daleko, odleglosc_od_granicy, -np.inf))
            wybrane_idx = []
            for idx in idx_wg_odleglosci:
                if not maska_daleko[idx]:
                    break
                if all(
                    np.linalg.norm(wierzcholki[idx] - wierzcholki[w]) >= MIN_ODSTEP_ETYKIET
                    for w in wybrane_idx
                ):
                    wybrane_idx.append(int(idx))
            for idx in wybrane_idx:
                kandydaci_etykiet.append((prog, wierzcholki, idx))

    if kandydaci_etykiet:
        # Wymuszamy jednorazowe rysowanie figury, żeby mieć działający
        # `renderer` - potrzebny do zmierzenia FAKTYCZNEJ szerokości znaków
        # etykiety, zanim wytniemy pod nie fragment linii konturu.
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        for prog, wierzcholki, idx_najdalszy in kandydaci_etykiet:
            tekst = f"> {prog:.0%}"
            dlugosc = dlugosc_tekstu_w_danych(ax, tekst, fontsize=6, renderer=renderer)
            fragment = wytnij_fragment_konturu(wierzcholki, idx_najdalszy, dlugosc)
            if len(fragment) < 2:
                continue
            etykieta = TekstWzdlugKonturu(
                fragment[:, 0], fragment[:, 1], tekst, ax,
                fontsize=6, color='#0d3b10',
            )
            etykieta.set_path_effects([patheffects.withStroke(linewidth=2.5, foreground='white')])

    gdf_model.plot(ax=ax, color='gray', markersize=3, alpha=0.3)
    gdf_model[maska_gat].plot(ax=ax, color='red', markersize=6, alpha=0.5)
    poland.boundary.plot(ax=ax, color='black', linewidth=1)

    north_arrow(
        ax,
        location="upper left",
        rotation={"crs": poland.crs, "reference": "center"},
        shadow=False,
        scale=0.4,
    )
    scale_bar(
        ax,
        location="upper right",
        style="ticks",
        bar={"projection": poland.crs, "unit": "km", "tick_loc": "middle"},
        labels={"loc": "above", "fontsize": 8},
        units={"loc": "bar", "fontsize": 8},
    )

    # ==============================================================================
    # 7. KADR MAPY I STYLIZACJA
    # ==============================================================================
    MARGIN = 20_000
    ax.set_xlim(xmin - MARGIN, xmax + MARGIN)
    ax.set_ylim(ymin - MARGIN, ymax + MARGIN)

    ax.grid(True, linestyle='--', alpha=0.5, color='gray')
    ax.set_title(
        f"Udział gatunku {gat} w miąższości drzewostanów - zakresy "
        f"{', '.join(etykieta_pasma(i).replace(' miąższości', '') for i in range(len(progi_udzialu)))} "
        f"(Cykl: {cykl} | {adnotacja})",
        fontsize=11,
    )
    ax.set_xlabel("X [m] (PUWG92 / EPSG:2180)")
    ax.set_ylabel("Y [m] (PUWG92 / EPSG:2180)")
    ax.ticklabel_format(style='plain', useOffset=False)

    cx.add_basemap(ax, crs=poland.crs, source=cx.providers.Esri.WorldGrayCanvas, alpha=1, zoom=8)

    # ==============================================================================
    # 8. LEGENDA (PROXY ARTISTS)
    # ==============================================================================
    etykieta_punktow = (
        'Trakt z drzewostanem gatunku' if drzewostany else 'Trakt z gatunkiem'
    )
    legend_elements = [
        mpatches.Patch(
            facecolor=kolory_pasm[i], edgecolor='#1b5e20', linewidth=1.2, alpha=0.7,
            label=etykieta_pasma(i),
        )
        for i in range(len(progi_udzialu) - 1, -1, -1)
    ] + [
        mlines.Line2D([], [], color='red', marker='o', linestyle='None', markersize=6,
                      alpha=0.5, label=etykieta_punktow),
        mlines.Line2D([], [], color='gray', marker='o', linestyle='None', markersize=4,
                      alpha=0.4, label='Trakt badany (tło)'),
        mlines.Line2D([], [], color='black', linewidth=1, label='Granica Polski'),
    ]

    ax.legend(
        handles=legend_elements, loc='center left', bbox_to_anchor=(1.01, 0.5),
        frameon=True, facecolor='white', fontsize=9,
        title="Legenda", title_fontsize=10,
    )

    # ==============================================================================
    # 9. ZAPIS DO PLIKÓW
    # ==============================================================================
    if not os.path.exists("KDE_gatunki"):
        os.makedirs("KDE_gatunki")

    gdf_zasieg = gpd.GeoDataFrame(
        [
            {
                'gatunek': gat,
                'cykl': cykl,
                'typ_zasiegu': adnotacja,
                'prog_udzialu': prog,
                # Wielokąty są KUMULATYWNE (zagnieżdżone): obszar progu 0,10
                # leży w całości wewnątrz obszaru progu 0,05. To inna konwencja
                # niż rozłączne pasma kolorów na PNG - stąd jawny opis.
                'zakres': f'udzial >= {prog:.0%}',
                'udzial_krajowy': float(wspolczynnik_korekty_skali),
                'max_udzialu': max_udzialu,
                'n_traktow': len(gdf_model),
                'n_traktow_gat': n_traktow_gat,
                'geometry': geom,
            }
            for prog, geom in zip(progi_udzialu, zasiegi_geom)
        ],
        geometry='geometry',
        crs=CRS_OBLICZENIOWY,
    )

    # Eksport do EPSG:4326 (WGS84) dla portalu webowego / Folium
    gdf_zasieg.to_crs(CRS_ZAPISU).to_file(
        f"KDE_gatunki/zasieg_{gat}_cykl_{cykl}_{adnotacja}_epsg4326.geojson", driver="GeoJSON"
    )
    fig.savefig(f"KDE_gatunki/mapa_{gat}_cykl_{cykl}_{adnotacja}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Zakończono pomyślnie. Zapisano wyniki dla gatunku {gat} ({adnotacja}), cykl {cykl}.")


if __name__ == "__main__":
    gatunki = ['SO', 'ŚW', 'JD', 'MD', 'DB', 'BK', 'BRZ', 'OL']
    cykle = [1, 2, 3, 4]
    for gat in gatunki:
        for cykl in cykle:
            plot_kde_for_species(gat=gat, cykl=cykl, drzewostany=True)
