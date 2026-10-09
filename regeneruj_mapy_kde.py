"""
Ponowne wygenerowanie map KDE (PNG + GeoJSON) skryptów kde_*.

Plan = PEŁNY ZESTAW wariantów zapisany w tym pliku (pelny_zestaw) + warianty
odczytane z nazw istniejących map PNG (np. dodane ręcznie, spoza pełnego
zestawu). Wcześniej plan brał się WYŁĄCZNIE z istniejących PNG, więc mapa,
której plik zniknął (np. przerwane przeliczanie sparr - 2026-10-05 zostało 38
ze 124 map), nigdy nie wracała.

    KDE_gatunki/mapa_{GAT}_{okres}_{drzewostany|gatunek}_{miara}.png
                                          -> kde_gat.plot_kde_for_species
    KDE_zasobnosc/zasobnosc[_GAT]_{okres}_prog....png
                                          -> kde_zasobnosc.zasobnosc_mapa
    KDE_martwe_drewno/martwe_drewno_{okres}[_lezace|_stojace]_prog....png
                                          -> kde_martwe_drewno.martwe_drewno_mapa
    KDE_przyrost/przyrost_{okres}_prog....png
                                          -> kde_przyrost.przyrost_mapa
    KDE_uzytkowanie/uzytkowanie[_rebne|_przedrebne]_{okres}_prog....png
                                          -> kde_uzytkowanie.uzytkowanie_mapa
    KDE_intensywnosc/intensywnosc_{okres}_prog....png
                                          -> kde_intensywnosc.intensywnosc_mapa
    KDE_zmiany/zmiana_{wskaznik}_{okres_od}_{okres_do}.png
                                          -> kde_zmiany.zmiana_mapa
    KDE_uszkodzenia/udzial_uszkodzonych_{okres}[_GAT][_nasilN][_przyczN].png
                                          -> kde_uszkodzenia.uszkodzenia
    KDE_uszkodzenia_ryzyko/ryzyko_{okres}[_GAT][_nasilN][_przyczN]_sparr.png
                                          -> kde_uszkodzenia_sparr.uszkodzenia (R, sparr)

Część wariantów pełnego zestawu z założenia nie daje mapy (np. uszkodzenia
z rzadkiej przyczyny nie przekraczają żadnego progu, gatunek ma < 100 traktów)
- skrypt wtedy tylko wypisuje komunikat i idzie dalej.

Uwaga: jeśli po przeliczeniu zmieni się lista osiągniętych progów, zmieni się
też sufiks _prog... w nazwie pliku - wtedy stary plik zostaje obok nowego
(portal bierze najnowszy).

Uruchomienie (z działającą bazą i WISL_DB_PASSWORD w środowisku):
    python regeneruj_mapy_kde.py                         - przelicz wszystkie mapy
    python regeneruj_mapy_kde.py kde_uszkodzenia_sparr   - tylko wybrane skrypty
    python regeneruj_mapy_kde.py --brakujace [skrypty]   - tylko warianty bez mapy PNG
    python regeneruj_mapy_kde.py --plan [skrypty...]     - tylko wypisz wywołania (bez bazy)
"""
import importlib
import os
import re
import sys
import time
import traceback
from pathlib import Path

KATALOG = Path(__file__).resolve().parent

# Pełny zestaw - jak w blokach __main__ skryptów kde_* (bez importu Wisl_quert,
# żeby --plan działało bez bazy). Okresy = Wisl_quert.CYKLE_LATA.
OKRESY = [(2005, 2009), (2010, 2014), (2015, 2019), (2020, 2025)]
GATUNKI = ['SO', 'ŚW', 'JD', 'MD', 'DB', 'BK', 'BRZ', 'OL']
PRZYCZYNY = list(range(11, 33))      # Wisl_quert.PRZYCZYNY_USZK


def _okres(p):
    return f"{p['rok_start']}-{p['rok_end']}"


