import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from Wisl_quert import query_zasobnosc, query_przyrost, martwe_drewno
from kde_srednia import (model_traktow, powierzchnia, granice_polski, rysuj_mape,
                         MIN_TRAKTOW_WIARYGODNY)

# ==============================================================================
# CO LICZY TEN SKRYPT
# ==============================================================================
# Mapę ZMIANY wskaźnika między dwoma cyklami: różnica dwóch wygładzonych map
# KDE (późniejszy minus wcześniejszy), policzonych tym samym estymatorem co
# mapy pojedynczych okresów (kde_srednia.powierzchnia), na tej samej siatce.
# Każdy okres wygładzany osobno, z własnym pasmem (reguła Scotta dla jego
# traktów - pasma okresów różnią się o kilka %).
#
# Wskaźniki (dane jak w skryptach pojedynczych okresów):
#   zasobnosc - Wisl_quert.query_zasobnosc (kde_zasobnosc.py, ogółem),
#   martwe    - Wisl_quert.martwe_drewno, suma typów (kde_martwe_drewno.py),
#   przyrost  - Wisl_quert.query_przyrost (kde_przyrost.py, od II cyklu).
# Wartość krajowa = różnica średnich krajowych obu okresów.
#
# Progi stałe dla wskaźnika (porównywalne między parami cykli); pasmo
# zawierające zero = "bez wyraźnej zmiany" (prawie białe), spadki brązowe,
# wzrosty zielone (_kolory). Kreskowanie: mało traktów w którymkolwiek z okresów.


def _zasobnosc(rok_start, rok_end):
    return pd.DataFrame(query_zasobnosc(rok_start=rok_start, rok_end=rok_end),
                        columns=['NR_TRAKTU', 'SR', 'SUMA_WSP_Z'])


def _martwe(rok_start, rok_end):
    # jak kde_martwe_drewno.martwe_drewno_mapa(rodzaj=None): całe martwe drewno
    # (leżące + stojące - w I cyklu także posusz zapisany wśród drzew > 7 cm,
    # Wisl_quert.martwe_drewno)
    df = pd.DataFrame(martwe_drewno(rok_start=rok_start, rok_end=rok_end),
                      columns=['NR_TRAKTU', 'SR_LEZACE', 'SR_STOJACE', 'SR', 'SUMA_WSP_Z'])
    return df[['NR_TRAKTU', 'SR', 'SUMA_WSP_Z']]


def _przyrost(rok_start, rok_end):
    return pd.DataFrame(query_przyrost(rok_start=rok_start, rok_end=rok_end),
                        columns=['NR_TRAKTU', 'SR', 'SUMA_WSP_Z'])


# Progi dobrane do zakresu zmian (2026-10-09, kolejne cykle): zmiany są
# głównie DODATNIE - zasobność krajowo +17 / +12 / +11 m3/ha, lokalnie (5.-95.
# percentyl) od -1 do +24 m3/ha, skrajnie -30 do +30; martwe drewno krajowo
# -0,4 / +2,7 / +3,9 m3/ha (po poprawce Wisl_quert.martwe_drewno 2026-10-09:
# I cykl ze stojącym, właściwe koło w I-II), lokalnie od -11,6 (Karpaty
# i Sudety 2005->2010) do +19,7 m3/ha - stąd więcej pasm po stronie wzrostu.
# Przyrost: krajowo -0,8 / -0,3 m3/ha/rok - progi symetryczne.
WSKAZNIKI = {
    'zasobnosc': {'nazwa': 'Zmiana zasobności drzewostanów', 'jednostka': 'm³/ha',
                  'dane': _zasobnosc, 'progi': [-10, -5, 5, 10, 20, 30]},
    'martwe': {'nazwa': 'Zmiana zasobności martwego drewna', 'jednostka': 'm³/ha',
               'dane': _martwe, 'progi': [-2, -1, 1, 2, 4, 8]},
    'przyrost': {'nazwa': 'Zmiana bieżącego rocznego przyrostu', 'jednostka': 'm³/ha/rok',
                 'dane': _przyrost, 'progi': [-2, -1, -0.5, 0.5, 1, 2]},
}


