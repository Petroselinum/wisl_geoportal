"""
Wspólna mapa lokalnej, wygładzonej przestrzennie ŚREDNIEJ wielkości na hektar
(estymator Nadaraya-Watson) dla kde_przyrost.py i kde_uzytkowanie.py.

Ta sama metoda i ten sam wygląd co w kde_zasobnosc.py / kde_martwe_drewno.py:
    f = KDE ważone SR * SUMA_WSP_Z (ilość przypadająca na trakt)
    g = KDE ważone SUMA_WSP_Z (reprezentowana powierzchnia traktu)
    wynik = f/g * sum(waga_f)/sum(waga_g)    -> średnia w jednostkach SR
ze wspólnym fizycznym pasmem obu KDE (kde_common.wymus_wspolne_pasmo),
odcięciem brzegów o niskiej gęstości tła i STAŁYMI progami (porównywalnymi
między okresami). Zapis: GeoJSON z wielokątami KUMULATYWNYMI (próg wyższy
leży w niższym) w EPSG:4326 + mapa PNG 300 dpi.
"""
import os
import textwrap
import matplotlib.pyplot as plt
from matplotlib import patches as mpatches
from matplotlib import lines as mlines
from matplotlib import patheffects
import numpy as np
import geopandas as gpd
import shapely
from scipy.stats import gaussian_kde
from shapely.geometry import Polygon
from matplotlib_map_utils.core.north_arrow import north_arrow
from matplotlib_map_utils.core.scale_bar import scale_bar
from kde_common import (
    wymus_wspolne_pasmo,
    TekstWzdlugKonturu,
    wytnij_fragment_konturu,
    dlugosc_tekstu_w_danych,
)
import contextily as cx

CRS_OBLICZENIOWY = "EPSG:2180"
CRS_ZAPISU = "EPSG:4326"

PROG_MIN_TLA = 0.01           # poniżej tego ułamka maksimum gęstości tła nie ufamy ilorazowi (brzegi)
MIN_TRAKTOW_WIARYGODNY = 100  # globalny próg wiarygodności modelu (ten sam co w pozostałych skryptach KDE)


def _liczba(x):
    """12.5 -> '12,5', 10.0 -> '10' (progi i maksima w opisach map)."""
    return f"{x:.1f}".rstrip('0').rstrip('.').replace('.', ',')


def model_traktow(df):
    """
    df: NR_TRAKTU, SR (wartość na ha), SUMA_WSP_Z -> GeoDataFrame traktów
    w EPSG:2180 (geometria z data/trakty_wsp.geojson), tylko trakty
    z dodatnią wagą.
    """
    df = df.copy()
    df['NR_TRAKTU'] = df['NR_TRAKTU'].astype(int).astype(str)
    trakty = gpd.read_file('data/trakty_wsp.geojson')
    trakty['nr_traktu'] = trakty['nr_punktu'].astype(int).astype(str).str[:-1]
    gdf = trakty[['nr_traktu', 'geometry']].merge(df, left_on='nr_traktu', right_on='NR_TRAKTU', how='inner')
    gdf = gpd.GeoDataFrame(gdf, geometry='geometry', crs=trakty.crs).to_crs(CRS_OBLICZENIOWY)
    return gdf[gdf.geometry.notnull() & (gdf['SUMA_WSP_Z'] > 0)].copy()