def _parametry_uszkodzen(okres_od, okres_do, sufiksy):
    """'_BK_nasil5_przycz11' -> parametry funkcji uszkodzenia()."""
    param = dict(rok_start=int(okres_od), rok_end=int(okres_do),
                 prog_nasil_uszk=None, gatunek=None, przycz_uszk=None)
    for tok in filter(None, sufiksy.split('_')):
        if tok.startswith('nasil'):
            param['prog_nasil_uszk'] = int(tok[5:])
        elif tok.startswith('przycz'):
            param['przycz_uszk'] = int(tok[6:])
        else:
            param['gatunek'] = tok
    return param


def _sufiks_uszkodzen(p):
    return ''.join([f"_{p['gatunek']}" if p['gatunek'] else '',
                    f"_nasil{p['prog_nasil_uszk']}" if p['prog_nasil_uszk'] is not None else '',
                    f"_przycz{p['przycz_uszk']}" if p['przycz_uszk'] is not None else ''])


def oczekiwane_png(modul, p):
    """Wzorzec (glob) mapy PNG, którą zapisuje dane wywołanie."""
    if modul == 'kde_gat':
        typ = 'drzewostany' if p['drzewostany'] else 'gatunek'
        return f"KDE_gatunki/mapa_{p['gat']}_{_okres(p)}_{typ}_{p['miara']}.png"
    if modul == 'kde_zasobnosc':
        gat = f"_{p['gatunek']}" if p['gatunek'] else ''
        return f"KDE_zasobnosc/zasobnosc{gat}_{_okres(p)}_prog*.png"
    if modul == 'kde_martwe_drewno':
        suf = f"_{p['rodzaj']}" if p['rodzaj'] else ''
        return f"KDE_martwe_drewno/martwe_drewno_{_okres(p)}{suf}_prog*.png"
    if modul == 'kde_przyrost':
        return f"KDE_przyrost/przyrost_{_okres(p)}_prog*.png"
    if modul == 'kde_uzytkowanie':
        rodz = f"_{p['rodzaj']}" if p['rodzaj'] else ''
        return f"KDE_uzytkowanie/uzytkowanie{rodz}_{_okres(p)}_prog*.png"
    if modul == 'kde_intensywnosc':
        return f"KDE_intensywnosc/intensywnosc_{_okres(p)}_prog*.png"
    if modul == 'kde_zmiany':
        return f"KDE_zmiany/zmiana_{p['wskaznik']}_{p['okres_od']}_{p['okres_do']}.png"
    if modul == 'kde_uszkodzenia':
        return f"KDE_uszkodzenia/udzial_uszkodzonych_{_okres(p)}{_sufiks_uszkodzen(p)}.png"
    if modul == 'kde_uszkodzenia_sparr':
        return f"KDE_uszkodzenia_ryzyko/ryzyko_{_okres(p)}{_sufiks_uszkodzen(p)}_sparr.png"
    raise ValueError(modul)


