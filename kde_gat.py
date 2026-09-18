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
from Wisl_quert import query_udzial_gat, query_tlo_lasu, query_mlode_uprawy
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
#   f = KDE ważone wagą gatunku (patrz `miara` niżej)
#   g = KDE ważone wagą CAŁEJ badanej powierzchni leśnej (WSP_Z),
#       niezależnie od gatunku - query_tlo_lasu
# Wynik f/g to lokalny, wygładzony przestrzennie UDZIAŁ gatunku (0-1) -
# wielkość bezwzględna o sensie fizycznym. Ten sam test kontrolowany daje dla
# niezmienionego regionu 0,3672 w OBU scenariuszach.
#
# ==============================================================================
# DLACZEGO DOMYŚLNIE POWIERZCHNIA, A NIE MIĄŻSZOŚĆ
# ==============================================================================
# Dla trybu drzewostany (miara='powierzchnia') waga to WYŁĄCZNIE WSP_Z -
# BEZ zadrzewienia (ZADRZEW). Dwa powody:
#
# 1. Merytoryczny: ZADRZEW różnicuje podpowierzchnie o tym samym udziale
#    miąższościowym i tej samej powierzchni (WSP_Z) wg intensywności/gęstości
#    lasu - to osobne pytanie od "czy tu rośnie drzewostan tego gatunku".
#    Podpowierzchnia z 2 rzadkimi dębami i podpowierzchnia z 30 gęstymi
#    dębami mają tu tę samą wagę, bo obie SĄ drzewostanem dębowym (>=60%
#    miąższości) - interesuje nas GDZIE, nie JAK GĘSTO.
# 2. Techniczny: ZADRZEW jest w tej bazie ZAWSZE NULL dla podpowierzchni bez
#    drzew >=7cm (sprawdzone: 0/2088) - a to dokładnie te podpowierzchnie
#    (młode uprawy, zręby, halizny), które trzeba było dołączyć do modelu,
#    żeby przestały być całkowicie niewidoczne (patrz niżej). Waga oparta
#    na ZADRZEW by je automatycznie wykluczała.
#
# Jedynym elementem czyniącym wynik miąższościowym (miara='miazszosc') jest
# UDZIAL_MIAZSZOSC. Ponieważ miąższość silnie zależy od wieku (a udział
# gatunku w zasobach - od jego pozycji w piętrze), udział miąższościowy
# zaniża gatunki młodsze i wolniej przyrastające. Sprawdzone na cyklu 4:
# przejście na miarę powierzchniową podnosi udział brzozy o 42,6%, jodły
# o 39,7%, dębu o 20,0%. Dla pytania "gdzie rośnie ten gatunek" właściwa jest
# powierzchnia; miąższość odpowiada na inne pytanie - "gdzie są jego zasoby
# drzewne" (i to jest sens trybu drzewostany=False, gdzie liczy się też
# domieszka, nie tylko dominacja).
#
# ==============================================================================
# MIANOWNIK: CAŁA POWIERZCHNIA LEŚNA, NIE TYLKO DRZEWA >=7CM
# ==============================================================================
# 5,5% podpowierzchni R_POW_PR=1 ("Drzewostan") w cyklu 4 (2158/39548) nie ma
# ŻADNEGO drzewa >=7cm - to młode uprawy (mediana wieku 10 lat) i sporadyczne
# błędnie sklasyfikowane zręby (wiek do 155 lat). Wcześniejsza wersja tej
# metody (i cała reszta obliczeń WISL oparta na DRZEWA_OD_7) pomijała je
# CAŁKOWICIE - nie tylko w liczniku, ale i w mianowniku, bo obie strony
# ilorazu wymagały obecności drzew >=7cm. To systematycznie zaniżało udział
# gatunków silnie reprezentowanych w młodym pokoleniu odnowieniowym.
#
# Rozwiązanie ma dwie części (query_mlode_uprawy, query_tlo_lasu):
#  - Młode uprawy (R_POW_PR=1, brak drzew >=7cm, wiek <=20) WCHODZĄ do
#    licznika gatunku wskazanego przez GAT_PAN_PR (opis taksacyjny) - to
#    realny, aktualny gatunek odnowienia, bo ktoś już go tam posadził/on się
#    tam odnawia. Tylko dla miary='powierzchnia' - miąższościowo nie ma czego
#    mierzyć.
#  - Las bez aktualnego drzewostanu (Halizna, Zrąb, Płazowina, Do naturalnej
#    sukcesji, Objęte ochroną, Inne wylesienia - R_POW_PR 7-12) WCHODZI do
#    MIANOWNIKA (jako część badanej powierzchni leśnej), ale NIE do żadnego
#    licznika gatunkowego - GAT_PAN_PR na takiej podpowierzchni to zazwyczaj
#    gatunek USUNIĘTEGO drzewostanu (opis planistyczny), nie stan faktyczny,
#    więc przypisanie mu 100% udziału byłoby błędem. Poprawnie obniża to
#    udział KAŻDEGO gatunku, bo tam faktycznie nic teraz nie rośnie.
# Plantacje specjalnego przeznaczenia (R_POW_PR 2-6) i infrastruktura leśna
# (13+) są wykluczone z obu stron - nie reprezentują gospodarczego
# rozmieszczenia gatunków.
#
# ==============================================================================
# PODGATUNKI (DB.S, DB.B, DB.C, SO.*, ...) TRAKTOWANE JAK GATUNEK BAZOWY
# ==============================================================================
# Kody WISL rozróżniają podgatunki kropką. Dosłowne porównanie kodu (obecne
# przed tą poprawką) pomijało je całkowicie - dla dębu to 20,6% wszystkich
# drzew i 1990 podpowierzchni, które miały WYŁĄCZNIE podgatunek (żadnego
# drzewa z czystym kodem 'DB') i przez to znikały z wyników w 100%. Dla
# pozostałych 7 gatunków głównych wpływ jest marginalny (0-4,2%), ale
# konwersja jest zastosowana uniwersalnie (Wisl_quert._dopasowanie_gatunku).
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