def powierzchnia(gdf_model, poland_geom, rozdzielczosc=500):
    """Siatka X, Y i wygładzona lokalna średnia (NaN poza Polską i na brzegach
    o zbyt niskiej gęstości tła) + średnia krajowa ważona powierzchnią."""
    coords = np.vstack([gdf_model.geometry.x, gdf_model.geometry.y])
    waga_tlo = gdf_model['SUMA_WSP_Z'].to_numpy(dtype=float)
    waga_f = (gdf_model['SR'] * gdf_model['SUMA_WSP_Z']).to_numpy(dtype=float)

    xmin, ymin, xmax, ymax = poland_geom.bounds
    X, Y = np.meshgrid(np.linspace(xmin, xmax, rozdzielczosc), np.linspace(ymin, ymax, rozdzielczosc))
    positions = np.vstack([X.ravel(), Y.ravel()])

    kernel_tlo = gaussian_kde(coords, weights=waga_tlo, bw_method='scott')
    kernel_f = gaussian_kde(coords, weights=waga_f)
    wymus_wspolne_pasmo(kernel_f, kernel_tlo)
    # scipy normalizuje f i g NIEZALEŻNIE do całki = 1 - bez tej korekty
    # iloraz byłby przeskalowany przypadkowym współczynnikiem
    srednia_krajowa = waga_f.sum() / waga_tlo.sum()

    f_est = kernel_f(positions).reshape(X.shape)
    g_est = kernel_tlo(positions).reshape(X.shape)
    mask_polska = shapely.contains_xy(poland_geom, X, Y)
    f_est[~mask_polska] = np.nan
    g_est[~mask_polska] = np.nan
    with np.errstate(divide='ignore', invalid='ignore'):
        wartosc = (f_est / g_est) * srednia_krajowa
    wartosc[g_est < PROG_MIN_TLA * np.nanmax(g_est)] = np.nan
    return X, Y, wartosc, float(srednia_krajowa)


