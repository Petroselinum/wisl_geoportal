"""
Ponowne wygenerowanie ISTNIEJĄCYCH map KDE (PNG + GeoJSON) skryptów kde_*.

Parametry wywołań są odczytywane z nazw plików PNG w katalogach wyników, więc
skrypt odtwarza dokładnie ten sam zestaw map co obecny - niezależnie od
pętli w blokach __main__ poszczególnych skryptów (np. kde_uszkodzenia.py
liczy tam tylko warianty z przyczynami). Przydatne po zmianie wyglądu map
(np. legendy), gdy trzeba przeliczyć wszystko jeszcze raz.

    KDE_gatunki/mapa_{GAT}_{okres}_{drzewostany|gatunek}_{miara}.png
                                          -> kde_gat.plot_kde_for_species
    KDE_zasobnosc/zasobnosc[_GAT]_{okres}_prog....png
                                          -> kde_zasobnosc.zasobnosc_mapa
    KDE_martwe_drewno/martwe_drewno_{okres}[_typN]_prog....png
                                          -> kde_martwe_drewno.martwe_drewno_mapa
    KDE_uszkodzenia/udzial_uszkodzonych_{okres}[_GAT][_nasilN][_przyczN].png
                                          -> kde_uszkodzenia.uszkodzenia
    KDE_uszkodzenia_ryzyko/ryzyko_{okres}[_GAT][_nasilN][_przyczN]_sparr.png
                                          -> kde_uszkodzenia_sparr.uszkodzenia (R, sparr)

Uwaga: jeśli po przeliczeniu zmieni się lista osiągniętych progów, zmieni się
też sufiks _prog... w nazwie pliku - wtedy stary plik zostaje obok nowego
(portal bierze najnowszy).

Uruchomienie (z działającą bazą i WISL_DB_PASSWORD w środowisku):
    python regeneruj_mapy_kde.py                         - przelicz wszystkie mapy
    python regeneruj_mapy_kde.py kde_uszkodzenia_sparr   - tylko wybrane skrypty
    python regeneruj_mapy_kde.py --plan [skrypty...]     - tylko wypisz wywołania (bez bazy)
"""
import importlib
import os
import re
import sys
from pathlib import Path

KATALOG = Path(__file__).resolve().parent


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


def plan():
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
        m = re.fullmatch(r'martwe_drewno_(\d{4})-(\d{4})(?:_typ(\d+))?_prog[\d_]+\.png', f.name)
        wywolania.append(('kde_martwe_drewno', 'martwe_drewno_mapa',
                          dict(rok_start=int(m[1]), rok_end=int(m[2]),
                               typ=int(m[3]) if m[3] else None)))
    for f in sorted((KATALOG / 'KDE_uszkodzenia').glob('udzial_uszkodzonych_*.png')):
        m = re.fullmatch(r'udzial_uszkodzonych_(\d{4})-(\d{4})(.*)\.png', f.name)
        wywolania.append(('kde_uszkodzenia', 'uszkodzenia', _parametry_uszkodzen(m[1], m[2], m[3])))
    for f in sorted((KATALOG / 'KDE_uszkodzenia_ryzyko').glob('ryzyko_*_sparr.png')):
        m = re.fullmatch(r'ryzyko_(\d{4})-(\d{4})(.*)_sparr\.png', f.name)
        wywolania.append(('kde_uszkodzenia_sparr', 'uszkodzenia',
                          _parametry_uszkodzen(m[1], m[2], m[3])))
    return wywolania


def main():
    lista = plan()
    wybrane = [a for a in sys.argv[1:] if not a.startswith('--')]
    if wybrane:
        lista = [w for w in lista if w[0] in wybrane]
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
    for i, (modul, funkcja, param) in enumerate(lista, 1):
        getattr(importlib.import_module(modul), funkcja)(**param)
        plt.close('all')
        print(f'[{i}/{len(lista)}] {modul}.{funkcja}({param})', flush=True)
    print('Gotowe.')


if __name__ == '__main__':
    main()