# Progi STAŁE (udział gatunku), a nie percentyle rozkładu w danym cyklu -
# z tego samego powodu co PROGI_ZASOBNOSCI_M3HA w kde_martwe_drewno.py:
# percentyl to znowu wielkość względna, więc mapy różnych cykli przestałyby być
# porównywalne, czyli wróciłby dokładnie ten problem, który ta metoda ma
# rozwiązywać.
# Najniższy próg (5%) pełni rolę dawnego "zasięgu gatunku": obszar, na którym
# gatunek stanowi co najmniej 5% lokalnego lasu.
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


def plot_kde_for_species(gat, rok_start=2020, rok_end=2025, drzewostany=True, miara=None, progi=PROGI_UDZIALU):
    """
    Lokalny, wygładzony przestrzennie udział gatunku, z zaznaczeniem obszarów
    przekraczających stałe progi udziału.

    rok_start, rok_end - zakres lat wykonania pomiaru (ADRES_POW.DATA), a nie
        numer formalnego cyklu WISL. Cykle są rozłączne (Wisl_quert.CYKLE_LATA:
        1=2005-2009, 2=2010-2014, 3=2015-2019, 4=2020-2025), ale zakres można
        dobrać dowolnie - np. tylko część cyklu albo kilka cykli naraz.

    drzewostany=True  - licznik ograniczony do powierzchni, na których gatunek
        DOMINUJE (udział miąższości >= 60%): mapa zasięgu drzewostanów danego
        gatunku. Obejmuje też młode uprawy (patrz query_mlode_uprawy), gdzie
        gatunek panujący pochodzi z opisu taksacyjnego (GAT_PAN_PR), bo nie ma
        jeszcze mierzalnej miąższości.
    drzewostany=False - licznik obejmuje każde wystąpienie gatunku, także jako
        domieszki: mapa zasięgu samego gatunku (bez młodych upraw - te nie
        mają miąższości, więc nie da się dla nich policzyć udziału domieszki).

    miara - co dokładnie jest udziałem:
        'powierzchnia' - udział w BADANEJ POWIERZCHNI LEŚNEJ. Licznik i
            mianownik oparte WYŁĄCZNIE na WSP_Z (bez zadrzewienia - patrz
            uzasadnienie w komentarzu na górze pliku). Niezależne od wieku
            i gęstości drzewostanu.
        'miazszosc' - udział w MIĄŻSZOŚCI. Licznik to UDZIAL_MIAZSZOSC * WSP_Z,
            czyli faktyczny udział gatunku w zasobach ważony powierzchnią.
            Wielkość zależna od wieku i produkcyjności: młody dąb w podszycie
            pod starą sosną wnosi mało miąższości mimo zajmowanej powierzchni.

        None (domyślnie) dobiera miarę do trybu: 'powierzchnia' dla drzewostanów,
        'miazszosc' dla gatunku z domieszkami. Miara powierzchniowa NIE JEST
        dostępna w trybie drzewostany=False - WISL nie podaje powierzchniowego
        udziału gatunku wewnątrz drzewostanu mieszanego, a zaliczenie całej
        podpowierzchni domieszce zawyżałoby wynik wielokrotnie.

    Mianownik (tło) jest zawsze ten sam - cała badana powierzchnia leśna
    (query_tlo_lasu) - więc mapy są wyrażone w tej samej, porównywalnej skali.
    """
    if miara is None:
        miara = 'powierzchnia' if drzewostany else 'miazszosc'

    if miara not in ('powierzchnia', 'miazszosc'):
        raise ValueError(f"Nieznana miara: {miara!r} (dozwolone: 'powierzchnia', 'miazszosc')")

    if miara == 'powierzchnia' and not drzewostany:
        print(
            f"Pominięto mapę: miara powierzchniowa nie jest dostępna dla trybu "
            f"gatunku z domieszkami (gatunek {gat}, lata {rok_start}-{rok_end}) - "
            f"WISL nie podaje powierzchniowego udziału gatunku w drzewostanie mieszanym."
        )
        return

    adnotacja = "drzewostany" if drzewostany else "gatunek"
    okres = f"{rok_start}-{rok_end}"

    # ==============================================================================
    # 1. DANE: LICZNIK (GATUNEK) I MIANOWNIK (CAŁA POWIERZCHNIA LEŚNA)
    # ==============================================================================
    udzial_gat = query_udzial_gat(gat, rok_start, rok_end)
    if not udzial_gat:
        print(f"Brak danych z bazy dla gatunku {gat} w latach {okres}.")
        return

    df_gat = pd.DataFrame(udzial_gat, columns=[
        'NR_PODPOW', 'NR_CYKLU', 'UDZIAL_MIAZSZOSC', 'reprezentatywnosc_gat',
        'ZADRZEW', 'SUMA_MIAZSZOSC_gat', 'SUMA_MIAZSZOSC'])

    # Filtr dominacji: gatunek stanowi co najmniej 60% miąższości na
    # podpowierzchni (sposób wyłonienia gatunku panującego). Bez warunku na
    # ZADRZEW - patrz uzasadnienie na górze pliku (metoda wag go pomija
    # celowo, więc niespójnie byłoby zostawiać go tu jako próg kwalifikacji).
    if drzewostany:
        df_gat = df_gat.query("UDZIAL_MIAZSZOSC >= 0.6")

    tlo = query_tlo_lasu(rok_start, rok_end)
    if not tlo:
        print(f"Brak danych tła dla lat {okres}.")
        return
    df_tlo = pd.DataFrame(tlo, columns=['NR_PODPOW', 'waga_tlo'])

    # Wagę licznika bierzemy z TŁA (waga_tlo = WSP_Z), a nie z
    # reprezentatywnosc_gat liczonej w SQL (ta wciąż zawiera ZADRZEW - służy
    # tylko do odsiania w SQL zerowych/ujemnych wag, nie do obliczeń tutaj).
    # Tylko wtedy licznik i mianownik stoją na dokładnie tej samej wadze.
    # Podpowierzchnie z drzewami danego gatunku są ścisłym podzbiorem tła
    # (R_POW_PR=1 jest podzbiorem KODY_R_POW_LAS), więc złączenie niczego nie gubi.
    df_gat = df_gat.merge(df_tlo, on='NR_PODPOW', how='inner')

    if miara == 'powierzchnia':
        # Cała powierzchnia drzewostanu liczy się na rzecz gatunku, który go
        # tworzy.
        df_gat['waga_gat'] = df_gat['waga_tlo']

        # Młode uprawy (bez drzew >=7cm, więc nieobecne w query_udzial_gat) -
        # gatunek z opisu taksacyjnego (GAT_PAN_PR), z tym samym dopasowaniem
        # podgatunków jak w SQL. Rozłączne z df_gat z definicji (query_mlode_uprawy
        # wymaga braku drzew >=7cm, df_gat wymaga ich obecności), więc concat
        # bez ryzyka zdublowania podpowierzchni.
        mlode = query_mlode_uprawy(rok_start, rok_end)
        if mlode:
            df_mlode = pd.DataFrame(mlode, columns=['NR_PODPOW', 'GAT_PAN_PR', 'waga_tlo'])
            maska_gat = (df_mlode['GAT_PAN_PR'] == gat) | df_mlode['GAT_PAN_PR'].str.startswith(gat + '.')
            df_mlode_gat = df_mlode.loc[maska_gat, ['NR_PODPOW', 'waga_tlo']].copy()
            df_mlode_gat['waga_gat'] = df_mlode_gat['waga_tlo']
            df_gat = pd.concat(
                [df_gat[['NR_PODPOW', 'waga_tlo', 'waga_gat']], df_mlode_gat],
                ignore_index=True,
            )
    else:
        # Powierzchnia ważona faktycznym udziałem gatunku w miąższości. Młode
        # uprawy pomijamy - nie mają miąższości do zmierzenia.
        df_gat['waga_gat'] = df_gat['UDZIAL_MIAZSZOSC'] * df_gat['waga_tlo']

    if df_gat.empty:
        print(f"Brak powierzchni po odfiltrowaniu ({adnotacja}) dla gatunku {gat} w latach {okres}.")
        return

    # ==============================================================================
    # 2. AGREGACJA DO TRAKTU
    # ==============================================================================
    for df in (df_gat, df_tlo):
        df['NR_TRAKTU'] = pd.to_numeric(df['NR_PODPOW']).astype('int64') // 1000

    f_trakty = df_gat.groupby('NR_TRAKTU', as_index=False)['waga_gat'].sum()
    g_trakty = df_tlo.groupby('NR_TRAKTU', as_index=False)['waga_tlo'].sum()

    # LEFT JOIN od tła: trakty bez gatunku zostają w modelu z wagą licznika 0.
    # To nie jest kosmetyka - bez nich iloraz liczyłby lokalną średnią tylko
    # po powierzchniach, na których gatunek już jest, więc wszędzie wychodziłby
    # zawyżony udział (a obszary bez gatunku w ogóle nie obniżałyby wyniku).
    df_model = g_trakty.merge(f_trakty, on='NR_TRAKTU', how='left')
    df_model['waga_gat'] = df_model['waga_gat'].fillna(0.0)
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

    maska_gat = gdf_model['waga_gat'] > 0
    n_traktow_gat = int(maska_gat.sum())

    if len(gdf_model) < 5:
        print(f"Zbyt mało danych przestrzennych do wyznaczenia KDE (lata {okres}, znaleziono: {len(gdf_model)}).")
        return

    if n_traktow_gat < MIN_TRAKTOW_WIARYGODNY:
        print(
            f"Pominięto mapę: gatunek {gat} ({adnotacja}) występuje tylko na "
            f"{n_traktow_gat} traktach (wymagane min. {MIN_TRAKTOW_WIARYGODNY}, lata {okres})."
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
    waga_f = gdf_model['waga_gat'].to_numpy()

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
        print(f"Brak poprawnych wartości udziału dla gatunku {gat} w latach {okres}.")
        return

    max_udzialu = float(np.nanmax(wartosci_valid))

    # Progi rosnąco, ograniczone do faktycznie osiągniętych w tym cyklu
    # (próg >= max nie wyznaczyłby żadnego obszaru na contourf/contour).
    progi_udzialu = sorted(p for p in set(progi) if p < max_udzialu)

    if not progi_udzialu:
        print(
            f"Gatunek {gat} ({adnotacja}), lata {okres}: udział nie przekracza żadnego z progów "
            f"{sorted(set(progi))} (max={max_udzialu:.3f}) - pomijam mapę."
        )
        return

    print(
        f"Gatunek: {gat} ({adnotacja}, {miara}) | Lata: {okres} | n_traktow={len(gdf_model)} "
        f"(z gatunkiem: {n_traktow_gat}) | udział krajowy={wspolczynnik_korekty_skali:.3f} | "
        f"max lokalny={max_udzialu:.3f}"
    )

    # Etykiety muszą opisywać PRZEDZIAŁY, a nie progi: contourf koloruje
    # rozłączne pasma (levels = progi + [max]), więc najjaśniejszy kolor to
    # np. 5-10%, a nie "wszystko powyżej 5%". Wielokąty zapisywane do GeoJSON są
    # natomiast kumulatywne (zagnieżdżone) - tam prog_udzialu=0,05 to faktycznie
    # cały obszar powyżej 5%. Dwie różne konwencje w dwóch różnych wynikach.
    jednostka = 'powierzchni' if miara == 'powierzchnia' else 'miąższości'

    def etykieta_pasma(i):
        prog = progi_udzialu[i]
        if i + 1 < len(progi_udzialu):
            return f'{prog:.0%}–{progi_udzialu[i + 1]:.0%} {jednostka}'
        return f'> {prog:.0%} {jednostka}'

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
    opis_miary = ("zadrzewionej powierzchni lasu" if miara == 'powierzchnia'
                  else "miąższości drzewostanów")
    ax.set_title(
        f"Udział gatunku {gat} w {opis_miary} - zakresy "
        f"{', '.join(etykieta_pasma(i).replace(f' {jednostka}', '') for i in range(len(progi_udzialu)))} "
        f"(Lata: {okres} | {adnotacja})",
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
                'rok_start': rok_start,
                'rok_end': rok_end,
                'typ_zasiegu': adnotacja,
                'miara': miara,
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
        f"KDE_gatunki/zasieg_{gat}_{okres}_{adnotacja}_{miara}_epsg4326.geojson", driver="GeoJSON"
    )
    fig.savefig(f"KDE_gatunki/mapa_{gat}_{okres}_{adnotacja}_{miara}.png",
                dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Zakończono pomyślnie. Zapisano wyniki dla gatunku {gat} ({adnotacja}, {miara}), lata {okres}.")


if __name__ == "__main__":
    from Wisl_quert import CYKLE_LATA
    gatunki = ['SO', 'ŚW', 'JD', 'MD', 'DB', 'BK', 'BRZ', 'OL']
    for gat in gatunki:
        for rok_start, rok_end in CYKLE_LATA.values():
            plot_kde_for_species(gat=gat, rok_start=rok_start, rok_end=rok_end, drzewostany=True)
