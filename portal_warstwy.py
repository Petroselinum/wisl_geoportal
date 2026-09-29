"""
Panele portalu mapowego (1_portal_mapowy_wisl.py) w prawym górnym rogu:

- "Warstwy" (PanelWarstw): podkład, granice oraz wyniki WISL w PGL LP wg
  RDLP - kartogram wybranego wskaźnika z przełączaniem cykli WISL;
- "Analizy KDE" (portal_kde.PanelKDE) - pod nim, w tym samym stylu.

Wspólny wygląd paneli: StylPaneli (dodawany raz, przez dodaj_styl_paneli).

Kartogram RDLP jest rysowany w przeglądarce z JEDNEJ warstwy granic RDLP
i tabeli wyników (data.WISL_RDLP) - wcześniej każdy wskaźnik był osobną
kopią rdlp.geojson w HTML, a przy 4 cyklach byłoby ich 20.

Kliknięcie RDLP, krainy przyrodniczo-leśnej albo województwa otwiera popup
z wynikami WISL (cykl do wyboru w popupie) i wykresem zasobności w kolejnych
raportach 5-letnich. RDLP - lasy w zarządzie PGL LP (data.WISL_RDLP),
krainy i województwa - lasy wszystkich form własności (data.WISL_KRAINY,
data.WISL_WOJEWODZTWA).

Klasy kolorów każdego wskaźnika są WSPÓLNE dla wszystkich cykli (zakres
z wartości wszystkich cykli), żeby zmiana koloru RDLP między cyklami
oznaczała zmianę wartości - ta sama zasada co stałe progi w skryptach kde_*.
"""
import json
import math

import altair as alt
from branca.element import MacroElement
from jinja2 import Template
from matplotlib import colormaps
from matplotlib.colors import to_hex

import pandas as pd

from data import (RDLP, WISL_RDLP, zasob_time_rdlp,
                  KRAINY, WISL_KRAINY, ZASOBNOSC_OKNA_KRAINY,
                  WOJEWODZTWA, WISL_WOJEWODZTWA, ZASOBNOSC_OKNA_WOJEWODZTWA)

