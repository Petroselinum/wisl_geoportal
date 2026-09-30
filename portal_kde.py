"""
Katalog warstw KDE dla portalu mapowego (1_portal_mapowy_wisl.py).

Zbiera pliki GeoJSON zapisane przez skrypty kde_*.py i przygotowuje je do
wyświetlenia w przeglądarce:

    KDE_gatunki/zasieg_*_epsg4326.geojson        (kde_gat.py)
    KDE_zasobnosc/zasobnosc_*.geojson            (kde_zasobnosc.py)
    KDE_martwe_drewno/martwe_drewno_*.geojson    (kde_martwe_drewno.py)
    KDE_uszkodzenia/udzial_uszkodzonych_*.geojson (kde_uszkodzenia.py)
    KDE_uszkodzenia_ryzyko/istotne_ryzyko_*.geojson (kde_uszkodzenia_sparr.py)

Pliki są wyszukiwane wzorcem, a temat / wariant / okres odczytywany z
atrybutów (nazwy plików zmieniają się np. z listą osiągniętych progów:
zasobnosc_2020-2025_prog200_250_300_350_400). Jedynie pliki sparr nie mają
atrybutów (wynik z R) - dla nich metadane pochodzą z nazwy pliku.

Przygotowanie geometrii:
- skrypty kde_* zapisują progi SKUMULOWANE (poligon ">= 10%" zawiera
  poligon ">= 20%"), tak jak linie konturów na PNG. W przeglądarce nałożenie
  półprzezroczystych poligonów zagnieżdżonych sumowałoby krycie, więc są
  zamieniane na ROZŁĄCZNE pasma (">= 10%" minus ">= 20%" = pasmo 10-20%) -
  dokładnie jak contourf na mapach PNG;
- uproszczenie w EPSG:2180 z tolerancją TOLERANCJA_M (portal ma max_zoom 9,
  ~190 m/piksel, więc 250 m jest na granicy widoczności, a zmniejsza dane
  ~2.5x), potem EPSG:4326 i zaokrąglenie współrzędnych do 4 miejsc (~10 m).

Kolory pasm pochodzą z tych samych słowników co w skryptach kde_*
(KOLORY_PROGOW*), więc portal i mapy PNG mają identyczną legendę.
"""
import glob
import hashlib
import json
import os
import re
import warnings
from pathlib import Path
from urllib.parse import quote

import geopandas as gpd
import shapely
from branca.element import MacroElement
from jinja2 import Template
from matplotlib.colors import to_hex

from Wisl_quert import PRZYCZYNY_USZK
from portal_warstwy import dodaj_styl_paneli
from kde_gat import KOLORY_PROGOW as KOLORY_GAT
from kde_martwe_drewno import KOLORY_PROGOW_M3HA as KOLORY_MARTWE
from kde_uszkodzenia import KOLORY_PROGOW_PROC as KOLORY_USZK
from kde_zasobnosc import (KOLORY_PROGOW_M3HA as KOLORY_ZASOB,
                           KOLORY_PROGOW_GAT_M3HA as KOLORY_ZASOB_GAT)

TOLERANCJA_M = 250
MIEJSCA_DZIESIETNE = 4

# Styl pliku sparr jak na PNG z kde_uszkodzenia_sparr.py
KOLOR_RYZYKA = '#ff7f00'
KRAWEDZ_RYZYKA = '#8b0000'

SLOWNIK_GATUNKOW = {
    'SO': 'sosna zwyczajna',
    'ŚW': 'świerk pospolity',
    'JD': 'jodła pospolita',
    'MD': 'modrzew europejski',
    'DB': 'dąb',
    'BK': 'buk zwyczajny',
    'GB': 'grab pospolity',
    'BRZ': 'brzoza',
    'OL': 'olcha czarna',
    'JS': 'jesion wyniosły',
    'LP': 'lipa drobnolistna',
    'JW': 'klon jawor',
    'CZR': 'czereśnia'}

# Kolejność gatunków w listach wyboru
KOLEJNOSC_GAT = list(SLOWNIK_GATUNKOW)

# Typy martwego drewna (Wisl_quert.martwe_drewno, kolumna TYP)
TYPY_MARTWEGO_DREWNA = {1: 'Leżące (typ 1)', 2: 'Leżące (typ 2)',
                        3: 'Leżące (typ 3)', 4: 'Posusz', 5: 'Złomy'}

