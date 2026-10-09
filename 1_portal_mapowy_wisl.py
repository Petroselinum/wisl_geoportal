import folium
from folium.plugins import MiniMap, Search
from folium import Element
from branca.element import MacroElement
from jinja2 import Template
import geopandas as gpd
import shapely
from pathlib import Path
from portal_kde import dodaj_panel_kde
from portal_warstwy import dodaj_panel_warstw

#Aplikację należy uruchamiać na lokalnym serwerze (serwer.py - jak
# `python -m http.server`, ale przeglądarka nie pokazuje starej wersji
# z pamięci podręcznej po przebudowie portalu):
# python serwer.py 8000
# http://localhost:8000/wygerenowane_animacje/aplikacja_mapowa.html
#
# Warstwy analityczne pochodzą z plików GeoJSON zapisanych przez skrypty
# kde_*.py (KDE_gatunki, KDE_zasobnosc, KDE_martwe_drewno, KDE_uszkodzenia,
# KDE_uszkodzenia_ryzyko) - przed zbudowaniem portalu trzeba je przeliczyć.
# Wybiera się je w panelu "Analizy KDE" (portal_kde.py).
#
# Podkład i granice - panel "Warstwy", wyniki WISL - panel "Wyniki WISL"
# (oba w portal_warstwy.py):
# kartogram RDLP z przełączaniem cykli (data.WISL_RDLP) oraz popupy z wynikami
# i wykresem zasobności po kliknięciu RDLP, krainy albo województwa
# (data.WISL_KRAINY, data.WISL_WOJEWODZTWA). Oba panele stoją w prawym
# górnym rogu; zastępują LayerControl / GroupedLayerControl.

max_zoom = 9
output_dir = Path('wygerenowane_animacje')

# Uproszczenie warstw wektorowych osadzanych w HTML (rdlp.geojson 4,4 MB,
# krainy.geojson 10,5 MB, wojewodztwa.geojson 0,7 MB w pełnej szczegółowości).
# 200 m to ~1 piksel przy max_zoom 9 (~190 m/piksel), więc różnica jest
# niewidoczna.
TOLERANCJA_WARSTW_M = 200


def uprosc_warstwe(gdf, tolerancja_m=TOLERANCJA_WARSTW_M):
    """
    Upraszcza warstwę poligonów stykających się ze sobą (RDLP, krainy,
    województwa).
    coverage_simplify upraszcza wspólną granicę sąsiadów identycznie po obu
    stronach, więc nie powstają szczeliny ani nakładki (zwykłe simplify
    upraszcza każdy poligon osobno). Współrzędne zaokrąglane do 4 miejsc
    (~10 m) - pełna precyzja zajmowała ponad połowę objętości.
    """
    g = gdf.to_crs(2180)
    g['geometry'] = shapely.coverage_simplify(g.geometry.values, tolerancja_m)
    g = g.to_crs(4326)
    g['geometry'] = shapely.set_precision(g.geometry.values, 1e-4)
    return g


# Mapa
min_lat=45.4
max_lat=58.74
min_lon=-0.1
max_lon=41.0

m = folium.Map(
    location=[52.0, 19.0],  # centrum Polski
    zoom_start=7,
    max_zoom=max_zoom,
    min_zoom=6,
    control_scale=True,
    tiles=None,
    min_lat=min_lat,
    max_lat=max_lat,
    min_lon=min_lon,
    max_lon=max_lon,
    max_bounds=True
)


# Podkłady - wybór w panelu "Warstwy"
osm = folium.TileLayer(
    tiles='OpenStreetMap',
    name='OpenStreetMap',
    max_zoom=max_zoom,
    min_zoom=6,
).add_to(m)

# Ortofotomapa GUGiK (geoportal.gov.pl), WMTS w standardowej rozdzielczości.
# Zamiast Esri World Imagery: warunki Esri wymagają oprogramowania Esri albo
# subskrypcji ArcGIS. Usługa GUGiK jest bezpłatna ("Brak ograniczeń
# w publicznym dostępie"; korzystanie = akceptacja regulaminu Geoportalu).
# Siatka EPSG:3857 usługi to standardowa siatka web mercator (ten sam
# narożnik i skale), więc {z}/{x}/{y} Leafleta idą wprost do TILEMATRIX /
# TILECOL / TILEROW. WMS StandardResolution odpowiadał w testach (2026-10-09)
# głównie błędem 404, a HighResolution ma luki w pokryciu kraju.
ortofoto = folium.TileLayer(
    tiles=('https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMTS/StandardResolution'
           '?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=ORTOFOTOMAPA&STYLE=default'
           '&FORMAT=image/jpeg&TILEMATRIXSET=EPSG:3857&TILEMATRIX=EPSG:3857:{z}'
           '&TILEROW={y}&TILECOL={x}'),
    attr='Ortofotomapa &copy; <a href="https://www.geoportal.gov.pl">GUGiK</a>',
    name='Ortofotomapa',
    overlay=False,
    max_zoom=max_zoom,
    min_zoom=6,
).add_to(m)


