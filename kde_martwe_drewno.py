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
from Wisl_quert import martwe_drewno
from matplotlib_map_utils.core.north_arrow import north_arrow
from matplotlib_map_utils.core.scale_bar import scale_bar
from kde_common import wymus_wspolne_pasmo
import contextily as cx

# Układ obliczeniowy i wyświetlania: PUWG92 (EPSG:2180) - metryczny
CRS_OBLICZENIOWY = "EPSG:2180"
CRS_ZAPISU = "EPSG:4326"

# ==============================================================================
# DLACZEGO TO NIE JEST TA SAMA METODYKA CO DLA USZKODZEŃ
# ==============================================================================
# Uszkodzenia to było zdarzenie (trakt uszkodzony / nie), więc pytaliśmy
# "czy to zdarzenie koncentruje się bardziej niż wynikałoby z tła" -
# stąd sparr::risk() i test istotności zbudowany pod porównanie dwóch
# procesów punktowych (przypadek/kontrola).
#
# Zasobność martwego drewna to CIĄGŁA zmienna zmierzona na każdym trakcie
# (nie "czy", tylko "ile"). Właściwe pytanie to nie "czy to anomalia
# względem tła", tylko "jaka jest lokalna, wygładzona przestrzennie
# ŚREDNIA zasobność" - poprawnie skorygowana o nierówną gęstość
# próbkowania (schematyczna siatka WISL, czasem tylko część powierzchni
# w trakcie faktycznie założona).
#
# To jest estymator Nadaraya-Watson: iloraz dwóch KDE (f = zasobność
# ważona reprezentatywnością, g = sama reprezentatywność wszystkich
# traktów) - matematycznie to samo narzędzie co przy uszkodzeniach,
# inna interpretacja wyniku (lokalna średnia, nie ryzyko względne).
#
# WAŻNA PUŁAPKA: scipy.stats.gaussian_kde normalizuje wagi OSOBNO dla f
# i dla g (każda gęstość integruje się do 1, niezależnie od surowej sumy
# wag wejściowych). Samo f/g byłoby więc przeskalowane przypadkowym
# współczynnikiem, nie prawdziwą średnią w jednostkach fizycznych
# (m3/ha). Trzeba to skorygować mnożąc przez sum(waga_f)/sum(waga_tlo) -
# patrz WSPOLCZYNNIK_KOREKTY_SKALI poniżej. Sprawdzone testem na danych
# syntetycznych ze znanym trendem - bez korekty błąd był ~20-krotny,
# z korektą <5%.
#
# Percentyl progu (żeby zaznaczyć "obszary najbardziej zasobne") liczony
# jest na WYNIKU (już unormowanej lokalnej średniej), nie na surowej
# gęstości f - to jest różnica względem błędu, który popełniliśmy
# najpierw przy uszkodzeniach (percentyl na surowej gęstości dawał
# pokrycie ~90% kraju). Tutaj percentyl na już poprawnie skalowanej
# średniej jest sensowny i porównywalny z tym, jak BULiGL raportuje
# zasobność w tabelach (m3/ha), tylko w wersji ciągłej zamiast podziału
# na województwa.
CRS_OBLICZENIOWY_ = CRS_OBLICZENIOWY  # (alias niepotrzebny, zostawiony dla czytelności importu wyżej)

PERCENTYL_ZASOBNOSCI = 95  # "top 5% kraju pod względem lokalnej średniej zasobności"
PROG_MIN_TLA = 0.01        # poniżej tego ułamka maksimum gęstości tła nie ufamy ilorazowi (brzegi)
MIN_TRAKTOW_WIARYGODNY = 100  # globalny próg wiarygodności modelu (ten sam co przy KDE gatunków)