TEMATY = {
    'drzewostany': {
        'nazwa': 'Udział drzewostanów z gat. pan.',
        'opis': 'Udział powierzchni drzewostanów z gatunkiem panującym '
                '(GAT_PAN_PR) względem tła lasu, estymator Nadaraya-Watsona.',
    },
    'gatunek': {
        'nazwa': 'Udział gatunku w miąższości',
        'opis': 'Udział miąższości gatunku w miąższości wszystkich drzew '
                'względem tła lasu.',
    },
    'zasobnosc': {
        'nazwa': 'Zasobność drzewostanów',
        'opis': 'Lokalna, wygładzona średnia zasobność drzew żywych '
                '(m³/ha, OBL_ADRES_POW.ZASOBNOSC).',
    },
    'martwe': {
        'nazwa': 'Martwe drewno',
        'opis': 'Lokalna, wygładzona średnia zasobność martwego drewna (m³/ha).',
    },
    'uszkodzenia': {
        'nazwa': 'Uszkodzenia - udział powierzchni',
        'opis': 'Udział powierzchni drzewostanów uszkodzonych (waga WSP_Z) '
                'względem tła lasu.',
    },
    'ryzyko': {
        'nazwa': 'Uszkodzenia - istotne ryzyko (sparr)',
        'opis': 'Obszary istotnie podwyższonego względnego ryzyka uszkodzeń '
                '(p < 0,05). Wynik eksploracyjny - bez korekty na '
                'wielokrotne testowanie.',
    },
}


def _kolory_hex(slownik):
    return {float(k): to_hex(v) for k, v in slownik.items()}


PALETY = {
    'gat': _kolory_hex(KOLORY_GAT),
    'martwe': _kolory_hex(KOLORY_MARTWE),
    'uszk': _kolory_hex(KOLORY_USZK),
    'zasob': _kolory_hex(KOLORY_ZASOB),
    'zasob_gat': _kolory_hex(KOLORY_ZASOB_GAT),
}


def _kolor(paleta, prog, progi):
    """Kolor progu z palety skryptu kde_*; dla progu spoza palety (ręcznie
    podane progi) - kolor wg pozycji na liście progów."""
    kolory = PALETY[paleta]
    if float(prog) in kolory:
        return kolory[float(prog)]
    lista = [kolory[k] for k in sorted(kolory)]
    i = sorted(progi).index(prog)
    return lista[min(round(i * (len(lista) - 1) / max(len(progi) - 1, 1)), len(lista) - 1)]


def _fmt(x, jedn=''):
    tekst = f"{x:.1f}".rstrip('0').rstrip('.').replace('.', ',')
    return f"{tekst}{jedn}"


def _tylko_poligony(geom):
    """Odrzuca linie/punkty powstałe przy różnicy/przecięciu poligonów."""
    if geom is None or geom.is_empty:
        return None
    czesci = [g for g in shapely.get_parts(geom)
              if g.geom_type in ('Polygon', 'MultiPolygon') and not g.is_empty]
    if not czesci:
        return None
    return shapely.union_all(czesci) if len(czesci) > 1 else czesci[0]


def _napraw(g):
    """make_valid z metodą 'structure': poligon = obszar zewnętrzny minus
    dziury. Domyślna metoda 'linework' potrafi przy zdegenerowanym fragmencie
    ("Too few points") źle odtworzyć wąski pierścień i "zasypać" dziurę -
    pasmo 5-10% zamieniało się w cały zasięg progu 5% (sosna 2005-2009)."""
    return shapely.make_valid(g, method='structure', keep_collapsed=False)