class PonowKafelki(MacroElement):
    """Serwer GUGiK odrzuca czasem pojedyncze żądania (w testach 3 z 20
    kafelków; te same adresy chwilę później zwracały 200) - kafelek z błędem
    jest pobierany ponownie, do 3 razy, z rosnącą przerwą.
    Znane ograniczenie usługi (2026-10-09, zostawione świadomie): WMTS
    w siatce EPSG:3857 odrzuca rzędy powyżej ok. 54,9°N ("TileOutOfRange"),
    więc ortofotomapa jest ucięta na pasie wybrzeża (Łeba-Rozewie)."""
    _template = Template("""
{% macro script(this, kwargs) %}
{{ this._parent.get_name() }}.on('tileerror', function(e) {
    var img = e.tile, proba = (img._proba || 0) + 1;
    if (proba > 3) return;
    img._proba = proba;
    setTimeout(function() {
        img.src = img.src.replace(/&_proba=\\d+$/, '') + '&_proba=' + proba;
    }, 500 * proba);
});
{% endmacro %}
""")


ortofoto.add_child(PonowKafelki())

# Nakładki z etykietami Esri (World_Boundaries_and_Places) już nie ma -
# warunki Esri jak przy ortofotomapie (2026-10-09).

# Logo WISL
logo_html = '''
<div style="position: fixed; 
            top: 10px; 
            left: 50px; 
            width: 150px; 
            height: 50px;
            z-index: 9999;">
    <img src="/data/WISL_logo_opis.png" 
         style="width: 100%; height: 100%; object-fit: contain;">
</div>
'''

m.get_root().html.add_child(Element(logo_html))

# Tytuł karty przeglądarki
m.get_root().header.add_child(Element('<title>Portal mapowy WISL</title>'))

#Nadleśnictwa

nadlesnictwa = gpd.read_file('data/nadlesnictwa_simple.geojson')

nadlgeo = folium.GeoJson(
    data = nadlesnictwa,
    name="Nadleśnictwa",
    style_function=lambda feature: {
        "fillColor": "blue",
        "color": "blue",
        "weight": .3,
        "fillOpacity": 0.1,
    },
    highlight_function=lambda feature: {
        'fillColor': 'yellow',
        'fillOpacity': 0.5,
        'color': 'blue',
        'weight': .3,
    },
    tooltip=folium.GeoJsonTooltip(
        fields=["ins_name"], aliases=["Nadleśnictwo"], localize=True
    ),
).add_to(m)

nadlsearch = Search(
    layer=nadlgeo,
    geom_type="Polygon",
    placeholder="Wyszukaj Nadleśnictwo",
    collapsed=False,
    search_label="ins_name",
    weight=3,
    position="topright"
).add_to(m)

#RDLP, krainy przyrodniczo-leśne, województwa - granice z popupami wyników
# WISL (i kartogramem) rysuje portal_warstwy.py (panele "Warstwy" i "Wyniki WISL")

rdlp_granice = uprosc_warstwe(gpd.read_file('data/rdlp.geojson'))
krainy = uprosc_warstwe(gpd.read_file('data/krainy.geojson'))
wojewodztwa = uprosc_warstwe(gpd.read_file('data/wojewodztwa.geojson'))

#################################################
# Panele w prawym górnym rogu: "Warstwy", "Wyniki WISL", pod nimi "Analizy KDE"
# (kolejność dodania = kolejność w rogu, pod wyszukiwarką nadleśnictw)
#################################################
dodaj_panel_warstw(
    m,
    granice_rdlp=rdlp_granice,
    granice_krainy=krainy,
    granice_wojewodztwa=wojewodztwa,
    podklady=[('OpenStreetMap', osm), ('Ortofotomapa', ortofoto)],
    nakladki=[('Nadleśnictwa', nadlgeo, True)],
    podklad_poczatkowy=0,   # OpenStreetMap
)

dodaj_panel_kde(m, output_dir)

class Wspolrzedne(MacroElement):
    """Kliknięcie w mapę (poza jednostkami z popupem) pokazuje współrzędne -
    jak folium.LatLngPopup, ale po polsku i z przecinkiem dziesiętnym."""
    _template = Template("""
{% macro script(this, kwargs) %}
(function() {
    var popup = L.popup();
    var st = function(v) { return v.toFixed(4).replace('.', ',') + '°'; };
    {{ this._parent.get_name() }}.on('click', function(e) {
        popup.setLatLng(e.latlng)
             .setContent('Szerokość: ' + st(e.latlng.lat) + '<br>Długość: ' + st(e.latlng.lng))
             .openOn({{ this._parent.get_name() }});
    });
})();
{% endmacro %}
""")


m.add_child(Wspolrzedne())

#Minimapa nawigacyjna
MiniMap(position="topleft",
        toggle_display=True).add_to(m)


output_dir.mkdir(parents=True, exist_ok=True)
file_path = output_dir / 'aplikacja_mapowa.html'
m.save(file_path)