def martwe_drewno_mapa(nr_cykl: int = 1, typ: int | None = None, percentyl: int = PERCENTYL_ZASOBNOSCI):
    """
    Lokalna, wygładzona przestrzennie średnia zasobność martwego drewna
    (m3/ha), z zaznaczeniem obszarów o najwyższej zasobności (górny
    percentyl rozkładu tej średniej).

    Wisl_quert.martwe_drewno(nr_cykl) zwraca dane per trakt i per TYP
    martwego drewna (1-3 leżące, 4 posusz, 5 złom — patrz dokumentacja
    WISL), już podzielone przez SUMA_WSP_Z traktu (SR_MIAZSZOSC to
    gotowa średnia ważona na poziomie podpowierzchni, zagregowana do
    traktu) — ale SUMA_WSP_Z jest też zwracane osobno, bo potrzebujemy
    go jako wagi reprezentatywności do przestrzennego wygładzania KDE,
    niezależnie od tego, że posłużyło już do policzenia SR_MIAZSZOSC.

    typ: opcjonalny filtr konkretnego typu martwego drewna (int).
        None = suma wszystkich typów na trakt (ten sam mianownik
        SUMA_WSP_Z obowiązuje dla każdego typu w danym trakcie, więc
        sumowanie SR_MIAZSZOSC po typach jest poprawne matematycznie).
    """
    res = martwe_drewno(nr_cykl=nr_cykl)
    if not res:
        print(f"Brak danych z bazy dla cyklu {nr_cykl}.")
        return

    df = pd.DataFrame(res, columns=['NR_TRAKTU', 'TYP', 'SR_MIAZSZOSC', 'SUMA_WSP_Z'])

    if df.empty:
        print(f"Brak danych dla cyklu {nr_cykl}.")
        return

    # Pełna populacja (tło) — KAŻDY trakt z z_pow_les pojawia się co najmniej
    # raz dzięki LEFT JOIN w zapytaniu SQL (trakty bez martwego drewna mają
    # TYP=NULL, SR_MIAZSZOSC=0). Bierzemy ją NIEZALEŻNIE od filtra `typ`,
    # żeby zawężenie do jednego typu nie zmniejszało populacji odniesienia.
    tlo_trakty = df.groupby('NR_TRAKTU', as_index=False)['SUMA_WSP_Z'].first()

    # Licznik: zasobność wybranego typu (albo suma wszystkich typów, gdy
    # typ=None — wiersze placeholder z SR_MIAZSZOSC=0 nic tu nie zmieniają).
    df_f = df[df['TYP'] == typ] if typ is not None else df
    zasobnosc_trakty = df_f.groupby('NR_TRAKTU', as_index=False)['SR_MIAZSZOSC'].sum()

    # Złączenie: trakty bez wybranego typu (ale obecne w populacji) dostają 0,
    # zamiast znikać z analizy.
    df_trakt = tlo_trakty.merge(zasobnosc_trakty, on='NR_TRAKTU', how='left')
    df_trakt['SR_MIAZSZOSC'] = df_trakt['SR_MIAZSZOSC'].fillna(0.0)
    df_trakt['NR_TRAKTU'] = df_trakt['NR_TRAKTU'].astype(int).astype(str)

    trakty = gpd.read_file('data/trakty_wsp.geojson')
    trakty['nr_traktu'] = trakty['nr_punktu'].astype(int).astype(str).str[:-1]
    trakty_geom = trakty[['nr_traktu', 'geometry']].copy()

    gdf_model = trakty_geom.merge(df_trakt, left_on='nr_traktu', right_on='NR_TRAKTU', how='inner')
    gdf_model = gpd.GeoDataFrame(gdf_model, geometry='geometry', crs=trakty.crs).to_crs(CRS_OBLICZENIOWY)
    gdf_model = gdf_model[gdf_model.geometry.notnull() & (gdf_model['SUMA_WSP_Z'] > 0)].copy()

    if len(gdf_model) < 5:
        print(f"Zbyt mało danych przestrzennych do wyznaczenia KDE (cykl {nr_cykl}, znaleziono: {len(gdf_model)}).")
        return

    wiarygodne = len(gdf_model) >= MIN_TRAKTOW_WIARYGODNY
    if not wiarygodne:
        print(
            f"Uwaga: tylko {len(gdf_model)} traktów (próg wiarygodności: "
            f"{MIN_TRAKTOW_WIARYGODNY}). Wynik może być niewiarygodny."
        )

    coords = np.vstack([gdf_model.geometry.x, gdf_model.geometry.y])

    # WAGI: g (tło) = reprezentatywność wszystkich traktów (SUMA_WSP_Z);
    #       f (licznik) = SR_MIAZSZOSC (już będące średnią ważoną na
    #       podpowierzchnię) pomnożone z powrotem przez SUMA_WSP_Z, żeby
    #       odtworzyć "łączną masę ważoną" traktu - spójne z tym, jak
    #       ważymy pozostałe warstwy KDE w repo (zasobnosc * waga_repr).
    # Te same współrzędne (coords) dla obu - trakty bez martwego drewna
    # mają waga_f=0, więc nic nie wnoszą do licznika, ale poprawnie
    # obniżają lokalną średnią przez swój wkład w mianowniku (g).
    waga_tlo = gdf_model['SUMA_WSP_Z'].to_numpy()
    waga_f = (gdf_model['SR_MIAZSZOSC'] * gdf_model['SUMA_WSP_Z']).to_numpy()

    # ==============================================================================
    # GRANICE POLSKI I SIATKA
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
    # Wymuszamy TO SAMO fizyczne pasmo co dla tła - sam `factor` (kde_gat.py
    # / stara wersja tego pliku) na to nie wystarcza, bo scipy przelicza
    # covariance na nowo z WAŻONEGO rozrzutu przekazanych danych (tu: te same
    # współrzędne, ale inne wagi -> inna ważona kowariancja mimo identycznego
    # `factor`; patrz kde_common.wymus_wspolne_pasmo).
    kernel_f = gaussian_kde(coords, weights=waga_f)
    wymus_wspolne_pasmo(kernel_f, kernel_tlo)

    # scipy normalizuje f i g NIEZALEŻNIE do całki=1 - bez tej korekty iloraz
    # byłby przeskalowany przypadkowym współczynnikiem, nie prawdziwą
    # średnią w m3/ha. Patrz uzasadnienie i test w komentarzu na górze pliku.
    wspolczynnik_korekty_skali = waga_f.sum() / waga_tlo.sum()

    f_est = kernel_f(positions).reshape(X.shape)
    g_est = kernel_tlo(positions).reshape(X.shape)

    mask_polska = shapely.contains_xy(poland_geom, X, Y)
    f_est[~mask_polska] = np.nan
    g_est[~mask_polska] = np.nan

    max_tla = np.nanmax(g_est)
    mask_niskie_tlo = g_est < (PROG_MIN_TLA * max_tla)

    with np.errstate(divide='ignore', invalid='ignore'):
        srednia_zasobnosc = (f_est / g_est) * wspolczynnik_korekty_skali

    srednia_zasobnosc[mask_niskie_tlo] = np.nan
    wartosci_valid = srednia_zasobnosc[~np.isnan(srednia_zasobnosc)]

    if wartosci_valid.size == 0:
        print(f"Brak poprawnych wartości zasobności dla cyklu {nr_cykl}.")
        return

    prog_zasobnosci = np.percentile(wartosci_valid, percentyl)

    print(
        f"Martwe drewno | Cykl: {nr_cykl} | n_traktow={len(gdf_model)} | "
        f"srednia krajowa={np.nanmean(wartosci_valid):.2f} m3/ha | "
        f"prog ({percentyl}. percentyl)={prog_zasobnosci:.2f} m3/ha | "
        f"max={np.nanmax(wartosci_valid):.2f} m3/ha"
    )

    # ==============================================================================
    # WIZUALIZACJA I EKSTRAKCJA GEOMETRII
    # ==============================================================================
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')

    cf = ax.contourf(
        X, Y, srednia_zasobnosc,
        cmap=plt.cm.YlOrBr,
        levels=[prog_zasobnosci, np.nanmax(wartosci_valid)],
        alpha=0.6,
    )
    kde_color = cf.get_facecolor()[0] if hasattr(cf, 'get_facecolor') else cf.collections[0].get_facecolor()[0]

    zasobnosc_contour = np.nan_to_num(srednia_zasobnosc, nan=0.0)
    cs = ax.contour(
        X, Y, zasobnosc_contour,
        levels=[prog_zasobnosci],
        colors=['#6b3d00'],
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
    gdf_model[gdf_model['SR_MIAZSZOSC'] > 0].plot(ax=ax, color='saddlebrown', markersize=6, alpha=0.6)
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

    ax.set_title(
        f"Zasobność martwego drewna — top {100-percentyl}% kraju "
        f"(Cykl: {nr_cykl}, próg: {prog_zasobnosci:.1f} m3/ha)",
        fontsize=11,
    )
    ax.set_xlabel("X [m] (EPSG:2180)")
    ax.set_ylabel("Y [m] (EPSG:2180)")
    ax.ticklabel_format(style='plain', useOffset=False)

    try:
        cx.add_basemap(ax, crs=poland.crs, source=cx.providers.Esri.WorldGrayCanvas, alpha=1, zoom=8)
    except Exception:
        pass

    legend_elements = [
        mpatches.Patch(
            facecolor=kde_color, edgecolor='#6b3d00', linewidth=1.5, alpha=0.6,
            label=f'Top {100-percentyl}% zasobności (≥ {prog_zasobnosci:.1f} m³/ha)',
        ),
        mlines.Line2D([], [], color='saddlebrown', marker='o', linestyle='None', markersize=6, alpha=0.6,
                      label='Trakt z martwym drewnem'),
        mlines.Line2D([], [], color='gray', marker='o', linestyle='None', markersize=4, alpha=0.4,
                      label='Trakt badany (tło)'),
        mlines.Line2D([], [], color='black', linewidth=1, label='Granica Polski'),
    ]
    ax.legend(handles=legend_elements, loc='lower left', bbox_to_anchor=(0.01, 0.03), frameon=True, facecolor='white')

    # ==============================================================================
    # ZAPIS WYNIKÓW
    # ==============================================================================
    if not os.path.exists("KDE_martwe_drewno"):
        os.makedirs("KDE_martwe_drewno")

    gdf_zasieg = gpd.GeoDataFrame(
        [{
            'cykl': nr_cykl,
            'typ_martwego_drewna': typ if typ is not None else 'wszystkie',
            'percentyl': percentyl,
            'prog_zasobnosci_m3ha': float(prog_zasobnosci),
            'srednia_krajowa_m3ha': float(np.nanmean(wartosci_valid)),
            'max_zasobnosci_m3ha': float(np.nanmax(wartosci_valid)),
            'n_traktow': len(gdf_model),
            'wiarygodne': wiarygodne,
        }],
        geometry=[zasieg_geom],
        crs=CRS_OBLICZENIOWY,
    )

    sufiks_typ = f"_typ{typ}" if typ is not None else ""
    file_prefix = f"martwe_drewno_cykl{nr_cykl}{sufiks_typ}_perc{percentyl}"

    gdf_zasieg.to_crs(CRS_ZAPISU).to_file(
        f"KDE_martwe_drewno/{file_prefix}.geojson", driver="GeoJSON"
    )
    fig.savefig(f"KDE_martwe_drewno/{file_prefix}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Zakończono pomyślnie. Zapisano wyniki dla cyklu {nr_cykl}.")


if __name__ == "__main__":
    cykle = [1, 2, 3, 4]
    for cykl in cykle:
        martwe_drewno_mapa(nr_cykl=cykl)