def _do_geojson(geomy_2180):
    """Lista geometrii EPSG:2180 (lub None) -> geometrie GeoJSON w EPSG:4326.
    Kontrola: pole po przeliczeniu (z powrotem w 2180) musi się zgadzać
    z polem wejściowym - inaczej ostrzeżenie (błąd naprawy geometrii)."""
    s = gpd.GeoSeries(geomy_2180, crs=2180).to_crs(4326)
    wynik = []
    for wej, g in zip(geomy_2180, s):
        if g is None or g.is_empty:
            wynik.append(None)
            continue
        # set_precision zaokrągla do siatki i od razu naprawia topologię
        # (samo zaokrąglenie współrzędnych potrafi skleić wierzchołki)
        g = _tylko_poligony(_napraw(g))
        try:
            g = shapely.set_precision(g, 10 ** -MIEJSCA_DZIESIETNE)
        except shapely.errors.GEOSException:
            g = shapely.set_precision(g.buffer(0), 10 ** -MIEJSCA_DZIESIETNE)
        g = _tylko_poligony(g)
        if g is not None:
            pole = gpd.GeoSeries([g], crs=4326).to_crs(2180).iloc[0].area
            if abs(pole - wej.area) > max(0.01 * wej.area, 1e6):
                warnings.warn(f'Pole pasma po przeliczeniu do EPSG:4326 {pole / 1e6:,.0f} km2 '
                              f'zamiast {wej.area / 1e6:,.0f} km2', stacklevel=2)
        wynik.append(shapely.geometry.mapping(g) if g is not None else None)
    return wynik


def _pasma(gdf, kolumna_progu):
    """
    Progi skumulowane -> rozłączne pasma. Zwraca listę (prog, geometria
    GeoJSON) posortowaną rosnąco po progu. Pasmo i = poligon(prog_i) minus
    poligon(prog_i+1); ostatnie pasmo to cały poligon najwyższego progu.
    """
    gdf = gdf.sort_values(kolumna_progu).reset_index(drop=True)
    gdf = gdf.to_crs(2180)
    geomy = [shapely.simplify(_napraw(g), TOLERANCJA_M, preserve_topology=True)
             for g in gdf.geometry]
    # Uproszczenie każdego progu osobno może minimalnie wysunąć wyższy próg
    # poza niższy - przycięcie przywraca zagnieżdżenie.
    for i in range(1, len(geomy)):
        geomy[i] = geomy[i].intersection(geomy[i - 1])
    pasma = [_tylko_poligony(g.difference(geomy[i + 1]) if i + 1 < len(geomy) else g)
             for i, g in enumerate(geomy)]
    return list(zip(gdf[kolumna_progu].tolist(), _do_geojson(pasma)))


def _warstwa(pasma, paleta, format_progu, jednostka, info, maks=None):
    """Buduje słownik warstwy: legenda (rosnąco) + FeatureCollection pasm.
    Najwyższe pasmo nie ma progu górnego - etykieta podaje próg i maksimum
    wygładzonej powierzchni ("≥ 25 m³/ha (maks. 34,1)"), tak jak legendy PNG
    skryptów kde_*: klasa zdefiniowana progiem, a widać, gdzie wartości się
    kończą."""
    progi = [p for p, _ in pasma]
    legenda, cechy = [], []
    for i, (prog, geom) in enumerate(pasma):
        if i + 1 < len(progi):
            etykieta = f"{format_progu(prog)}–{format_progu(progi[i + 1])}{jednostka}"
        else:
            etykieta = f"≥ {format_progu(prog)}{jednostka}"
            if maks is not None:
                etykieta += f" (maks. {format_progu(maks)}{'%' if jednostka == '%' else ''})"
        legenda.append({'kolor': _kolor(paleta, prog, progi), 'etykieta': etykieta})
        if geom is not None:
            cechy.append({'type': 'Feature', 'properties': {'b': i}, 'geometry': geom})
    return {'legenda': legenda, 'info': info,
            'geojson': {'type': 'FeatureCollection', 'features': cechy}}


def _okres(row):
    return f"{int(row['rok_start'])}-{int(row['rok_end'])}"


def _nazwa_gat(kod):
    return f"{SLOWNIK_GATUNKOW.get(kod, kod)} ({kod})"


def _klucz_gat(kod):
    return KOLEJNOSC_GAT.index(kod) if kod in KOLEJNOSC_GAT else len(KOLEJNOSC_GAT)


def _opis_nasilenia(prog):
    return f"nasilenie ≥ {int(prog) * 10}%" if prog else None


def _opis_uszk(gatunek, nasil, przycz_nazwa):
    czesci = [przycz_nazwa or 'Wszystkie przyczyny']
    if gatunek and gatunek != 'Wszystkie':
        czesci.append(_nazwa_gat(gatunek))
    if nasil:
        czesci.append(_opis_nasilenia(nasil))
    return ' | '.join(czesci)