def pelny_zestaw():
    """Wszystkie warianty, które powinny istnieć (bez wariantów, które
    z definicji nie mają danych: przyrost / użytkowanie w I cyklu 2005-2009)."""
    w = []
    for gat in GATUNKI:
        for drzewostany, miara in [(True, 'powierzchnia'), (False, 'miazszosc')]:
            for a, b in OKRESY:
                w.append(('kde_gat', 'plot_kde_for_species',
                          dict(gat=gat, rok_start=a, rok_end=b, drzewostany=drzewostany, miara=miara)))
    for gat in [None] + GATUNKI:
        for a, b in OKRESY:
            w.append(('kde_zasobnosc', 'zasobnosc_mapa', dict(rok_start=a, rok_end=b, gatunek=gat)))
    for rodzaj in [None, 'lezace', 'stojace']:
        for a, b in OKRESY:
            w.append(('kde_martwe_drewno', 'martwe_drewno_mapa',
                      dict(rok_start=a, rok_end=b, rodzaj=rodzaj)))
    for a, b in OKRESY[1:]:
        w.append(('kde_przyrost', 'przyrost_mapa', dict(rok_start=a, rok_end=b)))
    for rodzaj in [None, 'rebne', 'przedrebne']:
        for a, b in OKRESY[1:]:
            w.append(('kde_uzytkowanie', 'uzytkowanie_mapa', dict(rok_start=a, rok_end=b, rodzaj=rodzaj)))
    for a, b in OKRESY[1:]:
        w.append(('kde_intensywnosc', 'intensywnosc_mapa', dict(rok_start=a, rok_end=b)))
    # zmiany między kolejnymi cyklami (przyrost - od II cyklu)
    for wskaznik, okresy in [('zasobnosc', OKRESY), ('martwe', OKRESY), ('przyrost', OKRESY[1:])]:
        for (a1, b1), (a2, b2) in zip(okresy, okresy[1:]):
            w.append(('kde_zmiany', 'zmiana_mapa',
                      dict(wskaznik=wskaznik, okres_od=f"{a1}-{b1}", okres_do=f"{a2}-{b2}")))
    for a, b in OKRESY:
        for przycz in [None] + PRZYCZYNY:
            w.append(('kde_uszkodzenia', 'uszkodzenia',
                      dict(rok_start=a, rok_end=b, prog_nasil_uszk=None, gatunek=None, przycz_uszk=przycz)))
    for a, b in OKRESY:
        for gat, przycz in [(None, None)] + [(g, None) for g in GATUNKI] + [(None, p) for p in PRZYCZYNY]:
            w.append(('kde_uszkodzenia_sparr', 'uszkodzenia',
                      dict(rok_start=a, rok_end=b, prog_nasil_uszk=None, gatunek=gat, przycz_uszk=przycz)))
    return w


def z_istniejacych_png():
    """Lista (moduł, funkcja, parametry) odtworzona z nazw istniejących map PNG."""
    wywolania = []
    for f in sorted((KATALOG / 'KDE_gatunki').glob('mapa_*.png')):
        m = re.fullmatch(r'mapa_(.+)_(\d{4})-(\d{4})_(drzewostany|gatunek)_(\w+)\.png', f.name)
        wywolania.append(('kde_gat', 'plot_kde_for_species',
                          dict(gat=m[1], rok_start=int(m[2]), rok_end=int(m[3]),
                               drzewostany=m[4] == 'drzewostany', miara=m[5])))
    for f in sorted((KATALOG / 'KDE_zasobnosc').glob('zasobnosc*.png')):
        m = re.fullmatch(r'zasobnosc(?:_(.+?))?_(\d{4})-(\d{4})_prog[\d_]+\.png', f.name)
        wywolania.append(('kde_zasobnosc', 'zasobnosc_mapa',
                          dict(rok_start=int(m[2]), rok_end=int(m[3]), gatunek=m[1])))
    for f in sorted((KATALOG / 'KDE_martwe_drewno').glob('martwe_drewno_*.png')):
        m = re.fullmatch(r'martwe_drewno_(\d{4})-(\d{4})(?:_(lezace|stojace))?_prog[\d_]+\.png', f.name)
        if m:   # dawne warianty _typN (pojedyncze typy) nie są już liczone
            wywolania.append(('kde_martwe_drewno', 'martwe_drewno_mapa',
                              dict(rok_start=int(m[1]), rok_end=int(m[2]), rodzaj=m[3])))
    for f in sorted((KATALOG / 'KDE_przyrost').glob('przyrost_*.png')):
        m = re.fullmatch(r'przyrost_(\d{4})-(\d{4})_prog[\d_.]+\.png', f.name)
        wywolania.append(('kde_przyrost', 'przyrost_mapa',
                          dict(rok_start=int(m[1]), rok_end=int(m[2]))))
    for f in sorted((KATALOG / 'KDE_uzytkowanie').glob('uzytkowanie_*.png')):
        m = re.fullmatch(r'uzytkowanie(?:_(rebne|przedrebne))?_(\d{4})-(\d{4})_prog[\d_.]+\.png', f.name)
        wywolania.append(('kde_uzytkowanie', 'uzytkowanie_mapa',
                          dict(rok_start=int(m[2]), rok_end=int(m[3]), rodzaj=m[1])))
    for f in sorted((KATALOG / 'KDE_intensywnosc').glob('intensywnosc_*.png')):
        m = re.fullmatch(r'intensywnosc_(\d{4})-(\d{4})_prog[\d_.]+\.png', f.name)
        wywolania.append(('kde_intensywnosc', 'intensywnosc_mapa',
                          dict(rok_start=int(m[1]), rok_end=int(m[2]))))
    for f in sorted((KATALOG / 'KDE_zmiany').glob('zmiana_*.png')):
        m = re.fullmatch(r'zmiana_([a-z]+)_(\d{4}-\d{4})_(\d{4}-\d{4})\.png', f.name)
        wywolania.append(('kde_zmiany', 'zmiana_mapa',
                          dict(wskaznik=m[1], okres_od=m[2], okres_do=m[3])))
    for f in sorted((KATALOG / 'KDE_uszkodzenia').glob('udzial_uszkodzonych_*.png')):
        m = re.fullmatch(r'udzial_uszkodzonych_(\d{4})-(\d{4})(.*)\.png', f.name)
        wywolania.append(('kde_uszkodzenia', 'uszkodzenia', _parametry_uszkodzen(m[1], m[2], m[3])))
    for f in sorted((KATALOG / 'KDE_uszkodzenia_ryzyko').glob('ryzyko_*_sparr.png')):
        m = re.fullmatch(r'ryzyko_(\d{4})-(\d{4})(.*)_sparr\.png', f.name)
        wywolania.append(('kde_uszkodzenia_sparr', 'uszkodzenia',
                          _parametry_uszkodzen(m[1], m[2], m[3])))
    return wywolania


