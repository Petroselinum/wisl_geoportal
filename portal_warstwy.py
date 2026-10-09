"""
Panele portalu mapowego (1_portal_mapowy_wisl.py) w prawym górnym rogu:

- "Warstwy" (PanelWarstw): podkład i granice;
- "Wyniki WISL" (też PanelWarstw, osobny panel pod "Warstwy") - kartogram
  wskaźnika z przełączaniem podziału (RDLP - lasy w zarządzie PGL LP /
  województwa / krainy przyrodniczo-leśne - lasy wszystkich form własności)
  i cykli WISL;
- "Analizy KDE" (portal_kde.PanelKDE) - pod nimi, w tym samym stylu.

Wspólny wygląd paneli: StylPaneli (dodawany raz, przez dodaj_styl_paneli).

Kartogramy są rysowane w przeglądarce z JEDNEJ warstwy granic danego typu
jednostek i tabeli wyników - wcześniej każdy wskaźnik RDLP był osobną kopią
rdlp.geojson w HTML.

Kliknięcie RDLP, krainy przyrodniczo-leśnej albo województwa otwiera popup
z wynikami WISL (cykl do wyboru w popupie) i wykresem zasobności w kolejnych
raportach 5-letnich. RDLP - lasy w zarządzie PGL LP (data.WISL_RDLP),
krainy i województwa - lasy wszystkich form własności (data.WISL_KRAINY,
data.WISL_WOJEWODZTWA).

Klasy kolorów każdego wskaźnika są WSPÓLNE dla wszystkich cykli (zakres
z wartości wszystkich cykli, osobno dla każdego typu jednostek), żeby zmiana
koloru między cyklami oznaczała zmianę wartości - ta sama zasada co stałe progi w skryptach kde_*.
"""
import json
import math

import altair as alt
from branca.element import MacroElement
from jinja2 import Template
from matplotlib import colormaps
from matplotlib.colors import to_hex

from data import (RDLP, WISL_RDLP, zasob_time_rdlp,
                  KRAINY, WISL_KRAINY, ZASOBNOSC_OKNA_KRAINY,
                  WOJEWODZTWA, WISL_WOJEWODZTWA, ZASOBNOSC_OKNA_WOJEWODZTWA,
                  MARTWE_OKNA, PRZYROST_OKNA, UZYTKOWANIE_OKNA)

# Wskaźniki kartogramów i popupów; klucze jak w data.WISL_RDLP / WISL_KRAINY /
# WISL_WOJEWODZTWA. Opis bez zakresu własności - panel dopisuje go z danych
# jednostki (PGL LP albo wszystkie formy własności).
WSKAZNIKI = [
    {'id': 'powierzchnia', 'nazwa': 'Powierzchnia lasów', 'jednostka': 'tys. ha',
     'opis': 'Powierzchnia lasów.', 'paleta': 'Greens'},
    {'id': 'miazszosc', 'nazwa': 'Miąższość', 'jednostka': 'mln m³',
     'opis': 'Miąższość grubizny brutto.', 'paleta': 'YlGn'},
    {'id': 'zasobnosc', 'nazwa': 'Zasobność', 'jednostka': 'm³/ha',
     'opis': 'Przeciętna zasobność grubizny brutto.', 'paleta': 'YlGn'},
    # raporty podają przyrost z dokładnością 0,01; od II cyklu (I cykl to
    # pierwszy pomiar - bez przyrostu)
    {'id': 'przyrost', 'nazwa': 'Przyrost', 'jednostka': 'm³/ha/rok',
     'opis': 'Bieżący roczny przyrost miąższości grubizny brutto (z 5-letniego '
             'okresu), na 1 ha powierzchni z początku okresu.',
     'paleta': 'BuGn', 'miejsca': 2},
    {'id': 'wiek', 'nazwa': 'Średni wiek', 'jednostka': 'lat',
     'opis': 'Przeciętny wiek drzewostanów.', 'paleta': 'PuBu'},
    {'id': 'martwe', 'nazwa': 'Martwe drewno', 'jednostka': 'm³/ha',
     'opis': 'Przeciętna miąższość martwego drewna (stojącego i leżącego).',
     'paleta': 'YlOrBr'},
    # z data.UZYTKOWANIE_OKNA (tab. 105a.x) - okna 2015-2019 i 2020-2024 to
    # te same lata co cykle III i IV; raport 2010-2014 podaje użytkowanie
    # tylko wg form własności, wcześniejsze wcale
    {'id': 'uzytkowanie', 'nazwa': 'Użytkowanie', 'jednostka': 'm³/ha',
     'opis': 'Użytkowanie rębne i przedrębne grubizny w okresie 5-letnim (suma '
             'z 5 lat, nie wartość roczna), na 1 ha powierzchni z początku okresu.',
     'paleta': 'PuRd'},
]


