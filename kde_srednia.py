"""
Wspólna mapa lokalnej, wygładzonej przestrzennie ŚREDNIEJ wielkości na hektar
(estymator Nadaraya-Watson) dla kde_przyrost.py, kde_uzytkowanie.py,
kde_intensywnosc.py i kde_zmiany.py.

Ta sama metoda i ten sam wygląd co w kde_zasobnosc.py / kde_martwe_drewno.py:
    f = KDE ważone SR * SUMA_WSP_Z (ilość przypadająca na trakt)
    g = KDE ważone SUMA_WSP_Z (reprezentowana powierzchnia traktu)
    wynik = f/g * sum(waga_f)/sum(waga_g)    -> średnia w jednostkach SR
ze wspólnym fizycznym pasmem obu KDE (kde_common.wymus_wspolne_pasmo),
odcięciem brzegów o niskiej gęstości tła i STAŁYMI progami (porównywalnymi
między okresami). Zapis: GeoJSON z wielokątami KUMULATYWNYMI (próg wyższy
leży w niższym) w EPSG:4326 + mapa PNG 300 dpi. Obszary, gdzie wynik opiera
się na małej liczbie traktów, są kreskowane (kde_common.oznacz_niska_wiarygodnosc).

powierzchnia() liczy powierzchnię z traktów, rysuj_mape() rysuje i zapisuje
GOTOWĄ powierzchnię - także złożoną z kilku (iloraz w kde_intensywnosc.py,
różnica okresów w kde_zmiany.py).
"""
import os
import matplotlib.pyplot as plt
from matplotlib import patches as mpatches
from matplotlib import lines as mlines
from matplotlib.colors import to_hex
import numpy as np
import geopandas as gpd
import shapely
from scipy.stats import gaussian_kde
from matplotlib_map_utils.core.north_arrow import north_arrow
from matplotlib_map_utils.core.scale_bar import scale_bar
from kde_common import (
    dodaj_podklad,
    wymus_wspolne_pasmo,
    kontur_na_zasieg,
    etykietuj_kontury,
    efektywna_liczba_traktow_siatka,
    odetnij_malo_traktow,
    dodaj_przypis,
    PRZYPIS_ODCIECIA,
    oznacz_niska_wiarygodnosc,
    zapisz_wiarygodnosc,
)

CRS_OBLICZENIOWY = "EPSG:2180"
CRS_ZAPISU = "EPSG:4326"

PROG_MIN_TLA = 0.01           # poniżej tego ułamka maksimum gęstości tła nie ufamy ilorazowi (brzegi)
MIN_TRAKTOW_WIARYGODNY = 100  # globalny próg wiarygodności modelu (ten sam co w pozostałych skryptach KDE)


def _liczba(x, znak=False):
    """12.5 -> '12,5', 10.0 -> '10'; znak=True: '+10', '−10' (zmiany)."""
    tekst = f"{abs(x) if znak else x:.1f}".rstrip('0').rstrip('.').replace('.', ',')
    if znak:
        tekst = ('+' if x > 0 else '−' if x < 0 else '') + tekst
    return tekst


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


def granice_polski():
    poland = gpd.read_file("data/poland_land.geojson").to_crs(CRS_OBLICZENIOWY)
    return poland, poland.geometry.union_all()


def powierzchnia(gdf_model, poland_geom, rozdzielczosc=500):
    """Siatka X, Y, wygładzona lokalna średnia (NaN poza Polską i na brzegach
    o zbyt niskiej gęstości tła), średnia krajowa ważona powierzchnią
    i efektywna liczba traktów tła (NaN tam, gdzie średnia jest NaN)."""
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
    n_eff = efektywna_liczba_traktow_siatka(coords, waga_tlo, kernel_tlo, X, Y, wartosc=wartosc)
    return X, Y, wartosc, float(srednia_krajowa), n_eff