def plan():
    """Pełny zestaw + warianty z istniejących PNG, bez powtórzeń, w kolejności
    skryptów (kolejność modułów jak w pełnym zestawie)."""
    lista, widziane = [], set()
    for w in pelny_zestaw() + z_istniejacych_png():
        klucz = (w[0], w[1], tuple(sorted(w[2].items(), key=lambda kv: kv[0])))
        if klucz not in widziane:
            widziane.add(klucz)
            lista.append(w)
    kolejnosc = list(dict.fromkeys(w[0] for w in pelny_zestaw()))
    return sorted(lista, key=lambda w: kolejnosc.index(w[0]) if w[0] in kolejnosc else len(kolejnosc))


def main():
    lista = plan()
    wybrane = [a for a in sys.argv[1:] if not a.startswith('--')]
    if wybrane:
        lista = [w for w in lista if w[0] in wybrane]
    if '--brakujace' in sys.argv:
        lista = [w for w in lista if not list(KATALOG.glob(oczekiwane_png(w[0], w[2])))]
    if '--plan' in sys.argv:
        for modul, funkcja, param in lista:
            print(modul, funkcja, param)
        print(len(lista), 'wywołań')
        return

    import matplotlib
    matplotlib.use('Agg')                 # bez okien - tylko zapis do plików
    import matplotlib.pyplot as plt

    os.chdir(KATALOG)                     # skrypty kde_* zapisują ścieżkami względnymi
    sys.path.insert(0, str(KATALOG))
    # przeliczenie trwa godziny (sparr) - błąd jednej mapy nie przerywa reszty
    bledy = []
    for i, (modul, funkcja, param) in enumerate(lista, 1):
        start = time.time()
        try:
            getattr(importlib.import_module(modul), funkcja)(**param)
            wynik = f'{time.time() - start:.0f} s'
        except Exception:
            traceback.print_exc()
            bledy.append((modul, funkcja, param))
            wynik = 'BŁĄD'
        plt.close('all')
        print(f'[{i}/{len(lista)}] {modul}.{funkcja}({param}) - {wynik}', flush=True)
    for modul, funkcja, param in bledy:
        print('Nieudane:', modul, funkcja, param)
    print(f'Gotowe. Nieudanych: {len(bledy)}.')


if __name__ == '__main__':
    main()