# ---------------------------------------------------------------------------
# Czytniki poszczególnych tematów. Każdy zwraca listę krotek
# (temat, id_wariantu, nazwa_wariantu, klucz_sortowania, okres, warstwa).
# ---------------------------------------------------------------------------

def _czytaj_gatunki(plik):
    g = gpd.read_file(plik)
    r = g.iloc[0]
    temat = 'drzewostany' if r['typ_zasiegu'] == 'drzewostany' else 'gatunek'
    info = [f"Udział krajowy: {_fmt(r['udzial_krajowy'] * 100, '%')}",
            f"Maks. lokalny udział: {_fmt(r['max_udzialu'] * 100, '%')}",
            f"Trakty: {int(r['n_traktow'])} (z gatunkiem: {int(r['n_traktow_gat'])})"]
    warstwa = _warstwa(_pasma(g, 'prog_udzialu'), 'gat',
                       lambda p: _fmt(p * 100), '%', info, maks=r['max_udzialu'])
    return [(temat, r['gatunek'], _nazwa_gat(r['gatunek']), (_klucz_gat(r['gatunek']),),
             _okres(r), warstwa)]


def _czytaj_zasobnosc(plik):
    g = gpd.read_file(plik)
    r = g.iloc[0]
    gat = r['gatunek'] if isinstance(r['gatunek'], str) and r['gatunek'] else None
    info = [f"Średnia krajowa: {_fmt(r['srednia_krajowa_m3ha'], ' m³/ha')}",
            f"Maks. lokalna: {_fmt(r['max_zasobnosci_m3ha'], ' m³/ha')}",
            f"Trakty: {int(r['n_traktow'])}"]
    warstwa = _warstwa(_pasma(g, 'prog_zasobnosci_m3ha'), 'zasob_gat' if gat else 'zasob',
                       _fmt, ' m³/ha', info, maks=r['max_zasobnosci_m3ha'])
    if gat:
        return [('zasobnosc', gat, _nazwa_gat(gat), (1, _klucz_gat(gat)), _okres(r), warstwa)]
    return [('zasobnosc', 'ogolem', 'Wszystkie gatunki', (0,), _okres(r), warstwa)]


def _czytaj_martwe(plik):
    g = gpd.read_file(plik)
    r = g.iloc[0]
    typ = r['typ_martwego_drewna']
    try:
        typ = int(typ)
    except (TypeError, ValueError):
        typ = None
    info = [f"Średnia krajowa: {_fmt(r['srednia_krajowa_m3ha'], ' m³/ha')}",
            f"Maks. lokalna: {_fmt(r['max_zasobnosci_m3ha'], ' m³/ha')}",
            f"Trakty: {int(r['n_traktow'])}"]
    warstwa = _warstwa(_pasma(g, 'prog_zasobnosci_m3ha'), 'martwe', _fmt, ' m³/ha', info,
                       maks=r['max_zasobnosci_m3ha'])
    if typ is None:
        return [('martwe', 'wszystkie', 'Wszystkie typy', (0,), _okres(r), warstwa)]
    return [('martwe', f"typ{typ}", TYPY_MARTWEGO_DREWNA.get(typ, f"Typ {typ}"),
             (1, typ), _okres(r), warstwa)]


def _czytaj_uszkodzenia(plik):
    g = gpd.read_file(plik)
    r = g.iloc[0]
    gat = r.get('gatunek') or 'Wszystkie'
    nasil = int(r.get('prog_nasilenia') or 0)
    przycz_nazwa = r.get('przyczyna_uszk')
    if przycz_nazwa == 'Wszystkie':
        przycz_nazwa = None
    # kod przyczyny tylko do sortowania - z nazwy pliku
    m = re.search(r'_przycz(\d+)', os.path.basename(plik))
    przycz = int(m.group(1)) if m else 0
    info = [f"Udział krajowy: {_fmt(r['udzial_krajowy_proc'], '%')}",
            f"Maks. lokalny udział: {_fmt(r['max_udzialu_proc'], '%')}",
            f"Trakty: {int(r['liczba_traktow'])}"]
    warstwa = _warstwa(_pasma(g, 'prog_udzialu_proc'), 'uszk', _fmt, '%', info,
                       maks=r['max_udzialu_proc'])
    id_war = f"{gat}|{nasil}|{przycz}"
    return [('uszkodzenia', id_war, _opis_uszk(gat, nasil, przycz_nazwa),
             (przycz, gat != 'Wszystkie', _klucz_gat(gat), nasil), _okres(r), warstwa)]