def mapa_sredniej(df, rok_start, rok_end, progi, kolory_progow, *, jednostka, tytul, katalog,
                  prefiks, opis, atrybuty=None, kolor_linii='#1b5e20', kolor_etykiet='black',
                  etykieta_dodatnich=None, kolor_dodatnich='#7b1fa2', przypis=None):
    """
    df: NR_TRAKTU, SR, SUMA_WSP_Z (wynik zapytania z Wisl_quert).
    progi: stałe progi (rosnąco albo nie) - progi >= maksimum okresu są
        pomijane. kolory_progow: {prog: kolor} - kolor przypisany wartości
        progu, nie pozycji (pasmo ma ten sam odcień w każdym okresie).
    jednostka: np. 'm³/ha/rok' (opisy PNG i atrybut 'jednostka').
    tytul: początek tytułu mapy (dalej zakresy i lata).
    katalog, prefiks: zapis {katalog}/{prefiks}_{okres}_prog{progi}.geojson/.png
    opis: krótki opis wariantu do komunikatów konsoli.
    atrybuty: dodatkowe kolumny GeoJSON (np. rodzaj użytkowania).
    etykieta_dodatnich: jeśli podana, trakty z SR > 0 są zaznaczone osobno
        (np. 'Trakt z użytkowaniem rębnym') - jak trakty z martwym drewnem.
    przypis: uwaga metodyczna pod mapą (np. okres, którego dotyczą wartości).
    Zwraca ścieżkę GeoJSON albo None (mapa pominięta).
    """
    okres = f"{rok_start}-{rok_end}"
    if df is None or len(df) == 0:
        print(f"Brak danych z bazy dla lat {okres} ({opis}).")
        return None

    gdf_model = model_traktow(df)
    if len(gdf_model) < MIN_TRAKTOW_WIARYGODNY:
        print(f"Pominięto mapę: tylko {len(gdf_model)} traktów (wymagane min. "
              f"{MIN_TRAKTOW_WIARYGODNY}, lata {okres}, {opis}).")
        return None
    if not (gdf_model['SR'] > 0).any():
        print(f"Lata {okres} ({opis}): wszystkie wartości równe 0 - pomijam mapę.")
        return None

    poland = gpd.read_file("data/poland_land.geojson").to_crs(CRS_OBLICZENIOWY)
    poland_geom = poland.geometry.union_all()
    granica_polski = poland_geom.boundary
    X, Y, wartosc, srednia_krajowa = powierzchnia(gdf_model, poland_geom)

    wartosci_valid = wartosc[~np.isnan(wartosc)]
    if wartosci_valid.size == 0:
        print(f"Brak poprawnych wartości dla lat {okres} ({opis}).")
        return None
    maks = float(np.nanmax(wartosci_valid))

    progi_okresu = sorted(p for p in set(progi) if p < maks)
    if not progi_okresu:
        print(f"Lata {okres} ({opis}): wartości nie przekraczają żadnego z progów "
              f"{sorted(set(progi))} {jednostka} (max={maks:.2f}) - pomijam mapę.")
        return None

    print(f"{opis} | Lata: {okres} | n_traktow={len(gdf_model)} | "
          f"srednia krajowa={srednia_krajowa:.2f} {jednostka} | "
          + " | ".join(f"> {_liczba(p)}" for p in progi_okresu)
          + f" | max lokalny={maks:.2f} {jednostka}")

    # ==========================================================================
    # WIZUALIZACJA I EKSTRAKCJA GEOMETRII (jak kde_zasobnosc.py)
    # ==========================================================================
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')
    kolory_pasm = [kolory_progow[p] for p in progi_okresu]
    ax.contourf(X, Y, wartosc, levels=progi_okresu + [maks], colors=kolory_pasm, alpha=0.7)
    cs = ax.contour(X, Y, np.nan_to_num(wartosc, nan=0.0), levels=progi_okresu,
                    colors=[kolor_linii], linewidths=1.2)

    # Wielokąty KUMULATYWNE (zagnieżdżone) - cs.allsegs[i] to kontur i-tego progu
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

    # Etykiety wzdłuż konturów - punkt kotwiczący w PIERŚCIENIU pasma (poza
    # zagnieżdżonym wyższym progiem), z dala od granicy Polski, powtarzane
    # co MIN_ODSTEP_ETYKIET (szczegóły w kde_martwe_drewno.py).
    MIN_POWIERZCHNIA_ETYKIETY = 3e8  # m^2 (300 km^2)
    BORDER_TOL_ETYKIETY = 15_000     # m
    MIN_ODSTEP_ETYKIET = 150_000     # m
    kandydaci_etykiet = []
    for i, prog in enumerate(progi_okresu):
        geom = zasiegi_geom[i]
        if i + 1 < len(zasiegi_geom):
            geom = geom.difference(zasiegi_geom[i + 1])
        if geom.is_empty:
            continue
        for czesc in [g for g in getattr(geom, 'geoms', [geom]) if isinstance(g, Polygon)]:
            if czesc.is_empty or czesc.area < MIN_POWIERZCHNIA_ETYKIETY:
                continue
            wierzcholki = np.array(czesc.exterior.coords)
            odleglosc = shapely.distance(shapely.points(wierzcholki), granica_polski)
            maska_daleko = odleglosc > BORDER_TOL_ETYKIETY
            if not maska_daleko.any():
                continue
            wybrane_idx = []
            for idx in np.argsort(-np.where(maska_daleko, odleglosc, -np.inf)):
                if not maska_daleko[idx]:
                    break
                if all(np.linalg.norm(wierzcholki[idx] - wierzcholki[w]) >= MIN_ODSTEP_ETYKIET
                       for w in wybrane_idx):
                    wybrane_idx.append(int(idx))
            kandydaci_etykiet += [(prog, wierzcholki, idx) for idx in wybrane_idx]

    if kandydaci_etykiet:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        for prog, wierzcholki, idx in kandydaci_etykiet:
            tekst = f"> {_liczba(prog)} {jednostka}"
            dlugosc = dlugosc_tekstu_w_danych(ax, tekst, fontsize=6, renderer=renderer)
            fragment = wytnij_fragment_konturu(wierzcholki, idx, dlugosc)
            if len(fragment) < 2:
                continue
            etykieta = TekstWzdlugKonturu(fragment[:, 0], fragment[:, 1], tekst, ax,
                                          fontsize=6, color=kolor_etykiet)
            etykieta.set_path_effects([patheffects.withStroke(linewidth=2.5, foreground='white')])

    gdf_model.plot(ax=ax, color='gray', markersize=3, alpha=0.3)
    if etykieta_dodatnich:
        gdf_model[gdf_model['SR'] > 0].plot(ax=ax, color=kolor_dodatnich, markersize=6, alpha=0.35)
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

    zakresy_opis = ', '.join(
        (f'{_liczba(p)}–{_liczba(progi_okresu[i + 1])}' if i + 1 < len(progi_okresu) else f'>{_liczba(p)}')
        for i, p in enumerate(progi_okresu))
    ax.set_title(f"{tytul} — zakresy {zakresy_opis} {jednostka} (Lata: {okres})", fontsize=11)
    ax.set_xlabel("X [m] (EPSG:2180)")
    ax.set_ylabel("Y [m] (EPSG:2180)")
    ax.ticklabel_format(style='plain', useOffset=False)
    if przypis:
        # pod opisem osi X, jak adnotacje w kde_uszkodzenia_sparr.py
        ax.annotate("\n".join(textwrap.wrap(przypis, 120)), xy=(0, 0), xycoords="axes fraction",
                    xytext=(0, -40), textcoords="offset points", fontsize=8, color="#555555",
                    va="top", ha="left", annotation_clip=False)

    try:
        cx.add_basemap(ax, crs=poland.crs, source=cx.providers.Esri.WorldGrayCanvas, alpha=1, zoom=8)
    except Exception:
        pass

    # Legenda: PRZEDZIAŁY (contourf koloruje rozłączne pasma), najwyższe pasmo
    # z maksimum wygładzonej powierzchni - jak w kde_zasobnosc.py
    legend_elements = [
        mpatches.Patch(
            facecolor=kolory_pasm[i], edgecolor=kolor_linii, linewidth=1.2, alpha=0.7,
            label=(f'{_liczba(progi_okresu[i])}–{_liczba(progi_okresu[i + 1])} {jednostka}'
                   if i + 1 < len(progi_okresu)
                   else f'> {_liczba(progi_okresu[i])} {jednostka} (maks. {_liczba(maks)})'),
        )
        for i in range(len(progi_okresu) - 1, -1, -1)
    ]
    if etykieta_dodatnich:
        legend_elements.append(mlines.Line2D([], [], color=kolor_dodatnich, marker='o', linestyle='None',
                                             markersize=6, alpha=0.35, label=etykieta_dodatnich))
    legend_elements += [
        mlines.Line2D([], [], color='gray', marker='o', linestyle='None', markersize=4, alpha=0.4,
                      label='Trakt badany (tło)'),
        mlines.Line2D([], [], color='black', linewidth=1, label='Granica Polski'),
    ]
    ax.legend(handles=legend_elements, loc='center left', bbox_to_anchor=(1.01, 0.5),
              frameon=True, facecolor='white', fontsize=9, title="Legenda", title_fontsize=10)

    # ==========================================================================
    # ZAPIS WYNIKÓW
    # ==========================================================================
    os.makedirs(katalog, exist_ok=True)
    gdf_zasieg = gpd.GeoDataFrame(
        [{'rok_start': rok_start, 'rok_end': rok_end, **(atrybuty or {}),
          'prog': p, 'jednostka': jednostka,
          'srednia_krajowa': srednia_krajowa, 'max_lokalna': maks,
          'n_traktow': len(gdf_model), 'geometry': geom}
         for p, geom in zip(progi_okresu, zasiegi_geom)],
        geometry='geometry', crs=CRS_OBLICZENIOWY)

    sufiks_prog = "_".join(_liczba(p).replace(',', '.') for p in progi_okresu)
    sciezka = f"{katalog}/{prefiks}_{okres}_prog{sufiks_prog}"
    gdf_zasieg.to_crs(CRS_ZAPISU).to_file(f"{sciezka}.geojson", driver="GeoJSON")
    fig.savefig(f"{sciezka}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Zakończono pomyślnie. Zapisano wyniki dla lat {okres} ({opis}).")
    return f"{sciezka}.geojson"
