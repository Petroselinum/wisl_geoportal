import folium
from folium.plugins import MiniMap, Search
from folium import Element
import geopandas as gpd
import shapely
from pathlib import Path
from portal_kde import dodaj_panel_kde
from portal_warstwy import dodaj_panel_warstw

#Aplikację należy uruchamiać na lokalnym serverze (z katalogu projektu):
# python -m http.server 8000
# http://localhost:8000/wygerenowane_animacje/aplikacja_mapowa.html
#
# Warstwy analityczne pochodzą z plików GeoJSON zapisanych przez skrypty
# kde_*.py (KDE_gatunki, KDE_zasobnosc, KDE_martwe_drewno, KDE_uszkodzenia,
# KDE_uszkodzenia_ryzyko) - przed zbudowaniem portalu trzeba je przeliczyć.
# Wybiera się je w panelu "Analizy KDE" (portal_kde.py).
#
# Podkład, granice i wyniki WISL - panel "Warstwy" (portal_warstwy.py):
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

# Ortofotomapa
ortofoto = folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr='Esri',
    name='Ortofotomapa',
    overlay=False,
    max_zoom=max_zoom,
    min_zoom=6,
).add_to(m)

etykiety = folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
    attr='Esri',
    name='Etykiety na ortofotomapie',
    overlay=True,
    max_zoom=max_zoom,
    min_zoom=6,
).add_to(m)

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
# WISL (i kartogramem RDLP) rysuje panel "Warstwy" (portal_warstwy.py)

rdlp_granice = uprosc_warstwe(gpd.read_file('data/rdlp.geojson'))
krainy = uprosc_warstwe(gpd.read_file('data/krainy.geojson'))
wojewodztwa = uprosc_warstwe(gpd.read_file('data/wojewodztwa.geojson'))

#################################################
# Panele w prawym górnym rogu: "Warstwy", pod nim "Analizy KDE"
# (kolejność dodania = kolejność w rogu, pod wyszukiwarką nadleśnictw)
#################################################
dodaj_panel_warstw(
    m,
    granice_rdlp=rdlp_granice,
    granice_krainy=krainy,
    granice_wojewodztwa=wojewodztwa,
    podklady=[('OpenStreetMap', osm), ('Ortofotomapa', ortofoto)],
    nakladki=[('Etykiety', etykiety, True),
              ('Nadleśnictwa', nadlgeo, True)],
    podklad_poczatkowy=1,
)

dodaj_panel_kde(m, output_dir)

m.add_child(folium.LatLngPopup())

#Minimapa nawigacyjna
MiniMap(position="topleft",
        toggle_display=True).add_to(m)


output_dir.mkdir(parents=True, exist_ok=True)
file_path = output_dir / 'aplikacja_mapowa.html'
m.save(file_path)