WZORZEC_SPARR = re.compile(r'istotne_ryzyko_(\d{4})-(\d{4})(.*)\.geojson$')


def _czytaj_ryzyko(plik):
    m = WZORZEC_SPARR.search(os.path.basename(plik))
    if not m:
        return []
    okres = f"{m.group(1)}-{m.group(2)}"
    # Sufiksy jak w kde_uszkodzenia_sparr.py: _{gatunek}_nasil{N}_przycz{N}
    gat, nasil, przycz = 'Wszystkie', 0, 0
    for token in filter(None, m.group(3).split('_')):
        if token.startswith('nasil') and token[5:].isdigit():
            nasil = int(token[5:])
        elif token.startswith('przycz') and token[6:].isdigit():
            przycz = int(token[6:])
        else:
            gat = token
    g = gpd.read_file(plik)
    if g.crs is None:
        g = g.set_crs(2180)
    geom = shapely.union_all(_napraw(g.to_crs(2180).geometry.values))
    geom = _tylko_poligony(shapely.simplify(_napraw(geom), TOLERANCJA_M,
                                            preserve_topology=True))
    geojson = _do_geojson([geom])[0]
    warstwa = {
        'legenda': [{'kolor': KOLOR_RYZYKA, 'krawedz': KRAWEDZ_RYZYKA,
                     'etykieta': 'istotne ryzyko (p < 0,05)'}],
        'info': [] if geojson else ['Brak obszarów istotnie podwyższonego ryzyka.'],
        'geojson': {'type': 'FeatureCollection', 'features':
                    [{'type': 'Feature', 'properties': {'b': 0}, 'geometry': geojson}]
                    if geojson else []},
    }
    przycz_nazwa = PRZYCZYNY_USZK.get(przycz) if przycz else None
    id_war = f"{gat}|{nasil}|{przycz}"
    return [('ryzyko', id_war, _opis_uszk(gat, nasil, przycz_nazwa),
             (przycz, gat != 'Wszystkie', _klucz_gat(gat), nasil), okres, warstwa)]


ZRODLA = [
    ('KDE_gatunki/zasieg_*_epsg4326.geojson', _czytaj_gatunki),
    ('KDE_zasobnosc/zasobnosc_*.geojson', _czytaj_zasobnosc),
    ('KDE_martwe_drewno/martwe_drewno_*.geojson', _czytaj_martwe),
    ('KDE_uszkodzenia/udzial_uszkodzonych_*.geojson', _czytaj_uszkodzenia),
    ('KDE_uszkodzenia_ryzyko/istotne_ryzyko_*.geojson', _czytaj_ryzyko),
]


def plik_png(plik_geojson):
    """
    Mapa PNG zapisana przez skrypt kde_* razem z danym GeoJSON-em (albo None):
      KDE_gatunki/zasieg_X_epsg4326.geojson -> KDE_gatunki/mapa_X.png
      KDE_uszkodzenia_ryzyko/istotne_ryzyko_X.geojson
                                             -> KDE_uszkodzenia_ryzyko/ryzyko_X_sparr.png
      pozostałe katalogi: ta sama nazwa, rozszerzenie .png
    """
    katalog, nazwa = os.path.split(plik_geojson)
    rdzen = nazwa[:-len('.geojson')]
    if rdzen.startswith('zasieg_') and rdzen.endswith('_epsg4326'):
        rdzen = 'mapa_' + rdzen[len('zasieg_'):-len('_epsg4326')]
    elif rdzen.startswith('istotne_ryzyko_'):
        rdzen = rdzen[len('istotne_'):] + '_sparr'
    png = os.path.join(katalog, rdzen + '.png')
    return png if os.path.exists(png) else None