def _kolory(progi):
    """Paleta rozbieżna BrBG wg ODLEGŁOŚCI pasma od zera, nie pozycji na
    liście: pasmo zawierające zero prawie białe, spadki coraz ciemniej brązowe,
    wzrosty coraz ciemniej zielone (progi nie muszą być symetryczne). Klucz
    pasma = jego dolny próg; 'min' - pasmo poniżej najniższego progu."""
    progi = sorted(progi)
    dolne = ['min'] + progi
    gorne = progi + [float('inf')]
    ujemne = [i for i, g in enumerate(gorne) if g <= 0]          # całe poniżej zera
    dodatnie = [i for i, d in enumerate(dolne) if d != 'min' and d >= 0]
    kolory = {}
    for i, d in enumerate(dolne):
        if i in ujemne:
            ranga = len(ujemne) - ujemne.index(i)                  # 1 = najbliżej zera
            kolory[d] = plt.cm.BrBG(max(0.5 - 0.15 * ranga, 0.03))
        elif i in dodatnie:
            ranga = dodatnie.index(i) + 1
            kolory[d] = plt.cm.BrBG(min(0.5 + 0.11 * ranga, 0.97))
        else:
            kolory[d] = plt.cm.BrBG(0.5)                          # pasmo z zerem
    return kolory


PRZYPIS = ("Różnica dwóch wygładzonych map KDE: {okres_do} minus {okres_od} (każdy okres wygładzany "
           "osobno). Pasmo wokół zera - bez wyraźnej zmiany. Kreskowanie: mało traktów (efektywnie "
           "< 30) w którymkolwiek z okresów.")


def zmiana_mapa(wskaznik: str = 'zasobnosc', okres_od: str = '2015-2019', okres_do: str = '2020-2025',
                progi: list[float] = None):
    """
    Mapa zmiany wskaźnika między cyklami (okres_do minus okres_od), okresy
    jako 'RRRR-RRRR'. Zapis: KDE_zmiany/zmiana_{wskaznik}_{okres_od}_{okres_do}.geojson / .png
    """
    if wskaznik not in WSKAZNIKI:
        raise ValueError(f"wskaznik: {list(WSKAZNIKI)}")
    w = WSKAZNIKI[wskaznik]
    progi = progi or w['progi']
    (a1, b1), (a2, b2) = [tuple(int(r) for r in o.split('-')) for o in (okres_od, okres_do)]
    modele = []
    for a, b in [(a1, b1), (a2, b2)]:
        df = w['dane'](a, b)
        if df.empty:
            print(f"Brak danych ({wskaznik}) dla lat {a}-{b}.")
            return None
        df[['SR', 'SUMA_WSP_Z']] = df[['SR', 'SUMA_WSP_Z']].astype(float)
        model = model_traktow(df)
        if len(model) < MIN_TRAKTOW_WIARYGODNY:
            print(f"Pominięto mapę: za mało traktów ({wskaznik}, lata {a}-{b}).")
            return None
        modele.append(model)

    _, poland_geom = granice_polski()
    X, Y, przed, kraj_przed, n_eff_przed = powierzchnia(modele[0], poland_geom)
    _, _, po, kraj_po, n_eff_po = powierzchnia(modele[1], poland_geom)
    zmiana = po - przed
    n_eff = np.fmin(n_eff_przed, n_eff_po)
    n_eff[np.isnan(zmiana)] = np.nan

    return rysuj_mape(
        X, Y, zmiana, n_eff, modele[1], kraj_po - kraj_przed, a2, b2, progi, _kolory(progi),
        jednostka=w['jednostka'], tytul=w['nazwa'], katalog='KDE_zmiany', prefiks='zmiana',
        opis=f"zmiana {wskaznik}", atrybuty={'wskaznik': wskaznik, 'okres_od': okres_od},
        przypis=PRZYPIS.format(okres_od=okres_od, okres_do=okres_do),
        kolor_linii='#333333', kolor_etykiet='#222222',
        dwustronna=True, lata_tytul=f"{okres_od} → {okres_do}",
        nazwa_pliku=f"zmiana_{wskaznik}_{okres_od}_{okres_do}",
    )


if __name__ == "__main__":
    from Wisl_quert import CYKLE_LATA
    okresy = [f"{a}-{b}" for a, b in CYKLE_LATA]
    for wskaznik in WSKAZNIKI:
        lista = okresy[1:] if wskaznik == 'przyrost' else okresy
        for okres_od, okres_do in zip(lista, lista[1:]):
            zmiana_mapa(wskaznik, okres_od, okres_do)