def _progi_klas(wartosci, min_klas=5):
    """
    Równe przedziały o "okrągłym" kroku (1/2/2,5/5 x 10^k): największy krok,
    przy którym zakres wartości dzieli się na co najmniej min_klas klas.
    """
    lo, hi = min(wartosci), max(wartosci)
    if hi == lo:
        return [lo, lo + 1]
    kroki = sorted(m * 10 ** k for k in range(-3, 7) for m in (1, 2, 2.5, 5))
    for krok in reversed(kroki):
        start = math.floor(lo / krok) * krok
        n = math.floor((hi - start) / krok) + 1
        if n >= min_klas:
            break
    return [round(start + i * krok, 6) for i in range(n + 1)]


def _klasy(wyniki):
    """
    Klasy kolorów wskaźników dla jednego typu jednostek (RDLP, województwa,
    krainy): {wskaznik: {progi, kolory}}, wspólne dla wszystkich cykli.
    Każdy typ ma własne klasy - np. powierzchnia krainy sięga 2,4 mln ha.
    """
    klasy = {}
    for w in WSKAZNIKI:
        wartosci = [v for okres in wyniki.values()
                    for v in (okres.get(w['id']) or []) if v is not None]
        if not wartosci:
            continue
        progi = _progi_klas(wartosci)
        n = len(progi) - 1
        cmap = colormaps[w['paleta']]
        klasy[w['id']] = {'progi': progi,
                          'kolory': [to_hex(cmap(0.2 + 0.75 * i / max(n - 1, 1)))
                                     for i in range(n)]}
    return klasy


def _z_uzytkowaniem(wyniki, okna):
    """Kopia wyników cykli (data.WISL_*) z dopisanym użytkowaniem z okien
    5-letnich (data.UZYTKOWANIE_OKNA[...]) o tych samych latach co cykl."""
    return {okres: ({**dane, 'uzytkowanie': okna[okres]} if okres in okna else dane)
            for okres, dane in wyniki.items()}


def _tabela_wynikow(wyniki, nazwy):
    """{okres: {'zrodlo', 'ogolem', 'dane': {jednostka: {wskaznik: wartosc}}}}"""
    tabela = {}
    for okres, dane in sorted(wyniki.items()):
        jednostki = {nazwa: {} for nazwa in nazwy}
        for w in WSKAZNIKI:
            for nazwa, v in zip(nazwy, dane.get(w['id']) or []):
                if v is not None:
                    jednostki[nazwa][w['id']] = v
        tabela[okres] = {'zrodlo': dane.get('zrodlo', ''),
                         'ogolem': dane.get('ogolem', {}), 'dane': jednostki}
    return tabela


# Wykresy w popupie (przełączane przyciskami, jeden naraz); serie z raportów
# okien 5-letnich (data.py: zasob_time_rdlp / ZASOBNOSC_OKNA_*, MARTWE_OKNA,
# PRZYROST_OKNA, UZYTKOWANIE_OKNA).
WYKRESY = [
    {'id': 'zasobnosc', 'przycisk': 'Zasobność',
     'tytul': 'Zasobność grubizny brutto', 'os': 'Zasobność [m³/ha]'},
    {'id': 'martwe', 'przycisk': 'Martwe drewno',
     'tytul': 'Martwe drewno stojące i leżące', 'os': 'Martwe drewno [m³/ha]'},
    {'id': 'przyrost', 'przycisk': 'Przyrost',
     'tytul': 'Bieżący roczny przyrost miąższości', 'os': 'Przyrost [m³/ha/rok]'},
    {'id': 'uzytkowanie', 'przycisk': 'Użytkowanie',
     'tytul': 'Użytkowanie rębne i przedrębne w okresie 5-letnim', 'os': 'Użytkowanie [m³/ha]'},
]


def szablon_wykresu(tytul, os_y):
    """Wykres liniowy Vega-Lite bez danych - popup wstawia serię jednostki jako
    zbiór 'wartosci' (lata: '2005 - 2009', wartosc)."""
    return alt.Chart(alt.NamedData('wartosci')).mark_line(point=True).encode(
        x=alt.X('lata:O', title='Okres',
                axis=alt.Axis(labelAngle=-45, labelOverlap=False)),
        y=alt.Y('wartosc:Q', title=os_y, scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip('lata:O', title='Okres'), alt.Tooltip('wartosc:Q', title=os_y)]
    ).properties(
        title=tytul,
        width=300,
        height=170
    ).to_dict()


def _serie(zrodla, nazwy):
    """{miara: {okno: [wartości w kolejności nazw]}} -> {miara: {'okna': [...],
    'dane': {nazwa: [wartości w kolejności okien]}}}"""
    wynik = {}
    for miara, okna in zrodla.items():
        lista = sorted(okna)
        wynik[miara] = {'okna': lista,
                        'dane': {n: [okna[o][i] for o in lista] for i, n in enumerate(nazwy)}}
    return wynik