def zbuduj_katalog(katalog_bazowy='.'):
    """
    Zwraca słownik gotowy do zapisania jako JSON:
    {
      'tematy': [{'id', 'nazwa', 'opis',
                  'warianty': [{'id', 'nazwa', 'okresy': {okres: id_warstwy}}]}],
      'warstwy': {id_warstwy: {'legenda', 'info', 'geojson', ['png']}}
    }
    'png' - {'plik', 'rozmiar'}: mapa PNG z tego samego przeliczenia (plik_png),
    o ile istnieje.
    Gdy dla tego samego (temat, wariant, okres) istnieje kilka plików (np.
    przeliczenie z innymi progami zmieniło sufiks _prog...), wygrywa
    najnowszy.
    """
    warnings.filterwarnings('ignore', category=RuntimeWarning)
    wpisy = {}
    for wzorzec, czytnik in ZRODLA:
        for plik in glob.glob(os.path.join(katalog_bazowy, wzorzec)):
            mtime = os.path.getmtime(plik)
            for temat, id_war, nazwa, klucz, okres, warstwa in czytnik(plik):
                k = (temat, id_war, okres)
                if k not in wpisy or wpisy[k]['mtime'] < mtime:
                    wpisy[k] = {'mtime': mtime, 'nazwa': nazwa, 'klucz': klucz,
                                'warstwa': warstwa, 'plik': plik}

    tematy, warstwy = [], {}
    for id_tematu, opis in TEMATY.items():
        warianty = {}
        for (temat, id_war, okres), w in wpisy.items():
            if temat != id_tematu:
                continue
            war = warianty.setdefault(id_war, {'id': id_war, 'nazwa': w['nazwa'],
                                               'klucz': w['klucz'], 'okresy': {}})
            id_warstwy = f"{temat}|{id_war}|{okres}"
            war['okresy'][okres] = id_warstwy
            warstwy[id_warstwy] = w['warstwa']
            png = plik_png(w['plik'])
            if png:
                warstwy[id_warstwy]['png'] = {'plik': png, 'rozmiar': os.path.getsize(png)}
        if not warianty:
            continue
        lista = sorted(warianty.values(), key=lambda w: (w['klucz'], w['nazwa']))
        for w in lista:
            w.pop('klucz')
            w['okresy'] = dict(sorted(w['okresy'].items()))
        tematy.append({'id': id_tematu, **opis, 'warianty': lista})
    return {'tematy': tematy, 'warstwy': warstwy}


# ---------------------------------------------------------------------------
# Panel w portalu folium
# ---------------------------------------------------------------------------
# Ok. 220 warstw nie mieści się sensownie w LayerControl, więc wybór jest w
# osobnym panelu: Temat -> Wariant -> Okres (przyciski, żeby łatwo porównywać
# cykle). Dane leżą w osobnym pliku kde_warstwy.js obok HTML, a L.geoJSON
# tworzony jest dopiero przy pierwszym wyborze warstwy (i zapamiętywany).
# Warstwy KDE rysowane są w osobnym panelu Leaflet (z-index 450) - nad
# warstwami administracyjnymi i kartogramami RDLP (overlayPane, 400).
# Panel stoi w prawym górnym rogu pod panelem "Warstwy" (portal_warstwy.py),
# z którym dzieli styl (StylPaneli).

PLIK_DANYCH_JS = 'kde_warstwy.js'


