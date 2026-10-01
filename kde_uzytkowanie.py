import matplotlib.pyplot as plt
import pandas as pd
from Wisl_quert import query_uzytkowanie
from kde_srednia import mapa_sredniej

# ==============================================================================
# CO LICZY TEN SKRYPT
# ==============================================================================
# Lokalne, wygładzone przestrzennie UŻYTKOWANIE (pozyskanie grubizny) w okresie
# między dwoma pomiarami tej samej podpowierzchni [m3/ha] - wartości 5-letnie
# (sumy z okresu, nie roczne), jak wykresy użytkowania w portalu:
#   rodzaj=None          - rębne + przedrębne,
#   rodzaj='rebne'       - OBL_ADRES_POW.POZ_REBNE_V,
#   rodzaj='przedrebne'  - OBL_ADRES_POW.POZ_PRZEDR_V.
# Przeliczenie na hektar i wybór podpowierzchni - Wisl_quert.query_uzytkowanie
# (wszystkie podpowierzchnie pomierzone ponownie, brak wycinki = 0). Estymator
# i wygląd mapy jak w kde_zasobnosc.py (kde_srednia.mapa_sredniej).
#
# Okres = lata pomiaru KOŃCOWEGO: 2010-2014 to użytkowanie między I a II
# cyklem. Każda podpowierzchnia ma odstęp pomiarów dokładnie 5 lat, ale co
# roku mierzone jest ok. 20% powierzchni (panele), więc mapa 2010-2014
# obejmuje użytkowanie z lat 2005-2014 - każda podpowierzchnia ze swojego
# 5-letniego okna. Opisane w przypisie na mapie (PRZYPIS). Dla 2005-2009 mapy
# nie ma (brak wcześniejszego pomiaru).
#
# Średnie krajowe z tego potoku (2026-10-01), rębne / przedrębne [m3/ha, 5 lat]:
# 2010-2014: 10,96 / 17,64 | 2015-2019: 13,54 / 17,82 | 2020-2025: 15,27 / 17,50.

RODZAJE_UZYTKOWANIA = {
    None: 'rębne i przedrębne',
    'rebne': 'rębne',
    'przedrebne': 'przedrębne',
}

# Progi STAŁE dla każdego rodzaju osobno (porównywalne między okresami),
# dobrane do zakresu wygładzonej powierzchni (5.-95. percentyl / maksimum):
#   razem 21-43 / 49-69, rębne 6-23 / 28-43, przedrębne 13-22,5 / 26.
PROGI_UZYTKOWANIA = {
    None: [25, 30, 35, 40, 50],
    'rebne': [10, 15, 20, 25, 30],
    'przedrebne': [14, 16, 18, 20, 22],
}

# Ta sama skala barw (PuRd) dla wszystkich rodzajów - kolor wg pozycji progu
# w zestawie danego rodzaju, stały między okresami.
_ODCIENIE = [0.25, 0.40, 0.55, 0.72, 0.92]
KOLORY_PROGOW_UZYTKOWANIA = {
    rodzaj: {p: plt.cm.PuRd(o) for p, o in zip(progi, _ODCIENIE)}
    for rodzaj, progi in PROGI_UZYTKOWANIA.items()
}


PRZYPIS = ("Użytkowanie w okresie między dwoma pomiarami tej samej powierzchni próbnej "
           "(5 lat). Co roku mierzone jest ok. 20% powierzchni, więc mapa dla lat pomiaru "
           "{rok_start}-{rok_end} obejmuje użytkowanie z lat {od}-{rok_end} - każda powierzchnia "
           "ze swojego 5-letniego okresu.")


def uzytkowanie_mapa(rok_start: int = 2020, rok_end: int = 2025, rodzaj: str | None = None,
                     progi: list[float] = None):
    """
    Mapa lokalnego średniego użytkowania [m3/ha, 5 lat] z obszarami ponad
    stałymi progami. rok_start, rok_end - lata pomiaru końcowego.
    rodzaj: None (razem), 'rebne' albo 'przedrebne'.
    Zapis: KDE_uzytkowanie/uzytkowanie[_rebne|_przedrebne]_{okres}_prog....
    """
    if rodzaj not in RODZAJE_UZYTKOWANIA:
        raise ValueError(f"rodzaj: {list(RODZAJE_UZYTKOWANIA)}")
    df = pd.DataFrame(query_uzytkowanie(rok_start=rok_start, rok_end=rok_end),
                      columns=['NR_TRAKTU', 'REBNE', 'PRZEDREBNE', 'SUMA_WSP_Z'])
    df[['REBNE', 'PRZEDREBNE', 'SUMA_WSP_Z']] = df[['REBNE', 'PRZEDREBNE', 'SUMA_WSP_Z']].astype(float)
    df['SR'] = {None: df['REBNE'] + df['PRZEDREBNE'],
                'rebne': df['REBNE'], 'przedrebne': df['PRZEDREBNE']}[rodzaj]

    nazwa = RODZAJE_UZYTKOWANIA[rodzaj]
    return mapa_sredniej(
        df[['NR_TRAKTU', 'SR', 'SUMA_WSP_Z']], rok_start, rok_end,
        progi or PROGI_UZYTKOWANIA[rodzaj], KOLORY_PROGOW_UZYTKOWANIA[rodzaj],
        jednostka='m³/ha', tytul=f'Użytkowanie {nazwa}',
        przypis=PRZYPIS.format(rok_start=rok_start, rok_end=rok_end, od=rok_start - 5),
        katalog='KDE_uzytkowanie', prefiks='uzytkowanie' + (f'_{rodzaj}' if rodzaj else ''),
        opis=f'użytkowanie {nazwa}', atrybuty={'rodzaj_uzytkowania': rodzaj or 'razem'},
        kolor_linii='#67001f', kolor_etykiet='#49000f',
        etykieta_dodatnich={None: 'Trakt z użytkowaniem', 'rebne': 'Trakt z użytkowaniem rębnym',
                            'przedrebne': 'Trakt z użytkowaniem przedrębnym'}[rodzaj],
        kolor_dodatnich='#ce1256',
    )


if __name__ == "__main__":
    from Wisl_quert import CYKLE_LATA
    for rodzaj in RODZAJE_UZYTKOWANIA:
        for rok_start, rok_end in CYKLE_LATA:
            uzytkowanie_mapa(rok_start=rok_start, rok_end=rok_end, rodzaj=rodzaj)