def _zasobnosc_rdlp():
    """zasob_time_rdlp() (lata '2005 - 2009') -> {okno: [wartości w kolejności RDLP]}."""
    df = zasob_time_rdlp()
    return {lata.replace(' - ', '-'): [float(g.set_index('rdlp').loc[n, 'zasobnosc']) for n in RDLP]
            for lata, g in df.groupby('lata')}


STYL_PANELI = """
<style>
/* Panele w prawym górnym rogu - róg przewija się, gdy oba panele
   rozwinięte nie mieszczą się w oknie. */
.leaflet-top.leaflet-right {
    max-height: 100%;
    overflow-y: auto;
    overflow-x: hidden;
    padding-left: 8px;
    padding-bottom: 10px;
    scrollbar-width: thin;
}
.panel-wisl {
    background: white;
    padding: 8px 10px;
    width: 270px;
    font: 12px/1.35 "Helvetica Neue", Arial, sans-serif;
    border-radius: 6px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.35);
}
.panel-wisl h4 { margin: 0; font-size: 14px; font-weight: bold; }
/* bez ramki fokusu przeglądarki na klikniętym poligonie */
path.leaflet-interactive:focus { outline: none; }
.panel-naglowek { display: flex; justify-content: space-between; align-items: center;
                  cursor: pointer; user-select: none; }
.panel-naglowek .zwin { font-size: 13px; color: #555; }
.panel-wisl.zwiniety .panel-tresc { display: none; }
.panel-tresc { margin-top: 4px; }
.panel-wisl label.pole { display: block; margin: 6px 0 2px; font-weight: bold; }
.panel-wisl select { width: 100%; font-size: 12px; }
.panel-sekcja { margin: 8px 0 3px; padding-top: 6px; border-top: 1px solid #e3e3e3;
                font-weight: bold; color: #333; }
.panel-sekcja:first-child { border-top: none; padding-top: 0; margin-top: 4px; }
.panel-opcje { display: grid; grid-template-columns: 1fr 1fr; gap: 1px 8px; }
.panel-opcje label { display: flex; align-items: center; gap: 4px; cursor: pointer;
                     margin: 1px 0; font-weight: normal; }
.panel-opcje input { margin: 0; }
.panel-okresy { display: flex; gap: 3px; flex-wrap: wrap; }
.panel-okresy button {
    flex: 1 1 0; padding: 3px 0; font-size: 11px; cursor: pointer;
    border: 1px solid #bbb; border-radius: 3px; background: #f7f7f7;
}
.panel-okresy button.aktywny { background: #c8e6c9; border-color: #4c8c4f; font-weight: bold; }
.panel-okresy button:disabled { color: #bbb; cursor: default; background: #fff; }
.panel-zakres { color: #2e6b30; font-style: italic; font-size: 11px; margin: 3px 0 5px; }
.panel-krycie { display: flex; align-items: center; gap: 6px; margin-top: 6px; }
.panel-krycie input { flex: 1; }
.panel-legenda { margin-top: 8px; }
.panel-legenda .poz { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
.panel-legenda .kolor { width: 22px; height: 13px; border: 1px solid #777; flex: none; }
.panel-info { margin-top: 6px; color: #333; }
.panel-opis { margin-top: 6px; color: #666; font-size: 11px; }
.panel-pobierz { display: block; margin-top: 8px; padding: 5px 0; text-align: center;
                 border: 1px solid #4c8c4f; border-radius: 3px; background: #eef7ee;
                 color: #1b5e20; font-weight: bold; text-decoration: none; }
.panel-pobierz:hover { background: #c8e6c9; }
.wisl-popup .zakres { color: #2e6b30; font-style: italic; margin: 1px 0 5px; }
.wisl-popup .panel-okresy { margin-bottom: 4px; }
/* sekcje popupu oddzielone cienką czarną linią: tytuł | Cykl WISL - informacje podstawowe | Zmiany w kolejnych okresach */
.wisl-popup .wisl-sekcja { border-top: 1px solid #000; padding-top: 6px; margin-top: 7px; }
.wisl-popup .podtytul { font-weight: bold; margin-bottom: 4px; }
.wisl-popup table { border-collapse: collapse; margin: 4px 0; }
.wisl-popup td { padding: 1px 6px 1px 0; }
.wisl-popup td.w { text-align: right; white-space: nowrap; }
.wisl-popup tr.aktywny td { font-weight: bold; }
.wisl-popup .zrodlo { color: #777; font-size: 11px; }
/* miejsce na wykres zarezerwowane od razu: autoprzesunięcie mapy liczy się
   przy otwarciu popupu, zanim vega-embed narysuje wykres */
.wisl-wykres { min-width: 380px; min-height: 285px; }
</style>
"""


class StylPaneli(MacroElement):
    _template = Template("""
{% macro header(this, kwargs) %}""" + STYL_PANELI + """{% endmacro %}
""")

    def __init__(self):
        super().__init__()
        self._name = 'StylPaneli'