def mapa_sredniej(df, rok_start, rok_end, progi, kolory_progow, *, jednostka, tytul, katalog,
                  prefiks, opis, atrybuty=None, kolor_linii='#1b5e20', kolor_etykiet='black',
                  etykieta_dodatnich=None, kolor_dodatnich='#7b1fa2', przypis=None):
    """
    df: NR_TRAKTU, SR, SUMA_WSP_Z (wynik zapytania z Wisl_quert).
    Pozostałe parametry - rysuj_mape. Zwraca ścieżkę GeoJSON albo None.
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
    poland, poland_geom = granice_polski()
    X, Y, wartosc, srednia_krajowa, n_eff = powierzchnia(gdf_model, poland_geom)
    return rysuj_mape(
        X, Y, wartosc, n_eff, gdf_model, srednia_krajowa, rok_start, rok_end, progi, kolory_progow,
        jednostka=jednostka, tytul=tytul, katalog=katalog, prefiks=prefiks, opis=opis,
        atrybuty=atrybuty, kolor_linii=kolor_linii, kolor_etykiet=kolor_etykiet,
        punkty_dodatnie=gdf_model[gdf_model['SR'] > 0] if etykieta_dodatnich else None,
        etykieta_dodatnich=etykieta_dodatnich, kolor_dodatnich=kolor_dodatnich, przypis=przypis)


def rysuj_mape(X, Y, wartosc, n_eff, gdf_model, srednia_krajowa, rok_start, rok_end, progi,
               kolory_progow, *, jednostka, tytul, katalog, prefiks, opis, atrybuty=None,
               kolor_linii='#1b5e20', kolor_etykiet='black', punkty_dodatnie=None,
               etykieta_dodatnich=None, kolor_dodatnich='#7b1fa2', przypis=None,
               dwustronna=False, lata_tytul=None, nazwa_pliku=None):
    """
    Rysuje i zapisuje gotową powierzchnię `wartosc` (siatka X, Y).

    progi: stałe progi - progi poza zakresem wartości okresu są pomijane.
    kolory_progow: {prog: kolor} - kolor przypisany wartości progu, nie
        pozycji (pasmo ma ten sam odcień w każdym okresie).
    dwustronna: mapa zmian (wartości ujemne i dodatnie) - pasmo poniżej
        najniższego progu też jest kolorowane (klucz 'min' w kolory_progow),
        opisy ze znakiem (+10 / −10). Pasmo dolne zapisane w GeoJSON z progiem
        = minimum (cały obszar z wartościami), dzięki czemu kumulatywne
        wielokąty dalej opisują wszystkie pasma.
    jednostka: np. 'm³/ha/rok' (opisy PNG i atrybut 'jednostka').
    tytul: początek tytułu mapy (dalej zakresy i lata); lata_tytul - zamiast
        "rok_start-rok_end" (np. "2015-2019 → 2020-2025").
    katalog, prefiks: zapis {katalog}/{prefiks}_{okres}_prog{progi}.geojson/.png
        (albo {katalog}/{nazwa_pliku}.geojson/.png, gdy podana nazwa_pliku).
    punkty_dodatnie / etykieta_dodatnich: trakty zaznaczone osobnym kolorem
        (np. 'Trakt z użytkowaniem rębnym').
    przypis: uwaga metodyczna pod mapą (np. okres, którego dotyczą wartości).
    Każdy wiersz GeoJSON ma też 'kolor' i 'etykieta' pasma - portal pokazuje
    dokładnie tę legendę co PNG. Zwraca ścieżkę GeoJSON albo None.
    """
    okres = f"{rok_start}-{rok_end}"
    lata_tytul = lata_tytul or okres
    poland, poland_geom = granice_polski()
    granica_polski = poland_geom.boundary
    fmt = (lambda v: _liczba(v, znak=True)) if dwustronna else _liczba

    # gdzie wynik opierałby się na efektywnie < 10 traktach, mapy nie ma
    # (kde_common.odetnij_malo_traktow) - przed maksimum i progami
    if odetnij_malo_traktow(wartosc, n_eff):
        przypis = f"{przypis} {PRZYPIS_ODCIECIA}" if przypis else PRZYPIS_ODCIECIA
    wartosci_valid = wartosc[~np.isnan(wartosc)]
    if wartosci_valid.size == 0:
        print(f"Brak poprawnych wartości dla lat {lata_tytul} ({opis}).")
        return None
    maks = float(np.nanmax(wartosci_valid))
    minimum = float(np.nanmin(wartosci_valid))

    progi_okresu = sorted(p for p in set(progi) if minimum < p < maks) if dwustronna \
        else sorted(p for p in set(progi) if p < maks)
    if not progi_okresu:
        print(f"Lata {lata_tytul} ({opis}): wartości nie przekraczają żadnego z progów "
              f"{sorted(set(progi))} {jednostka} (zakres {minimum:.2f}-{maks:.2f}) - pomijam mapę.")
        return None

    print(f"{opis} | Lata: {lata_tytul} | n_traktow={len(gdf_model)} | "
          f"srednia krajowa={srednia_krajowa:.2f} {jednostka} | "
          + " | ".join(f"> {fmt(p)}" for p in progi_okresu)
          + f" | zakres lokalny {minimum:.2f}-{maks:.2f} {jednostka}")

    # Pasma: (dolna granica, kolor, opis). W mapie dwustronnej pierwsze pasmo
    # zaczyna się od minimum - kolor i opis pasma progów, w którym leży minimum
    # (np. minimum +1,8 przy progach 1 i 2 -> pasmo "+1 – +2", nie "poniżej
    # najniższego progu"); 'min' tylko, gdy minimum jest poniżej wszystkich progów.
    if dwustronna:
        ponizej = [p for p in progi if p <= minimum]
        dolny = max(ponizej) if ponizej else 'min'
        poziomy = [minimum] + progi_okresu
        kolory_pasm = [kolory_progow[dolny]] + [kolory_progow[p] for p in progi_okresu]
        opisy = ([f'{fmt(dolny)} – {fmt(progi_okresu[0])} {jednostka} (min. {fmt(minimum)})' if ponizej
                  else f'< {fmt(progi_okresu[0])} {jednostka} (min. {fmt(minimum)})']
                 + [f'{fmt(p)} – {fmt(progi_okresu[i + 1])} {jednostka}'
                    for i, p in enumerate(progi_okresu[:-1])]
                 + [f'≥ {fmt(progi_okresu[-1])} {jednostka} (maks. {fmt(maks)})'])
    else:
        poziomy = progi_okresu
        kolory_pasm = [kolory_progow[p] for p in progi_okresu]
        opisy = ([f'{fmt(p)}–{fmt(progi_okresu[i + 1])} {jednostka}' for i, p in enumerate(progi_okresu[:-1])]
                 + [f'> {fmt(progi_okresu[-1])} {jednostka} (maks. {fmt(maks)})'])

    # ==========================================================================
    # WIZUALIZACJA I EKSTRAKCJA GEOMETRII (jak kde_zasobnosc.py)
    # ==========================================================================
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')
    ax.contourf(X, Y, wartosc, levels=poziomy + [maks], colors=kolory_pasm, alpha=0.7)
    # Poza obszarem z wartościami - poniżej wszystkich poziomów, żeby pętle
    # konturu były zamknięte (kontur_na_zasieg). Dla wielkości nieujemnych to
    # 0, dla zmian - poniżej minimum.
    do_konturu = np.nan_to_num(wartosc, nan=minimum - 1.0 if dwustronna else 0.0)
    cs = ax.contour(X, Y, do_konturu, levels=progi_okresu, colors=[kolor_linii], linewidths=1.2)

    # Wielokąty KUMULATYWNE (zagnieżdżone) - cs.allsegs[i] to kontur i-tego progu;
    # w mapie dwustronnej na początku cały obszar z wartościami (niewidoczny
    # kontur tuż poniżej minimum) - podstawa najniższego pasma
    zasiegi_geom = [kontur_na_zasieg(segs) for segs in cs.allsegs]
    if dwustronna:
        obrys = ax.contour(X, Y, do_konturu, levels=[minimum - 0.5], linewidths=0)
        zasiegi_geom.insert(0, kontur_na_zasieg(obrys.allsegs[0]))
        obrys.remove()

    # Etykiety progów wzdłuż pętli konturu (kde_common.etykietuj_kontury); bez
    # pomocniczego obrysu mapy dwustronnej
    etykietuj_kontury(ax, progi_okresu, zasiegi_geom[1:] if dwustronna else zasiegi_geom, granica_polski,
                      lambda p: f"{'' if dwustronna else '> '}{fmt(p)} {jednostka}", kolor=kolor_etykiet)

    obszar_malo, uchwyt_malo = oznacz_niska_wiarygodnosc(ax, X, Y, n_eff)

    gdf_model.plot(ax=ax, color='gray', markersize=3, alpha=0.3)
    if punkty_dodatnie is not None and len(punkty_dodatnie):
        punkty_dodatnie.plot(ax=ax, color=kolor_dodatnich, markersize=6, alpha=0.35)
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

    if dwustronna:
        ax.set_title(f"{tytul} (Lata: {lata_tytul})", fontsize=11)
    else:
        zakresy_opis = ', '.join(
            (f'{fmt(p)}–{fmt(progi_okresu[i + 1])}' if i + 1 < len(progi_okresu) else f'>{fmt(p)}')
            for i, p in enumerate(progi_okresu))
        ax.set_title(f"{tytul} — zakresy {zakresy_opis} {jednostka} (Lata: {lata_tytul})", fontsize=11)
    ax.set_xlabel("X [m] (EPSG:2180)")
    ax.set_ylabel("Y [m] (EPSG:2180)")
    ax.ticklabel_format(style='plain', useOffset=False)
    if przypis:
        dodaj_przypis(ax, przypis)

    dodaj_podklad(ax, poland.crs)

    # Legenda: PRZEDZIAŁY (contourf koloruje rozłączne pasma), najwyższe na górze
    legend_elements = [
        mpatches.Patch(facecolor=kolory_pasm[i], edgecolor=kolor_linii, linewidth=1.2, alpha=0.7,
                       label=opisy[i])
        for i in range(len(poziomy) - 1, -1, -1)
    ]
    if uchwyt_malo is not None:
        legend_elements.append(uchwyt_malo)
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
          'prog': p, 'jednostka': jednostka, 'kolor': to_hex(kol), 'etykieta': et,
          'srednia_krajowa': srednia_krajowa, 'max_lokalna': maks, 'min_lokalna': minimum,
          'n_traktow': len(gdf_model), 'geometry': geom}
         for p, kol, et, geom in zip(poziomy, kolory_pasm, opisy, zasiegi_geom)],
        geometry='geometry', crs=CRS_OBLICZENIOWY)

    if nazwa_pliku:
        sciezka = f"{katalog}/{nazwa_pliku}"
    else:
        sufiks_prog = "_".join(_liczba(p).replace(',', '.') for p in progi_okresu)
        sciezka = f"{katalog}/{prefiks}_{okres}_prog{sufiks_prog}"
    gdf_zasieg.to_crs(CRS_ZAPISU).to_file(f"{sciezka}.geojson", driver="GeoJSON")
    zapisz_wiarygodnosc(obszar_malo, f"{sciezka}.geojson", CRS_OBLICZENIOWY, CRS_ZAPISU)
    fig.savefig(f"{sciezka}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Zakończono pomyślnie. Zapisano wyniki dla lat {lata_tytul} ({opis}).")
    return f"{sciezka}.geojson"
