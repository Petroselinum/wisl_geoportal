import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from Wisl_quert import query_przyrost, query_uzytkowanie
from kde_srednia import (model_traktow, powierzchnia, granice_polski, rysuj_mape,
                         MIN_TRAKTOW_WIARYGODNY)

# ==============================================================================
# CO LICZY TEN SKRYPT
# ==============================================================================
# Lokalną INTENSYWNOŚĆ UŻYTKOWANIA - użytkowanie (rębne + przedrębne) jako
# % przyrostu miąższości w tym samym 5-letnim okresie między pomiarami:
#   intensywność = U / (5 * P) * 100 %
# U - wygładzone użytkowanie [m3/ha w okresie] (kde_uzytkowanie.py),
# P - wygładzony bieżący roczny przyrost [m3/ha/rok] (kde_przyrost.py).
# Obie mapy z tego samego estymatora (kde_srednia.powierzchnia), na tej samej
# siatce; iloraz liczony w każdym oczku. Powyżej 100% pozyskanie przekracza
# przyrost. Wartość krajowa = iloraz średnich krajowych (nie średnia ilorazów).
#
# Mianowniki obu średnich nie są identyczne: przyrost liczony jest tylko na
# podpowierzchniach z przyrostem (bez drzewostanów usuniętych w okresie -
# zrąb ma pozyskanie, ale nie ma przyrostu), użytkowanie na wszystkich
# pomierzonych ponownie (Wisl_quert.query_przyrost / query_uzytkowanie);
# różnica powierzchni to ok. 3%.
#
# Okres = lata pomiaru KOŃCOWEGO (jak w kde_przyrost / kde_uzytkowanie); dla
# 2005-2009 mapy nie ma. Kreskowanie: mało traktów w którejkolwiek z map.

# Progi STAŁE (porównywalne między okresami); 100% = użytkowanie równe
# przyrostowi. Dobrane do zakresu (2026-10-09): krajowo 52-67%, lokalnie
# zwykle 40-80%, maksima ok. 100-130%.
PROGI_INTENSYWNOSCI = [40, 50, 60, 70, 80, 100]

# od zieleni (użytkowanie wyraźnie poniżej przyrostu) przez żółty do czerwieni
# (powyżej przyrostu) - kolor przypisany wartości progu, stały między okresami
KOLORY_PROGOW_INTENSYWNOSCI = {
    40: plt.cm.RdYlGn_r(0.15),
    50: plt.cm.RdYlGn_r(0.30),
    60: plt.cm.RdYlGn_r(0.45),
    70: plt.cm.RdYlGn_r(0.60),
    80: plt.cm.RdYlGn_r(0.75),
    100: plt.cm.RdYlGn_r(0.95),
}

PRZYPIS = ("Użytkowanie (rębne i przedrębne) w okresie 5 lat między pomiarami tej samej powierzchni "
           "jako % przyrostu miąższości w tym okresie. Co roku mierzone jest ok. 20% powierzchni, "
           "więc mapa dla lat pomiaru {rok_start}-{rok_end} obejmuje lata {od}-{rok_end}. "
           "Kreskowanie: mało traktów (efektywnie < 30) w mapie przyrostu lub użytkowania.")


def intensywnosc_mapa(rok_start: int = 2020, rok_end: int = 2025,
                      progi: list[float] = PROGI_INTENSYWNOSCI):
    """
    Mapa intensywności użytkowania [% przyrostu] z obszarami ponad stałymi
    progami. rok_start, rok_end - lata pomiaru końcowego.
    Zapis: KDE_intensywnosc/intensywnosc_{okres}_prog....geojson / .png
    """
    okres = f"{rok_start}-{rok_end}"
    przyrost = pd.DataFrame(query_przyrost(rok_start=rok_start, rok_end=rok_end),
                            columns=['NR_TRAKTU', 'SR', 'SUMA_WSP_Z'])
    uzytk = pd.DataFrame(query_uzytkowanie(rok_start=rok_start, rok_end=rok_end),
                         columns=['NR_TRAKTU', 'REBNE', 'PRZEDREBNE', 'SUMA_WSP_Z'])
    if przyrost.empty or uzytk.empty:
        print(f"Brak danych przyrostu lub użytkowania dla lat {okres}.")
        return None
    przyrost[['SR', 'SUMA_WSP_Z']] = przyrost[['SR', 'SUMA_WSP_Z']].astype(float)
    uzytk[['REBNE', 'PRZEDREBNE', 'SUMA_WSP_Z']] = uzytk[['REBNE', 'PRZEDREBNE', 'SUMA_WSP_Z']].astype(float)
    uzytk['SR'] = uzytk['REBNE'] + uzytk['PRZEDREBNE']

    model_p = model_traktow(przyrost)
    model_u = model_traktow(uzytk[['NR_TRAKTU', 'SR', 'SUMA_WSP_Z']])
    if min(len(model_p), len(model_u)) < MIN_TRAKTOW_WIARYGODNY:
        print(f"Pominięto mapę: za mało traktów (lata {okres}).")
        return None

    _, poland_geom = granice_polski()
    X, Y, p, p_kraj, n_eff_p = powierzchnia(model_p, poland_geom)
    _, _, u, u_kraj, n_eff_u = powierzchnia(model_u, poland_geom)
    with np.errstate(divide='ignore', invalid='ignore'):
        intensywnosc = 100.0 * u / (5.0 * p)
    intensywnosc[~(p > 0)] = np.nan
    n_eff = np.fmin(n_eff_p, n_eff_u)
    n_eff[np.isnan(intensywnosc)] = np.nan

    return rysuj_mape(
        X, Y, intensywnosc, n_eff, model_u, 100.0 * u_kraj / (5.0 * p_kraj), rok_start, rok_end,
        progi, KOLORY_PROGOW_INTENSYWNOSCI,
        jednostka='%', tytul='Intensywność użytkowania (użytkowanie / przyrost)',
        katalog='KDE_intensywnosc', prefiks='intensywnosc', opis='intensywność użytkowania',
        przypis=PRZYPIS.format(rok_start=rok_start, rok_end=rok_end, od=rok_start - 5),
        kolor_linii='#7f2704', kolor_etykiet='#4a1500',
    )


if __name__ == "__main__":
    from Wisl_quert import CYKLE_LATA
    for rok_start, rok_end in CYKLE_LATA[1:]:
        intensywnosc_mapa(rok_start=rok_start, rok_end=rok_end)
