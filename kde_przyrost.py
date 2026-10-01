import matplotlib.pyplot as plt
import pandas as pd
from Wisl_quert import query_przyrost
from kde_srednia import mapa_sredniej

# ==============================================================================
# CO LICZY TEN SKRYPT
# ==============================================================================
# Lokalny, wygładzony przestrzennie BIEŻĄCY ROCZNY PRZYROST miąższości
# [m3/ha/rok] - z pomiaru powtórzonego na tej samej podpowierzchni po 5 latach
# (OBL_ADRES_POW.PRZYROST = P_V_II - P_V_I + P_U, w m3 na podpowierzchni).
# Przeliczenie na hektar i wybór podpowierzchni - Wisl_quert.query_przyrost
# (koło wspólne obu pomiarów, średnia traktu ważona WSP_Z). Estymator i wygląd
# mapy jak w kde_zasobnosc.py (kde_srednia.mapa_sredniej).
#
# Okres = lata pomiaru KOŃCOWEGO: 2010-2014 to przyrost między I a II cyklem.
# Każda podpowierzchnia ma odstęp pomiarów dokładnie 5 lat, ale co roku
# mierzone jest ok. 20% powierzchni, więc mapa 2010-2014 obejmuje lata
# 2005-2014 (PRZYPIS na mapie). Dla 2005-2009 mapy nie ma (brak wcześniejszego
# pomiaru).
#
# Średnie krajowe z tego potoku (2026-10-01): 10,93 / 10,12 / 9,81 m3/ha/rok
# w latach 2010-2014 / 2015-2019 / 2020-2025.

# Progi STAŁE (porównywalne między okresami), dobrane do zakresu wygładzonej
# powierzchni: 5.-95. percentyl to ok. 8,5-12,5 m3/ha/rok, maksima 12,8-13,5.
PROGI_PRZYROSTU = [9, 10, 11, 12, 13]

# Paleta BuGn jak wskaźnik "Przyrost" w kartogramach portalu (portal_warstwy.py)
KOLORY_PROGOW_PRZYROSTU = {
    9: plt.cm.BuGn(0.25),
    10: plt.cm.BuGn(0.40),
    11: plt.cm.BuGn(0.55),
    12: plt.cm.BuGn(0.72),
    13: plt.cm.BuGn(0.92),
}


PRZYPIS = ("Przyrost między dwoma pomiarami tej samej powierzchni próbnej (5 lat), w przeliczeniu "
           "na rok. Co roku mierzone jest ok. 20% powierzchni, więc mapa dla lat pomiaru "
           "{rok_start}-{rok_end} obejmuje lata {od}-{rok_end} - każda powierzchnia ze swojego "
           "5-letniego okresu.")


def przyrost_mapa(rok_start: int = 2020, rok_end: int = 2025, progi: list[float] = PROGI_PRZYROSTU):
    """
    Mapa lokalnego średniego przyrostu [m3/ha/rok] z obszarami ponad stałymi
    progami. rok_start, rok_end - lata pomiaru końcowego (ADRES_POW.DATA).
    Zapis: KDE_przyrost/przyrost_{okres}_prog....geojson / .png
    """
    df = pd.DataFrame(query_przyrost(rok_start=rok_start, rok_end=rok_end),
                      columns=['NR_TRAKTU', 'SR', 'SUMA_WSP_Z'])
    df[['SR', 'SUMA_WSP_Z']] = df[['SR', 'SUMA_WSP_Z']].astype(float)
    return mapa_sredniej(
        df, rok_start, rok_end, progi, KOLORY_PROGOW_PRZYROSTU,
        jednostka='m³/ha/rok', tytul='Bieżący roczny przyrost miąższości',
        katalog='KDE_przyrost', prefiks='przyrost', opis='przyrost',
        przypis=PRZYPIS.format(rok_start=rok_start, rok_end=rok_end, od=rok_start - 5),
        kolor_linii='#00441b',
    )


if __name__ == "__main__":
    from Wisl_quert import CYKLE_LATA
    for rok_start, rok_end in CYKLE_LATA:
        przyrost_mapa(rok_start=rok_start, rok_end=rok_end)
