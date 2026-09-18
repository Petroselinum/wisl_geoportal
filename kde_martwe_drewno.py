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
from shapely.geometry import Polygon, MultiPolygon
from Wisl_quert import martwe_drewno
from matplotlib_map_utils.core.north_arrow import north_arrow
from matplotlib_map_utils.core.scale_bar import scale_bar
from kde_common import (
    wymus_wspolne_pasmo,
    TekstWzdlugKonturu,
    wytnij_fragment_konturu,
    dlugosc_tekstu_w_danych,
)
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
# Progi zaznaczające "obszary najbardziej zasobne" są liczone na WYNIKU
# (już unormowanej lokalnej średniej), nie na surowej gęstości f - to
# jest różnica względem błędu, który popełniliśmy najpierw przy
# uszkodzeniach (próg na surowej gęstości dawał pokrycie ~90% kraju).
# Tutaj są to stałe wartości w m3/ha (PROGI_ZASOBNOSCI_M3HA), a nie
# percentyle rozkładu w danym cyklu - dzięki temu są porównywalne z tym,
# jak BULiGL raportuje zasobność w tabelach (m3/ha), i między cyklami.
CRS_OBLICZENIOWY_ = CRS_OBLICZENIOWY  # (alias niepotrzebny, zostawiony dla czytelności importu wyżej)

PROG_MIN_TLA = 0.01        # poniżej tego ułamka maksimum gęstości tła nie ufamy ilorazowi (brzegi)
MIN_TRAKTOW_WIARYGODNY = 100  # globalny próg wiarygodności modelu (ten sam co przy KDE gatunków)

# Progi STAŁE (m3/ha), a nie percentyle rozkładu w danym cyklu - percentyle
# dają różne wartości progowe (i różne kolory) dla tej samej "kategorii" w
# różnych cyklach (np. top 20% to 3.5 m3/ha w cyklu 1, ale 13.8 m3/ha w
# cyklu 4 - patrz dane historyczne), co czyni mapy między cyklami
# nieporównywalnymi. Stałe progi >5/>10/>15/>20 m3/ha rozwiązują to.
PROGI_ZASOBNOSCI_M3HA = [5, 10, 15, 20]

# Kolor przypisany NA STAŁE do konkretnej wartości progu (nie do jej
# pozycji w rankingu, jak dawniej przy percentylach) - dzięki temu pasmo
# ">10 m3/ha" ma zawsze ten sam odcień niezależnie od cyklu i od tego, ile
# innych progów akurat rysujemy, co pozwala porównywać mapy wizualnie.
KOLORY_PROGOW_M3HA = {
    5: plt.cm.YlOrBr(0.30),
    10: plt.cm.YlOrBr(0.50),
    15: plt.cm.YlOrBr(0.70),
    20: plt.cm.YlOrBr(0.92),
}