def dodaj_styl_paneli(mapa):
    if not any(isinstance(el, StylPaneli) for el in mapa._children.values()):
        StylPaneli().add_to(mapa)


class PanelWarstw(MacroElement):
    _template = Template("""
{% macro header(this, kwargs) %}
<script src="https://cdn.jsdelivr.net/npm/vega@6"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-lite@6"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-embed@7"></script>
{% endmacro %}

{% macro script(this, kwargs) %}
(function() {
    var map = {{ this._parent.get_name() }};
    var D = {{ this.dane | tojson }};
    var podklady = [
        {%- for nazwa, warstwa in this.podklady %}
        { nazwa: {{ nazwa | tojson }}, warstwa: {{ warstwa.get_name() }} },
        {%- endfor %}
    ];
    var nakladki = [
        {%- for nazwa, warstwa, widoczna in this.nakladki %}
        { nazwa: {{ nazwa | tojson }}, warstwa: {{ warstwa.get_name() }}, widoczna: {{ widoczna | tojson }} },
        {%- endfor %}
    ];

    var J = D.jednostki;
    var podzialy = D.kolejnosc_podzialow;            // RDLP, województwa, krainy
    var okresy = Object.keys(J.rdlp.wyniki).sort();
    var wskazniki = {};
    D.wskazniki.forEach(function(w) { wskazniki[w.id] = w; });
    // jeden kartogram: podział (typ jednostek), wskaźnik, cykl, krycie
    var stan = { podzial: podzialy[0], wskaznik: '', okres: okresy[okresy.length - 1], krycie: 0.85 };
    // wartości z dokładnością wskaźnika (przyrost: 8,70); progi legendy bez zer (8–9)
    var fmt = function(v, w, prog) {
        var m = (w && w.miejsca) || 1;
        return v.toLocaleString('pl-PL', { minimumFractionDigits: (m > 1 && !prog) ? m : 0,
                                           maximumFractionDigits: m });
    };
    // wartość z jednostką; wiek z odmianą: 1 rok, 62 lata, 57 lat
    function zJednostka(v, w) {
        var t = fmt(v, w);
        if (w.jednostka !== 'lat') return t + ' ' + w.jednostka;
        var n = Math.round(v), d = n % 10, s = n % 100;
        return t + ' ' + (n === 1 ? 'rok' : (d >= 2 && d <= 4 && (s < 12 || s > 14)) ? 'lata' : 'lat');
    }
    var stanWykresu = D.wykresy[0].id;               // ostatnio wybrany wykres w popupach
    // podświetlenie po najechaniu - jak w pozostałych warstwach portalu
    var PODSWIETLENIE = { fillColor: 'yellow', fillOpacity: 0.5, weight: 1 };
    var aktywny = function(j) { return j === stan.podzial && stan.wskaznik; };

    // --- Podkład: dokładnie jeden; nakładki zawsze nad podkładem ---------
    podklady.forEach(function(p) { p.warstwa.setZIndex(0); });
    function ustawPodklad(i) {
        podklady.forEach(function(p, j) {
            if (j === i) map.addLayer(p.warstwa); else map.removeLayer(p.warstwa);
        });
    }

    // --- Popup z wynikami WISL (RDLP, krainy, województwa) ---------------
    // Cykl wybierany w samym popupie (domyślnie cykl z panelu), wykres
    // zasobności w kolejnych raportach 5-letnich. Treść budowana jako węzeł
    // DOM: popup.update() po narysowaniu wykresu wstawia ten sam węzeł
    // (funkcja treści podmieniłaby HTML i skasowała wykres).
    function otworzPopup(j, f, e) {
        var jd = J[j], nazwa = f.properties.nazwa, okres = stan.okres;
        var div = document.createElement('div');
        div.className = 'wisl-popup';
        div.innerHTML = '<div class="tytul"></div><div class="zakres">' + jd.zakres + '</div>' +
            // 1) tytuł i zakres | 2) wyniki wybranego cyklu | 3) wykres zmian w czasie
            '<div class="wisl-sekcja"><div class="podtytul">Cykl WISL - informacje podstawowe</div>' +
            '<div class="panel-okresy wisl-cykle">' + okresy.map(function(o) {
                return '<button type="button" data-okres="' + o + '">' + o + '</button>';
            }).join('') + '</div><table></table><div class="zrodlo"></div></div>' +
            '<div class="wisl-sekcja"><div class="podtytul">Zmiany w kolejnych okresach</div>' +
            '<div class="panel-okresy wisl-wykresy">' + D.wykresy.map(function(w) {
                return '<button type="button" data-wykres="' + w.id + '">' + w.przycisk + '</button>';
            }).join('') + '</div><div class="wisl-wykres"></div>' +
            '<div class="zrodlo">Źródło: raporty WISL z kolejnych okresów 5-letnich.</div></div>';
        function pokaz() {
            var o = jd.wyniki[okres], r = o.dane[nazwa] || {};
            div.querySelector('.tytul').innerHTML = '<b>' + f.properties.etykieta + '</b> · WISL ' + okres;
            div.querySelector('table').innerHTML = D.wskazniki.map(function(w) {
                var v = r[w.id];
                return '<tr' + (aktywny(j) && w.id === stan.wskaznik ? ' class="aktywny"' : '') + '><td>' +
                       w.nazwa + '</td><td class="w">' + (v === undefined ? '—' : zJednostka(v, w)) +
                       '</td></tr>';
            }).join('');
            div.querySelector('.zrodlo').textContent = 'Źródło: ' + o.zrodlo;
            div.querySelectorAll('.wisl-cykle button').forEach(function(b) {
                b.classList.toggle('aktywny', b.getAttribute('data-okres') === okres);
            });
        }
        div.querySelector('.wisl-cykle').addEventListener('click', function(ev) {
            var b = ev.target.closest('button');
            if (!b) return;
            okres = b.getAttribute('data-okres');
            pokaz();
        });
        pokaz();
        e.popup.setContent(div);
        // wykresy: jeden naraz, wybór zapamiętany dla kolejnych popupów
        function rysujWykres() {
            var seria = jd.serie[stanWykresu], el = div.querySelector('.wisl-wykres');
            div.querySelectorAll('.wisl-wykresy button').forEach(function(b) {
                var s = jd.serie[b.getAttribute('data-wykres')];
                b.disabled = !s || !s.dane[nazwa];
                b.classList.toggle('aktywny', b.getAttribute('data-wykres') === stanWykresu);
            });
            el.innerHTML = '';
            if (!seria || !seria.dane[nazwa] || !window.vegaEmbed) return;
            var spec = JSON.parse(JSON.stringify(D.szablony[stanWykresu]));
            spec.datasets = { wartosci: seria.okna.map(function(o, i) {
                return { lata: o.replace('-', ' - '), wartosc: seria.dane[nazwa][i] };
            }).filter(function(r) { return r.wartosc !== null; }) };
            vegaEmbed(el, spec, { actions: false, renderer: 'svg' })
                .then(function() { e.popup.update(); });
        }
        div.querySelector('.wisl-wykresy').addEventListener('click', function(ev) {
            var b = ev.target.closest('button');
            if (!b || b.disabled) return;
            stanWykresu = b.getAttribute('data-wykres');
            rysujWykres();
        });
        rysujWykres();
    }

    // --- Warstwy jednostek: granice albo kartogram wskaźnika --------------
    function klasa(k, v) {
        for (var i = k.kolory.length - 1; i >= 0; i--) if (v >= k.progi[i]) return i;
        return 0;
    }
    function wartosc(j, nazwa) {
        if (!aktywny(j)) return undefined;
        var r = J[j].wyniki[stan.okres].dane[nazwa] || {};
        return r[stan.wskaznik];
    }
    function styl(j) {
        return function(f) {
            if (!aktywny(j)) return J[j].styl;
            var k = J[j].klasy[stan.wskaznik], v = wartosc(j, f.properties.nazwa);
            return { color: '#333', weight: 1, fillOpacity: v === undefined ? 0.15 : stan.krycie,
                     fillColor: v === undefined ? '#ccc' : k.kolory[klasa(k, v)] };
        };
    }
    var warstwy = {};
    podzialy.forEach(function(j) {
        var g = L.geoJSON(J[j].granice, {
            style: styl(j),
            onEachFeature: function(f, warstwa) {
                // marginesy autoprzesuwania: popup nie chowa się pod panelami
                // w prawym górnym rogu (Leaflet: ...BottomRight = prawy i dolny)
                // ani pod logo i minimapą w lewym górnym rogu
                warstwa.bindPopup('', { maxWidth: 440, minWidth: 340,
                                        autoPanPaddingTopLeft: L.point(170, 70),
                                        autoPanPaddingBottomRight: L.point(300, 10) });
                warstwa.on('popupopen', function(e) { otworzPopup(j, f, e); });
                warstwa.bindTooltip(function() {
                    var v = wartosc(j, f.properties.nazwa);
                    return f.properties.etykieta + (v === undefined ? '' :
                           ': <b>' + zJednostka(v, wskazniki[stan.wskaznik]) + '</b>');
                }, { sticky: true });
                warstwa.on('mouseover', function() { warstwa.setStyle(PODSWIETLENIE); });
                warstwa.on('mouseout', function() { g.resetStyle(warstwa); });
            }
        });
        warstwy[j] = g;
    });
    D.kolejnosc_warstw.forEach(function(j) {
        nakladki.push({ nazwa: J[j].warstwa, warstwa: warstwy[j], widoczna: J[j].widoczna, j: j });
    });

    // --- Panel ------------------------------------------------------------
    var panel = L.control({ position: 'topright' });
    panel.onAdd = function() {
        var d = L.DomUtil.create('div', 'panel-wisl');
        d.innerHTML =
            '<div class="panel-naglowek"><h4>Warstwy</h4><span class="zwin" title="Zwiń / rozwiń">▾</span></div>' +
            '<div class="panel-tresc">' +
            '<div class="panel-sekcja">Podkład</div><div class="panel-opcje">' +
            podklady.map(function(p, i) {
                return '<label><input type="radio" name="war-podklad" value="' + i + '">' + p.nazwa + '</label>';
            }).join('') + '</div>' +
            '<div class="panel-sekcja">Granice i opisy</div><div class="panel-opcje">' +
            nakladki.map(function(n, i) {
                return '<label><input type="checkbox" data-nakladka="' + i + '">' + n.nazwa + '</label>';
            }).join('') + '</div>' +
            '</div>';
        L.DomEvent.disableClickPropagation(d);
        L.DomEvent.disableScrollPropagation(d);
        return d;
    };

    // --- Panel "Wyniki WISL" (pod "Warstwy", nad "Analizy KDE") -----------
    // Ten sam układ co panel KDE: temat -> wybór podziału -> cykl -> legenda.
    var panelWyniki = L.control({ position: 'topright' });
    panelWyniki.onAdd = function() {
        var d = L.DomUtil.create('div', 'panel-wisl');
        d.innerHTML =
            '<div class="panel-naglowek"><h4>Wyniki WISL</h4><span class="zwin" title="Zwiń / rozwiń">▾</span></div>' +
            '<div class="panel-tresc">' +
            '<label class="pole" for="war-wskaznik">Temat</label>' +
            '<select id="war-wskaznik"><option value="">— wyłączone —</option>' +
            D.wskazniki.map(function(w) {
                return '<option value="' + w.id + '">' + w.nazwa + ' [' + w.jednostka + ']</option>';
            }).join('') + '</select>' +
            // przełącznik podziału (i zakres danych) dopiero po wybraniu
            // wskaźnika - pod listą, żeby lista nie przeskakiwała przy wyborze
            '<div id="war-wybor" style="display:none">' +
            '<label class="pole">Podział</label><div class="panel-okresy" id="war-podzialy">' +
            podzialy.map(function(j) {
                return '<button type="button" data-podzial="' + j + '">' + J[j].przycisk + '</button>';
            }).join('') + '</div>' +
            '<div class="panel-zakres" id="war-zakres"></div>' +
            '<label class="pole">Cykl WISL</label><div class="panel-okresy" id="war-okresy">' +
            okresy.map(function(o) {
                return '<button type="button" data-okres="' + o + '">' + o + '</button>';
            }).join('') + '</div>' +
            '<div class="panel-krycie"><span>Krycie</span>' +
            '<input type="range" id="war-krycie" min="0.1" max="1" step="0.05" value="' + stan.krycie + '"></div>' +
            '<div class="panel-legenda" id="war-legenda"></div>' +
            '<div class="panel-info" id="war-info"></div>' +
            '<div class="panel-opis" id="war-opis"></div>' +
            '</div></div>';
        L.DomEvent.disableClickPropagation(d);
        L.DomEvent.disableScrollPropagation(d);
        return d;
    };
    panel.addTo(map);
    panelWyniki.addTo(map);
    var kontener = panel.getContainer();
    var el = function(id) { return document.getElementById(id); };
    function checkbox(j) {
        var i = nakladki.findIndex(function(n) { return n.j === j; });
        return kontener.querySelector('input[data-nakladka="' + i + '"]');
    }
    // kartogram wymaga warstwy jednostek - włączona i na wierzchu
    function pokazWarstwe(j) {
        var cb = checkbox(j);
        if (!cb.checked) { cb.checked = true; map.addLayer(warstwy[j]); }
        warstwy[j].bringToFront();
    }
    function ukryjWarstwe(j) {
        var cb = checkbox(j);
        if (cb.checked) { cb.checked = false; map.removeLayer(warstwy[j]); }
    }

    function odswiez() {
        podzialy.forEach(function(j) { warstwy[j].setStyle(styl(j)); });
        var jd = J[stan.podzial], w = wskazniki[stan.wskaznik];
        el('war-podzialy').querySelectorAll('button').forEach(function(b) {
            b.classList.toggle('aktywny', b.getAttribute('data-podzial') === stan.podzial);
        });
        el('war-zakres').textContent = jd.zakres;
        el('war-wybor').style.display = w ? '' : 'none';
        if (!w) return;
        var k = jd.klasy[w.id];
        var dostepne = okresy.filter(function(o) {
            return Object.values(jd.wyniki[o].dane).some(function(r) { return r[w.id] !== undefined; });
        });
        if (dostepne.indexOf(stan.okres) < 0) stan.okres = dostepne[dostepne.length - 1];
        el('war-okresy').querySelectorAll('button').forEach(function(b) {
            var o = b.getAttribute('data-okres');
            b.disabled = dostepne.indexOf(o) < 0;
            b.classList.toggle('aktywny', o === stan.okres);
        });
        el('war-legenda').innerHTML = k.kolory.map(function(kol, i) {
            return '<div class="poz"><span class="kolor" style="background:' + kol + '"></span>' +
                   fmt(k.progi[i], w, true) + '–' + fmt(k.progi[i + 1], w, true) + ' ' + w.jednostka + '</div>';
        }).reverse().join('');
        var o = jd.wyniki[stan.okres], ogolem = o.ogolem[w.id];
        el('war-info').innerHTML = (ogolem !== undefined ?
            jd.ogolem_etykieta + ': ' + zJednostka(ogolem, w) + '<br>' : '') +
            'Klasy wspólne dla wszystkich cykli.';
        el('war-opis').innerHTML = w.opis + '<br>Źródło: ' + o.zrodlo + '.';
    }

    [kontener, panelWyniki.getContainer()].forEach(function(k) {
        k.querySelector('.panel-naglowek').addEventListener('click', function() {
            k.classList.toggle('zwiniety');
            k.querySelector('.zwin').textContent = k.classList.contains('zwiniety') ? '▸' : '▾';
        });
    });
    kontener.querySelectorAll('input[name="war-podklad"]').forEach(function(r) {
        r.addEventListener('change', function() { ustawPodklad(parseInt(this.value)); });
    });
    kontener.querySelectorAll('input[data-nakladka]').forEach(function(c) {
        var n = nakladki[parseInt(c.getAttribute('data-nakladka'))];
        c.checked = n.widoczna;
        if (n.widoczna) map.addLayer(n.warstwa); else map.removeLayer(n.warstwa);
        c.addEventListener('change', function() {
            if (this.checked) map.addLayer(n.warstwa); else map.removeLayer(n.warstwa);
            // ukrycie warstwy aktywnego kartogramu wyłącza kartogram - inaczej
            // w panelu zostaje legenda bez mapy
            if (!this.checked && n.j && n.j === stan.podzial && stan.wskaznik) {
                stan.wskaznik = '';
                el('war-wskaznik').value = '';
                odswiez();
            }
        });
    });
    var poczatkowy = {{ this.podklad_poczatkowy }};
    kontener.querySelectorAll('input[name="war-podklad"]')[poczatkowy].checked = true;
    ustawPodklad(poczatkowy);

    el('war-podzialy').addEventListener('click', function(e) {
        var b = e.target.closest('button');
        if (!b) return;
        var poprzedni = stan.podzial;
        stan.podzial = b.getAttribute('data-podzial');
        if (stan.wskaznik) {
            // zmiana podziału wyłącza warstwę poprzedniego (także w panelu
            // "Warstwy") - na mapie zostaje tylko kartogram wybranego
            if (poprzedni !== stan.podzial) ukryjWarstwe(poprzedni);
            pokazWarstwe(stan.podzial);
        }
        map.closePopup();
        odswiez();
    });
    el('war-wskaznik').addEventListener('change', function() {
        stan.wskaznik = this.value;
        if (stan.wskaznik) pokazWarstwe(stan.podzial);
        odswiez();
    });
    el('war-okresy').addEventListener('click', function(e) {
        var b = e.target.closest('button');
        if (!b || b.disabled) return;
        stan.okres = b.getAttribute('data-okres');
        map.closePopup();
        odswiez();
    });
    el('war-krycie').addEventListener('input', function() {
        stan.krycie = parseFloat(this.value);
        warstwy[stan.podzial].setStyle(styl(stan.podzial));
    });
    odswiez();
})();
{% endmacro %}
""")

    def __init__(self, dane, podklady, nakladki, podklad_poczatkowy=0):
        super().__init__()
        self._name = 'PanelWarstw'
        self.dane = dane
        self.podklady = podklady
        self.nakladki = nakladki
        self.podklad_poczatkowy = podklad_poczatkowy