# Wskaźniki kartogramu RDLP; klucze jak w data.WISL_RDLP
WSKAZNIKI_RDLP = [
    {'id': 'powierzchnia', 'nazwa': 'Powierzchnia lasów', 'jednostka': 'tys. ha',
     'opis': 'Powierzchnia lasów w zarządzie PGL LP.', 'paleta': 'Greens'},
    {'id': 'miazszosc', 'nazwa': 'Miąższość', 'jednostka': 'mln m³',
     'opis': 'Miąższość grubizny brutto lasów w zarządzie PGL LP.', 'paleta': 'YlGn'},
    {'id': 'zasobnosc', 'nazwa': 'Zasobność', 'jednostka': 'm³/ha',
     'opis': 'Przeciętna zasobność grubizny brutto lasów w zarządzie PGL LP.', 'paleta': 'YlGn'},
    {'id': 'wiek', 'nazwa': 'Średni wiek', 'jednostka': 'lat',
     'opis': 'Przeciętny wiek drzewostanów w zarządzie PGL LP.', 'paleta': 'PuBu'},
    {'id': 'martwe', 'nazwa': 'Martwe drewno', 'jednostka': 'm³/ha',
     'opis': 'Przeciętna miąższość martwego drewna w lasach w zarządzie PGL LP.',
     'paleta': 'YlOrBr'},
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


def _wskazniki_z_klasami():
    wynik = []
    for w in WSKAZNIKI_RDLP:
        wartosci = [v for okres in WISL_RDLP.values()
                    for v in (okres.get(w['id']) or []) if v is not None]
        if not wartosci:
            continue
        progi = _progi_klas(wartosci)
        n = len(progi) - 1
        cmap = colormaps[w['paleta']]
        kolory = [to_hex(cmap(0.2 + 0.75 * i / max(n - 1, 1))) for i in range(n)]
        wynik.append({k: v for k, v in w.items() if k != 'paleta'}
                     | {'progi': progi, 'kolory': kolory})
    return wynik


def _tabela_wynikow(wyniki, nazwy):
    """{okres: {'zrodlo', 'ogolem', 'dane': {jednostka: {wskaznik: wartosc}}}}"""
    tabela = {}
    for okres, dane in sorted(wyniki.items()):
        jednostki = {nazwa: {} for nazwa in nazwy}
        for w in WSKAZNIKI_RDLP:
            for nazwa, v in zip(nazwy, dane.get(w['id']) or []):
                if v is not None:
                    jednostki[nazwa][w['id']] = v
        tabela[okres] = {'zrodlo': dane.get('zrodlo', ''),
                         'ogolem': dane.get('ogolem', {}), 'dane': jednostki}
    return tabela


def wykres_zasobnosci(nazwa, df):
    """df: kolumny lata ('2005 - 2009'), jednostka, zasobnosc."""
    data = df[df['jednostka'] == nazwa][['lata', 'zasobnosc']].copy()
    chart = alt.Chart(data).mark_line(point=True).encode(
        x=alt.X('lata:O', title='Okres',
                axis=alt.Axis(labelAngle=-45, labelOverlap=False)),
        y=alt.Y('zasobnosc:Q', title='Zasobność [m³/ha]', scale=alt.Scale(zero=False)),
        tooltip=['lata', 'zasobnosc']
    ).properties(
        title=f"Zasobność w kolejnych okresach 5-letnich",
        width=300,
        height=170
    )
    return chart


def _okna_df(okna, nazwy):
    """ZASOBNOSC_OKNA_* ({'2005-2009': [..]}) -> df jak zasob_time_rdlp()."""
    return pd.DataFrame([{'lata': okno.replace('-', ' - '), 'jednostka': n, 'zasobnosc': v}
                         for okno, wartosci in okna.items() for n, v in zip(nazwy, wartosci)])


def _wykresy(df):
    return {nazwa: wykres_zasobnosci(nazwa, df).to_dict() for nazwa in df['jednostka'].unique()}


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
.panel-krycie { display: flex; align-items: center; gap: 6px; margin-top: 6px; }
.panel-krycie input { flex: 1; }
.panel-legenda { margin-top: 8px; }
.panel-legenda .poz { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
.panel-legenda .kolor { width: 22px; height: 13px; border: 1px solid #777; flex: none; }
.panel-info { margin-top: 6px; color: #333; }
.panel-opis { margin-top: 6px; color: #666; font-size: 11px; }
.wisl-popup .zakres { color: #2e6b30; font-style: italic; margin: 1px 0 5px; }
.wisl-popup .panel-okresy { margin-bottom: 4px; }
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
    var okresy = Object.keys(J.rdlp.wyniki).sort();
    var wskazniki = {};
    D.wskazniki.forEach(function(w) { wskazniki[w.id] = w; });
    var stan = { wskaznik: '', okres: okresy[okresy.length - 1], krycie: 0.85 };
    var fmt = function(v) { return v.toLocaleString('pl-PL', { maximumFractionDigits: 1 }); };

    // --- Podkład: dokładnie jeden; etykiety zawsze nad podkładem ---------
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
            '<div class="panel-okresy">' + okresy.map(function(o) {
                return '<button type="button" data-okres="' + o + '">' + o + '</button>';
            }).join('') + '</div><table></table>' +
            (jd.wykresy[nazwa] ? '<div class="wisl-wykres"></div>' : '') +
            '<div class="zrodlo"></div>';
        function pokaz() {
            var o = jd.wyniki[okres], r = o.dane[nazwa] || {};
            div.querySelector('.tytul').innerHTML = '<b>' + f.properties.etykieta + '</b> · WISL ' + okres;
            div.querySelector('table').innerHTML = D.wskazniki.map(function(w) {
                var v = r[w.id];
                return '<tr' + (w.id === stan.wskaznik ? ' class="aktywny"' : '') + '><td>' + w.nazwa +
                       '</td><td class="w">' + (v === undefined ? '—' : fmt(v) + ' ' + w.jednostka) + '</td></tr>';
            }).join('');
            div.querySelector('.zrodlo').textContent = 'Źródło: ' + o.zrodlo;
            div.querySelectorAll('.panel-okresy button').forEach(function(b) {
                b.classList.toggle('aktywny', b.getAttribute('data-okres') === okres);
            });
        }
        div.querySelector('.panel-okresy').addEventListener('click', function(ev) {
            var b = ev.target.closest('button');
            if (!b) return;
            okres = b.getAttribute('data-okres');
            pokaz();
        });
        pokaz();
        e.popup.setContent(div);
        var wykres = div.querySelector('.wisl-wykres');
        if (wykres && window.vegaEmbed)
            vegaEmbed(wykres, jd.wykresy[nazwa], { actions: false, renderer: 'svg' })
                .then(function() { e.popup.update(); });
    }
    function podepnijPopup(j, f, warstwa) {
        // margines autoprzesuwania z prawej (Leaflet: ...BottomRight = prawy
        // i dolny): popup nie chowa się pod panelami w prawym górnym rogu
        warstwa.bindPopup('', { maxWidth: 440, minWidth: 340,
                                autoPanPaddingBottomRight: L.point(300, 10) });
        warstwa.on('popupopen', function(e) { otworzPopup(j, f, e); });
    }

    // --- RDLP: jedna warstwa, styl zależny od wskaźnika i cyklu ----------
    function klasa(w, v) {
        for (var i = w.kolory.length - 1; i >= 0; i--) if (v >= w.progi[i]) return i;
        return 0;
    }
    function wartosc(nazwa) {
        var r = J.rdlp.wyniki[stan.okres].dane[nazwa] || {};
        return stan.wskaznik ? r[stan.wskaznik] : undefined;
    }
    function styl(f) {
        if (!stan.wskaznik)
            return { color: 'blue', weight: 1.5, fillColor: 'blue', fillOpacity: 0.1 };
        var w = wskazniki[stan.wskaznik], v = wartosc(f.properties.nazwa);
        return { color: '#333', weight: 1, fillOpacity: v === undefined ? 0.15 : stan.krycie,
                 fillColor: v === undefined ? '#ccc' : w.kolory[klasa(w, v)] };
    }
    var rdlp = L.geoJSON(J.rdlp.granice, {
        style: styl,
        onEachFeature: function(f, warstwa) {
            podepnijPopup('rdlp', f, warstwa);
            warstwa.bindTooltip(function() {
                var v = wartosc(f.properties.nazwa);
                return f.properties.etykieta + (v === undefined ? '' :
                       ': <b>' + fmt(v) + ' ' + wskazniki[stan.wskaznik].jednostka + '</b>');
            }, { sticky: true });
            warstwa.on('mouseover', function() { warstwa.setStyle({ weight: 3 }); });
            warstwa.on('mouseout', function() { rdlp.resetStyle(warstwa); });
        }
    });

    // --- Krainy i województwa: granice + ten sam popup --------------------
    function warstwaGranic(j, kolor) {
        var styl = { color: kolor, weight: 1.5, fillColor: kolor, fillOpacity: 0.1 };
        var g = L.geoJSON(J[j].granice, {
            style: styl,
            onEachFeature: function(f, warstwa) {
                podepnijPopup(j, f, warstwa);
                warstwa.bindTooltip(f.properties.etykieta, { sticky: true });
                warstwa.on('mouseover', function() {
                    warstwa.setStyle({ fillColor: 'yellow', fillOpacity: 0.5, weight: 1 });
                });
                warstwa.on('mouseout', function() { g.resetStyle(warstwa); });
            }
        });
        return g;
    }
    nakladki.push({ nazwa: 'Krainy przyr.-leśne', warstwa: warstwaGranic('krainy', 'orange'), widoczna: false });
    nakladki.push({ nazwa: 'Województwa', warstwa: warstwaGranic('wojewodztwa', 'pink'), widoczna: false });
    nakladki.push({ nazwa: 'RDLP', warstwa: rdlp, widoczna: true });

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
            '<div class="panel-sekcja">Wyniki WISL w PGL LP wg RDLP</div>' +
            '<select id="war-wskaznik"><option value="">— wyłączone —</option>' +
            D.wskazniki.map(function(w) {
                return '<option value="' + w.id + '">' + w.nazwa + ' [' + w.jednostka + ']</option>';
            }).join('') + '</select>' +
            '<div id="war-wybor" style="display:none">' +
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
    var kontener = panel.getContainer();
    var el = function(id) { return document.getElementById(id); };

    function odswiez() {
        rdlp.setStyle(styl);
        var w = wskazniki[stan.wskaznik];
        el('war-wybor').style.display = w ? '' : 'none';
        if (!w) return;
        var dostepne = okresy.filter(function(o) {
            return Object.values(J.rdlp.wyniki[o].dane).some(function(r) { return r[w.id] !== undefined; });
        });
        if (dostepne.indexOf(stan.okres) < 0) stan.okres = dostepne[dostepne.length - 1];
        el('war-okresy').querySelectorAll('button').forEach(function(b) {
            var o = b.getAttribute('data-okres');
            b.disabled = dostepne.indexOf(o) < 0;
            b.classList.toggle('aktywny', o === stan.okres);
        });
        var n = w.kolory.length;
        el('war-legenda').innerHTML = w.kolory.map(function(k, i) {
            return '<div class="poz"><span class="kolor" style="background:' + k + '"></span>' +
                   fmt(w.progi[i]) + '–' + fmt(w.progi[i + 1]) + ' ' + w.jednostka + '</div>';
        }).reverse().join('');
        var o = J.rdlp.wyniki[stan.okres], ogolem = o.ogolem[w.id];
        el('war-info').innerHTML = (ogolem !== undefined ?
            'PGL LP ogółem: ' + fmt(ogolem) + ' ' + w.jednostka + '<br>' : '') +
            'Klasy wspólne dla wszystkich cykli.';
        el('war-opis').innerHTML = w.opis + '<br>Źródło: ' + o.zrodlo + '.';
    }

    kontener.querySelector('.panel-naglowek').addEventListener('click', function() {
        kontener.classList.toggle('zwiniety');
        kontener.querySelector('.zwin').textContent = kontener.classList.contains('zwiniety') ? '▸' : '▾';
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
        });
    });
    var poczatkowy = {{ this.podklad_poczatkowy }};
    kontener.querySelectorAll('input[name="war-podklad"]')[poczatkowy].checked = true;
    ustawPodklad(poczatkowy);

    el('war-wskaznik').addEventListener('change', function() {
        stan.wskaznik = this.value;
        // kartogram wymaga warstwy RDLP
        var cb = kontener.querySelector('input[data-nakladka="' + (nakladki.length - 1) + '"]');
        if (stan.wskaznik && !cb.checked) { cb.checked = true; map.addLayer(rdlp); }
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
        rdlp.setStyle(styl);
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
                          krainy, województwa i RDLP (z popupami WISL) panel
                          dodaje sam, na końcu listy.
    Panel dodawać PRZED panelem KDE - w rogu układają się w kolejności dodania.
    """
    dodaj_styl_paneli(mapa)
    rdlp_df = zasob_time_rdlp().rename(columns={'rdlp': 'jednostka'})
    jednostki = {
        'rdlp': {
            'zakres': 'Dane dotyczą lasów w zarządzie PGL LP.',
            'granice': _granice(granice_rdlp, 'NAZWA', lambda r: f"RDLP {r['NAZWA']}"),
            'wyniki': _tabela_wynikow(WISL_RDLP, RDLP),
            'wykresy': _wykresy(rdlp_df),
        },
        'krainy': {
            'zakres': 'Dane dotyczą lasów wszystkich form własności.',
            'granice': _granice(granice_krainy, 'Nazwa',
                                lambda r: f"Kraina {r['Nazwa']} ({r['Kraina']})"),
            'wyniki': _tabela_wynikow(WISL_KRAINY, KRAINY),
            'wykresy': _wykresy(_okna_df(ZASOBNOSC_OKNA_KRAINY, KRAINY)),
        },
        'wojewodztwa': {
            'zakres': 'Dane dotyczą lasów wszystkich form własności.',
            'granice': _granice(granice_wojewodztwa, 'JPT_NAZWA_',
                                lambda r: f"Województwo {r['JPT_NAZWA_']}"),
            'wyniki': _tabela_wynikow(WISL_WOJEWODZTWA, WOJEWODZTWA),
            'wykresy': _wykresy(_okna_df(ZASOBNOSC_OKNA_WOJEWODZTWA, WOJEWODZTWA)),
        },
    }
    dane = {'wskazniki': _wskazniki_z_klasami(), 'jednostki': jednostki}
    PanelWarstw(dane, podklady, nakladki, podklad_poczatkowy).add_to(mapa)