class PanelKDE(MacroElement):
    _template = Template("""
{% macro header(this, kwargs) %}
<script src="{{ this.plik_js }}" charset="utf-8"></script>
{% endmacro %}

{% macro script(this, kwargs) %}
(function() {
    var map = {{ this._parent.get_name() }};
    var K = window.KDE_WARSTWY;
    if (!K) { console.warn('Brak danych KDE ({{ this.plik_js }})'); return; }

    map.createPane('kde');
    map.getPane('kde').style.zIndex = 450;

    var tematy = {};
    K.tematy.forEach(function(t) { tematy[t.id] = t; });
    var wszystkieOkresy = [];
    K.tematy.forEach(function(t) { t.warianty.forEach(function(w) {
        Object.keys(w.okresy).forEach(function(o) {
            if (wszystkieOkresy.indexOf(o) < 0) wszystkieOkresy.push(o);
        });
    }); });
    wszystkieOkresy.sort();

    var stan = { temat: '', wariant: null, okres: null, krycie: 0.65 };
    var cache = {}, aktywna = null;

    var panel = L.control({ position: 'topright' });
    panel.onAdd = function() {
        var d = L.DomUtil.create('div', 'panel-wisl');
        var opcje = '<option value="">— wyłączone —</option>' + K.tematy.map(function(t) {
            return '<option value="' + t.id + '">' + t.nazwa + '</option>';
        }).join('');
        d.innerHTML =
            '<div class="panel-naglowek"><h4>Analizy KDE</h4><span class="zwin" title="Zwiń / rozwiń">▾</span></div>' +
            '<div class="panel-tresc">' +
            '<label class="pole" for="kde-temat">Temat</label><select id="kde-temat">' + opcje + '</select>' +
            '<div id="kde-wybor" style="display:none">' +
            '<label class="pole" for="kde-wariant">Wariant</label><select id="kde-wariant"></select>' +
            '<label class="pole">Cykl WISL</label><div class="panel-okresy" id="kde-okresy">' +
            wszystkieOkresy.map(function(o) {
                return '<button type="button" data-okres="' + o + '">' + o + '</button>';
            }).join('') + '</div>' +
            '<div class="panel-krycie"><span>Krycie</span>' +
            '<input type="range" id="kde-krycie" min="0.1" max="1" step="0.05" value="' + stan.krycie + '"></div>' +
            '<div class="panel-legenda" id="kde-legenda"></div>' +
            '<div class="panel-info" id="kde-info"></div>' +
            '<div class="panel-opis" id="kde-opis"></div>' +
            '<a class="panel-pobierz" id="kde-png" style="display:none" ' +
            'title="Mapa PNG (300 dpi) z tego samego przeliczenia skryptem kde_*"></a>' +
            '</div></div>';
        L.DomEvent.disableClickPropagation(d);
        L.DomEvent.disableScrollPropagation(d);
        return d;
    };
    panel.addTo(map);
    var kontener = panel.getContainer();

    var el = function(id) { return document.getElementById(id); };

    function wariant() {
        var t = tematy[stan.temat];
        return t ? t.warianty.filter(function(w) { return w.id === stan.wariant; })[0] : null;
    }

    function zbuduj(idWarstwy) {
        if (cache[idWarstwy]) return cache[idWarstwy];
        var dane = K.warstwy[idWarstwy], leg = dane.legenda;
        var nazwaTematu = tematy[stan.temat].nazwa;
        cache[idWarstwy] = L.geoJSON(dane.geojson, {
            pane: 'kde',
            style: function(f) {
                var p = leg[f.properties.b];
                return { fillColor: p.kolor, color: p.krawedz || p.kolor,
                         weight: p.krawedz ? 1.2 : 0.5, opacity: 0.9,
                         fillOpacity: stan.krycie };
            },
            onEachFeature: function(f, warstwa) {
                warstwa.bindTooltip(nazwaTematu + ': <b>' + leg[f.properties.b].etykieta + '</b>',
                                    { sticky: true });
            }
        });
        return cache[idWarstwy];
    }

    function rysuj() {
        if (aktywna) { map.removeLayer(aktywna); aktywna = null; }
        var w = wariant();
        var idWarstwy = w && w.okresy[stan.okres];
        el('kde-legenda').innerHTML = '';
        el('kde-info').innerHTML = '';
        el('kde-opis').innerHTML = stan.temat ? tematy[stan.temat].opis : '';
        el('kde-png').style.display = 'none';
        if (!idWarstwy) return;
        // warstwa z pamięci podręcznej ma krycie z chwili, gdy była ostatnio
        // widoczna - ustawić bieżące z suwaka
        aktywna = zbuduj(idWarstwy).addTo(map);
        aktywna.setStyle({ fillOpacity: stan.krycie });
        var dane = K.warstwy[idWarstwy];
        // legenda: najwyższe pasmo na górze, jak na mapach PNG
        el('kde-legenda').innerHTML = dane.legenda.slice().reverse().map(function(p) {
            return '<div class="poz"><span class="kolor" style="background:' + p.kolor +
                   (p.krawedz ? ';border-color:' + p.krawedz : '') + '"></span>' + p.etykieta + '</div>';
        }).join('');
        el('kde-info').innerHTML = dane.info.join('<br>');
        // mapa PNG oglądanej warstwy do pobrania
        if (dane.png) {
            var a = el('kde-png');
            a.href = dane.png.url;
            a.setAttribute('download', dane.png.nazwa);
            a.textContent = '⬇ Pobierz mapę PNG (' + (dane.png.rozmiar / 1048576).toLocaleString('pl-PL',
                { maximumFractionDigits: 1 }) + ' MB)';
            a.style.display = '';
        }
    }

    function ustawOkresy() {
        var w = wariant(), dostepne = w ? Object.keys(w.okresy) : [];
        if (dostepne.indexOf(stan.okres) < 0) stan.okres = dostepne[dostepne.length - 1] || null;
        el('kde-okresy').querySelectorAll('button').forEach(function(b) {
            var o = b.getAttribute('data-okres');
            b.disabled = dostepne.indexOf(o) < 0;
            b.classList.toggle('aktywny', o === stan.okres);
        });
    }

    function ustawTemat(id) {
        stan.temat = id;
        el('kde-wybor').style.display = id ? '' : 'none';
        if (!id) { rysuj(); return; }
        var t = tematy[id];
        // ten sam wariant (np. gatunek) przy zmianie tematu, jeśli istnieje
        if (!t.warianty.some(function(w) { return w.id === stan.wariant; }))
            stan.wariant = t.warianty[0].id;
        el('kde-wariant').innerHTML = t.warianty.map(function(w) {
            return '<option value="' + w.id + '">' + w.nazwa + '</option>';
        }).join('');
        el('kde-wariant').value = stan.wariant;
        ustawOkresy();
        rysuj();
    }

    el('kde-temat').addEventListener('change', function() { ustawTemat(this.value); });
    el('kde-wariant').addEventListener('change', function() {
        stan.wariant = this.value; ustawOkresy(); rysuj();
    });
    el('kde-okresy').addEventListener('click', function(e) {
        var b = e.target.closest('button');
        if (!b || b.disabled) return;
        stan.okres = b.getAttribute('data-okres'); ustawOkresy(); rysuj();
    });
    el('kde-krycie').addEventListener('input', function() {
        stan.krycie = parseFloat(this.value);
        if (aktywna) aktywna.setStyle({ fillOpacity: stan.krycie });
    });
    kontener.querySelector('.panel-naglowek').addEventListener('click', function() {
        kontener.classList.toggle('zwiniety');
        kontener.querySelector('.zwin').textContent = kontener.classList.contains('zwiniety') ? '▸' : '▾';
    });
})();
{% endmacro %}
""")

    def __init__(self, plik_js=PLIK_DANYCH_JS):
        super().__init__()
        self._name = 'PanelKDE'
        self.plik_js = plik_js