def _granice(gdf, kol_nazwa, etykieta):
    """GeoJSON z właściwościami nazwa (klucz danych) i etykieta (do wyświetlenia)."""
    g = gdf.to_crs(4326).copy()
    g['nazwa'] = g[kol_nazwa].astype(str)
    g['etykieta'] = g.apply(etykieta, axis=1)
    return json.loads(g[['nazwa', 'etykieta', 'geometry']].to_json())


def dodaj_panel_warstw(mapa, granice_rdlp, granice_krainy, granice_wojewodztwa,
                       podklady, nakladki, podklad_poczatkowy=0):
    """
    granice_rdlp        - GeoDataFrame RDLP z kolumną NAZWA;
    granice_krainy      - GeoDataFrame krain z kolumnami Kraina (I-VIII), Nazwa;
    granice_wojewodztwa - GeoDataFrame województw z kolumną JPT_NAZWA_;
    podklady            - lista (nazwa, TileLayer) - wybór jednego;
    nakladki            - lista (nazwa, warstwa folium, widoczna_na_starcie);
                          krainy, województwa i RDLP (kartogramy i popupy
                          WISL) panel dodaje sam, na końcu listy.
    Panel dodawać PRZED panelem KDE - w rogu układają się w kolejności dodania.
    """
    dodaj_styl_paneli(mapa)
    jednostki = {
        'rdlp': {
            'przycisk': 'RDLP',
            'warstwa': 'RDLP', 'widoczna': True,
            'styl': {'color': 'blue', 'weight': 1.5, 'fillColor': 'blue', 'fillOpacity': 0.1},
            'zakres': 'Dane dotyczą lasów w zarządzie PGL LP.',
            'ogolem_etykieta': 'PGL LP ogółem',
            'granice': _granice(granice_rdlp, 'NAZWA', lambda r: f"RDLP {r['NAZWA']}"),
            'wyniki': _tabela_wynikow(_z_uzytkowaniem(WISL_RDLP, UZYTKOWANIE_OKNA['rdlp']), RDLP),
            'klasy': _klasy(_z_uzytkowaniem(WISL_RDLP, UZYTKOWANIE_OKNA['rdlp'])),
            'serie': _serie({'zasobnosc': _zasobnosc_rdlp(), 'martwe': MARTWE_OKNA['rdlp'],
                             'przyrost': PRZYROST_OKNA['rdlp'],
                             'uzytkowanie': UZYTKOWANIE_OKNA['rdlp']}, RDLP),
        },
        'wojewodztwa': {
            'przycisk': 'Województwa',
            'warstwa': 'Województwa', 'widoczna': False,
            'styl': {'color': 'pink', 'weight': 1.5, 'fillColor': 'pink', 'fillOpacity': 0.1},
            'zakres': 'Dane dotyczą lasów wszystkich form własności.',
            'ogolem_etykieta': 'Polska ogółem',
            'granice': _granice(granice_wojewodztwa, 'JPT_NAZWA_',
                                lambda r: f"Województwo {r['JPT_NAZWA_']}"),
            'wyniki': _tabela_wynikow(_z_uzytkowaniem(WISL_WOJEWODZTWA, UZYTKOWANIE_OKNA['wojewodztwa']), WOJEWODZTWA),
            'klasy': _klasy(_z_uzytkowaniem(WISL_WOJEWODZTWA, UZYTKOWANIE_OKNA['wojewodztwa'])),
            'serie': _serie({'zasobnosc': ZASOBNOSC_OKNA_WOJEWODZTWA,
                             'martwe': MARTWE_OKNA['wojewodztwa'],
                             'przyrost': PRZYROST_OKNA['wojewodztwa'],
                             'uzytkowanie': UZYTKOWANIE_OKNA['wojewodztwa']}, WOJEWODZTWA),
        },
        'krainy': {
            'przycisk': 'Krainy',
            'warstwa': 'Krainy przyr.-leśne', 'widoczna': False,
            'styl': {'color': 'orange', 'weight': 1.5, 'fillColor': 'orange', 'fillOpacity': 0.1},
            'zakres': 'Dane dotyczą lasów wszystkich form własności.',
            'ogolem_etykieta': 'Polska ogółem',
            'granice': _granice(granice_krainy, 'Nazwa',
                                lambda r: f"Kraina {r['Nazwa']} ({r['Kraina']})"),
            'wyniki': _tabela_wynikow(_z_uzytkowaniem(WISL_KRAINY, UZYTKOWANIE_OKNA['krainy']), KRAINY),
            'klasy': _klasy(_z_uzytkowaniem(WISL_KRAINY, UZYTKOWANIE_OKNA['krainy'])),
            'serie': _serie({'zasobnosc': ZASOBNOSC_OKNA_KRAINY, 'martwe': MARTWE_OKNA['krainy'],
                             'przyrost': PRZYROST_OKNA['krainy'],
                             'uzytkowanie': UZYTKOWANIE_OKNA['krainy']}, KRAINY),
        },
    }
    dane = {'wskazniki': [{k: v for k, v in w.items() if k != 'paleta'} for w in WSKAZNIKI],
            'wykresy': [{k: w[k] for k in ('id', 'przycisk')} for w in WYKRESY],
            'szablony': {w['id']: szablon_wykresu(w['tytul'], w['os']) for w in WYKRESY},
            'jednostki': jednostki,
            # jawne kolejności - filtr tojson sortuje klucze słowników
            'kolejnosc_podzialow': ['rdlp', 'wojewodztwa', 'krainy'],
            # pola wyboru w "Granice i opisy" (po warstwach folium)
            'kolejnosc_warstw': ['krainy', 'wojewodztwa', 'rdlp']}
    PanelWarstw(dane, podklady, nakladki, podklad_poczatkowy).add_to(mapa)