def martwe_drewno_mapa(rok_start: int = 2020, rok_end: int = 2025, typ: int | None = None, progi: list[float] = PROGI_ZASOBNOSCI_M3HA):
    """
    Lokalna, wygładzona przestrzennie średnia zasobność martwego drewna
    (m3/ha), z zaznaczeniem obszarów przekraczających kilka stałych progów
    zasobności (domyślnie >5, >10, >15, >20 m3/ha).

    rok_start, rok_end - zakres lat wykonania pomiaru (ADRES_POW.DATA), nie
        numer formalnego cyklu WISL (patrz Wisl_quert.CYKLE_LATA).

    Wisl_quert.martwe_drewno(rok_start, rok_end) zwraca dane per trakt i per
    TYP martwego drewna (1-3 leżące, 4 posusz, 5 złom — patrz dokumentacja
    WISL), już podzielone przez SUMA_WSP_Z traktu (SR_MIAZSZOSC to
    gotowa średnia ważona na poziomie podpowierzchni, zagregowana do
    traktu) — ale SUMA_WSP_Z jest też zwracane osobno, bo potrzebujemy
    go jako wagi reprezentatywności do przestrzennego wygładzania KDE,
    niezależnie od tego, że posłużyło już do policzenia SR_MIAZSZOSC.

    typ: opcjonalny filtr konkretnego typu martwego drewna (int).
        None = suma wszystkich typów na trakt (ten sam mianownik
        SUMA_WSP_Z obowiązuje dla każdego typu w danym trakcie, więc
        sumowanie SR_MIAZSZOSC po typach jest poprawne matematycznie).

    progi: lista stałych progów zasobności (m3/ha) do zaznaczenia jako
        osobne zakresy na mapie. Progi poza zakresem danych cyklu (>= max)
        są automatycznie pomijane. Kolor każdego progu jest stały
        (KOLORY_PROGOW_M3HA), więc mapy różnych cykli/gatunków są
        porównywalne wizualnie.
    """
    okres = f"{rok_start}-{rok_end}"
    res = martwe_drewno(rok_start=rok_start, rok_end=rok_end)
    if not res:
        print(f"Brak danych z bazy dla lat {okres}.")
        return

    df = pd.DataFrame(res, columns=['NR_TRAKTU', 'TYP', 'SR_MIAZSZOSC', 'SUMA_WSP_Z'])

    if df.empty:
        print(f"Brak danych dla lat {okres}.")
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
        print(f"Zbyt mało danych przestrzennych do wyznaczenia KDE (lata {okres}, znaleziono: {len(gdf_model)}).")
        return

    if len(gdf_model) < MIN_TRAKTOW_WIARYGODNY:
        print(
            f"Pominięto mapę: tylko {len(gdf_model)} traktów (wymagane min. "
            f"{MIN_TRAKTOW_WIARYGODNY}, lata {okres})."
        )
        return

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
        print(f"Brak poprawnych wartości zasobności dla lat {okres}.")
        return

    max_zasobnosci = float(np.nanmax(wartosci_valid))

    # Progi rosnąco, ograniczone do tych faktycznie osiągniętych w tym okresie
    # (próg >= max nie wyznaczyłby żadnego obszaru na contourf/contour).
    progi_zasobnosci = sorted(p for p in set(progi) if p < max_zasobnosci)

    if not progi_zasobnosci:
        print(
            f"Lata {okres}: zasobność nie przekracza żadnego z progów {sorted(set(progi))} "
            f"m3/ha (max={max_zasobnosci:.2f} m3/ha) - pomijam mapę."
        )
        return

    print(
        f"Martwe drewno | Lata: {okres} | n_traktow={len(gdf_model)} | "
        f"srednia krajowa={np.nanmean(wartosci_valid):.2f} m3/ha | "
        + " | ".join(f"> {prog:.0f} m3/ha" for prog in progi_zasobnosci)
        + f" | max={max_zasobnosci:.2f} m3/ha"
    )

    # ==============================================================================
    # WIZUALIZACJA I EKSTRAKCJA GEOMETRII
    # ==============================================================================
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')

    # Kolor każdego pasma jest STAŁY dla danej wartości progu (KOLORY_PROGOW_M3HA),
    # nie zależy od tego, ile progów akurat rysujemy - pozwala porównywać
    # mapy różnych cykli/gatunków wizualnie (patrz komentarz przy stałej).
    kolory_pasm = [KOLORY_PROGOW_M3HA[prog] for prog in progi_zasobnosci]

    ax.contourf(
        X, Y, srednia_zasobnosc,
        levels=progi_zasobnosci + [max_zasobnosci],
        colors=kolory_pasm,
        alpha=0.7,
    )

    zasobnosc_contour = np.nan_to_num(srednia_zasobnosc, nan=0.0)
    cs = ax.contour(
        X, Y, zasobnosc_contour,
        levels=progi_zasobnosci,
        colors=['#6b3d00'],
        linewidths=1.2,
    )

    # Geometria każdego zakresu osobno (do zapisu i do etykietowania) -
    # cs.allsegs[i] to segmenty konturu dla i-tego progu z `progi_zasobnosci`,
    # w tej samej kolejności.
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

    # Etykiety KSZTAŁTEM I POŁOŻENIEM DOPASOWANE DO PRZEBIEGU KONTURU: zamiast
    # jednego sztywnego napisu obróconego pod jednym kątem (dawne
    # ax.clabel(manual=...)), każdy znak etykiety jest osobno pozycjonowany i
    # obracany wzdłuż wyciętego fragmentu linii konturu (TekstWzdlugKonturu w
    # kde_common.py) - dzięki temu napis "podąża" za krzywizną granicy
    # zasięgu tak jak opis warstwicy na mapie topograficznej, zamiast
    # przecinać ją pod przypadkowym kątem przy mocno wygiętych konturach.
    #
    # Punkt kotwiczący (środek etykiety) musi leżeć NA linii konturu
    # (wierzchołek jego zewnętrznej granicy) - tylko wtedy wiadomo, z
    # którego fragmentu pierścienia wyciąć ścieżkę pod tekst.
    # representative_point() dałoby punkt ŚCIŚLE wewnątrz wielokąta, ale bez
    # żadnego fragmentu linii, na który dałoby się nanieść napis.
    #
    # Kandydatów filtrujemy po odległości od granicy Polski
    # (BORDER_TOL_ETYKIETY) - kategorycznie odrzucamy wierzchołki leżące
    # blisko przebiegu granicy kraju, niezależnie od tego, czy to artefakt
    # (kontur "przyklejony" do granicy przez np.nan_to_num na brzegu
    # obszaru ważnego) czy realny fragment zasięgu - w obu przypadkach
    # etykieta tam wyglądałaby jak opis granicy Polski, a nie warstwicy KDE.
    # Wybieramy wierzchołki najdalsze od granicy - dla dłuższych fragmentów
    # konturu więcej niż jeden, żeby etykieta pasma powtarzała się częściej
    # (jak opis warstwicy na mapie topograficznej), ale zachowując między
    # kolejnymi powtórzeniami odstęp MIN_ODSTEP_ETYKIET, żeby się nie zlewały.
    #
    # Szukamy tylko po granicy ZEWNĘTRZNEJ (czesc.exterior), nie po
    # ewentualnych `interiors` - te ostatnie to granica z zagnieżdżonym
    # wyższym progiem (już opisywana osobną etykietą tego wyższego progu).
    #
    # Punkt kotwiczący dla progu N trafia w PIERŚCIEŃ tego pasma (obszar
    # >= prog_N ale poza zagnieżdżonym obszarem >= prog_N+1), nie w cały
    # wielokąt >= prog_N - inaczej punkty zagnieżdżonych progów zbiegałyby
    # się w tym samym, najbardziej wewnętrznym miejscu (tam, gdzie leży też
    # najwyższy próg) i etykiety nakładałyby się na siebie.
    MIN_POWIERZCHNIA_ETYKIETY = 3e8  # m^2 (300 km^2) - nie etykietujemy znikomych strzępków zakresu
    BORDER_TOL_ETYKIETY = 15_000  # m - punkt kotwiczący etykiety musi leżeć dalej od granicy Polski niż to
    MIN_ODSTEP_ETYKIET = 150_000  # m - minimalny odstęp między powtórzeniami etykiety tego samego pasma na jednym fragmencie konturu
    kandydaci_etykiet = []
    for i, prog in enumerate(progi_zasobnosci):
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
                # Cała zewnętrzna granica tej części biegnie blisko granicy
                # Polski (zasięg dochodzi do granicy na całej swojej
                # długości) - nie da się tu bezpiecznie umieścić etykiety, więc
                # kategorycznie pomijamy tę część zamiast ryzykować pomylenie
                # jej z linią granicy kraju.
                continue
            # Kandydaci w kolejności od najdalszego od granicy - dobieramy
            # zachłannie, pomijając każdego, kto wypadłby bliżej niż
            # MIN_ODSTEP_ETYKIET od wierzchołka już wybranego.
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
        # `renderer` - potrzebny do zmierzenia FAKTYCZNEJ szerokości
        # znaków etykiety (dlugosc_tekstu_w_danych), zanim wytniemy pod nie
        # fragment linii konturu.
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        for prog, wierzcholki, idx_najdalszy in kandydaci_etykiet:
            tekst = f"> {prog:.0f} m³/ha"
            dlugosc = dlugosc_tekstu_w_danych(ax, tekst, fontsize=6, renderer=renderer)
            fragment = wytnij_fragment_konturu(wierzcholki, idx_najdalszy, dlugosc)
            if len(fragment) < 2:
                continue
            etykieta = TekstWzdlugKonturu(
                fragment[:, 0], fragment[:, 1], tekst, ax,
                fontsize=6, color='#3d2400',
            )
            etykieta.set_path_effects([patheffects.withStroke(linewidth=2.5, foreground='white')])

    gdf_model.plot(ax=ax, color='gray', markersize=3, alpha=0.3)
    gdf_model[gdf_model['SR_MIAZSZOSC'] > 0].plot(ax=ax, color='orange', markersize=6, alpha=0.35)
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
        (f'{prog:.0f}–{progi_zasobnosci[i + 1]:.0f}'
         if i + 1 < len(progi_zasobnosci) else f'>{prog:.0f}')
        for i, prog in enumerate(progi_zasobnosci)
    )
    ax.set_title(
        f"Zasobność martwego drewna — zakresy {zakresy_opis} m³/ha (Lata: {okres})",
        fontsize=11,
    )
    ax.set_xlabel("X [m] (EPSG:2180)")
    ax.set_ylabel("Y [m] (EPSG:2180)")
    ax.ticklabel_format(style='plain', useOffset=False)

    try:
        cx.add_basemap(ax, crs=poland.crs, source=cx.providers.Esri.WorldGrayCanvas, alpha=1, zoom=8)
    except Exception:
        pass

    # Od najwyższego progu do najniższego. Etykiety opisują PRZEDZIAŁY, a nie
    # progi: contourf koloruje rozłączne pasma (levels = progi + [max]), więc
    # najjaśniejszy kolor to np. 5-10 m³/ha, a nie "wszystko powyżej 5".
    # Etykiety przy samych liniach konturu zostają progowe ("> 5 m³/ha") - tam
    # jest to poprawne, bo linia wyznacza właśnie przekroczenie progu.
    # Wielokąty w GeoJSON są z kolei kumulatywne (zagnieżdżone), tak jak
    # w kde_gat.py - patrz atrybut prog_zasobnosci_m3ha.
    legend_elements = [
        mpatches.Patch(
            facecolor=kolory_pasm[i], edgecolor='#6b3d00', linewidth=1.2, alpha=0.7,
            label=(f'{progi_zasobnosci[i]:.0f}–{progi_zasobnosci[i + 1]:.0f} m³/ha'
                   if i + 1 < len(progi_zasobnosci)
                   else f'> {progi_zasobnosci[i]:.0f} m³/ha'),
        )
        for i in range(len(progi_zasobnosci) - 1, -1, -1)
    ] + [
        mlines.Line2D([], [], color='orange', marker='o', linestyle='None', markersize=6, alpha=0.35,
                      label='Trakt z martwym drewnem'),
        mlines.Line2D([], [], color='gray', marker='o', linestyle='None', markersize=4, alpha=0.4,
                      label='Trakt badany (tło)'),
        mlines.Line2D([], [], color='black', linewidth=1, label='Granica Polski'),
    ]
    # Legenda WYNIESIONA poza obszar mapy (po prawej stronie osi), żeby nie
    # zasłaniać terytorium Polski - wcześniejsze 'lower left' wewnątrz osi
    # nakładało się na południowo-zachodni skrawek kraju.
    ax.legend(
        handles=legend_elements, loc='center left', bbox_to_anchor=(1.01, 0.5),
        frameon=True, facecolor='white', fontsize=9, title="Legenda", title_fontsize=10,
    )

    # ==============================================================================
    # ZAPIS WYNIKÓW
    # ==============================================================================
    if not os.path.exists("KDE_martwe_drewno"):
        os.makedirs("KDE_martwe_drewno")

    gdf_zasieg = gpd.GeoDataFrame(
        [
            {
                'rok_start': rok_start,
                'rok_end': rok_end,
                'typ_martwego_drewna': typ if typ is not None else 'wszystkie',
                'prog_zasobnosci_m3ha': prog,
                'srednia_krajowa_m3ha': float(np.nanmean(wartosci_valid)),
                'max_zasobnosci_m3ha': max_zasobnosci,
                'n_traktow': len(gdf_model),
                'geometry': geom,
            }
            for prog, geom in zip(progi_zasobnosci, zasiegi_geom)
        ],
        geometry='geometry',
        crs=CRS_OBLICZENIOWY,
    )

    sufiks_typ = f"_typ{typ}" if typ is not None else ""
    sufiks_prog = "_".join(str(int(p)) for p in progi_zasobnosci)
    file_prefix = f"martwe_drewno_{okres}{sufiks_typ}_prog{sufiks_prog}"

    gdf_zasieg.to_crs(CRS_ZAPISU).to_file(
        f"KDE_martwe_drewno/{file_prefix}.geojson", driver="GeoJSON"
    )
    fig.savefig(f"KDE_martwe_drewno/{file_prefix}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Zakończono pomyślnie. Zapisano wyniki dla lat {okres}.")


if __name__ == "__main__":
    from Wisl_quert import CYKLE_LATA
    for rok_start, rok_end in CYKLE_LATA:
        martwe_drewno_mapa(rok_start=rok_start, rok_end=rok_end)