def dodaj_panel_kde(mapa, katalog_wyjsciowy):
    """
    Buduje katalog warstw KDE, zapisuje go jako kde_warstwy.js w katalogu,
    do którego trafi HTML portalu, i dodaje do mapy panel wyboru warstw.
    Dodawać PO panelu "Warstwy" - w rogu panele układają się w kolejności.
    """
    dodaj_styl_paneli(mapa)
    katalog = zbuduj_katalog()
    # mapy PNG nie są kopiowane (~500 MB) - odnośnik względny z katalogu HTML-a
    # (serwer udostępnia katalog projektu, np. ../KDE_gatunki/mapa_...png)
    for warstwa in katalog['warstwy'].values():
        if 'png' in warstwa:
            png = warstwa['png'].pop('plik')
            warstwa['png']['url'] = quote(Path(os.path.relpath(png, katalog_wyjsciowy)).as_posix())
            warstwa['png']['nazwa'] = os.path.basename(png)
    plik = Path(katalog_wyjsciowy) / PLIK_DANYCH_JS
    plik.parent.mkdir(parents=True, exist_ok=True)
    tresc = ('window.KDE_WARSTWY = '
             + json.dumps(katalog, ensure_ascii=False, separators=(',', ':')) + ';\n')
    plik.write_text(tresc, encoding='utf-8')
    # wersja w adresie (skrót treści): przeglądarka nie użyje starej kopii
    # z pamięci podręcznej po przebudowie danych
    wersja = hashlib.md5(tresc.encode('utf-8')).hexdigest()[:10]
    PanelKDE(plik_js=f'{PLIK_DANYCH_JS}?v={wersja}').add_to(mapa)
    return katalog
