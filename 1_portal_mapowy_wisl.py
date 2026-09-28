import folium
from folium.plugins import GroupedLayerControl, MiniMap, Search
from folium import Element
from data import wisl_rdlp_info
import geopandas as gpd
import pandas as pd
import shapely
from branca.colormap import linear
import altair as alt
from data import zasob_time_rdlp
from pathlib import Path
from portal_kde import dodaj_panel_kde

#Aplikację należy uruchamiać na lokalnym serverze (z katalogu projektu):
# python -m http.server 8000
# http://localhost:8000/wygerenowane_animacje/aplikacja_mapowa.html
#
# Warstwy analityczne pochodzą z plików GeoJSON zapisanych przez skrypty
# kde_*.py (KDE_gatunki, KDE_zasobnosc, KDE_martwe_drewno, KDE_uszkodzenia,
# KDE_uszkodzenia_ryzyko) - przed zbudowaniem portalu trzeba je przeliczyć.
# Wybiera się je w panelu "Analizy KDE" (portal_kde.py), nie w LayerControl.

cykl = 4
max_zoom = 9
output_dir = Path('wygerenowane_animacje')

# Uproszczenie warstw wektorowych osadzanych w HTML. rdlp.geojson trafia do
# HTML 7 razy (opis, 5 kartogramów, wykresy), a krainy.geojson ma pełną
# szczegółowość - razem ~35 MB z ~42 MB pliku. 200 m to ~1 piksel przy
# max_zoom 9 (~190 m/piksel), więc różnica jest niewidoczna.
TOLERANCJA_WARSTW_M = 200


def uprosc_warstwe(gdf, tolerancja_m=TOLERANCJA_WARSTW_M):
    """
    Upraszcza warstwę poligonów stykających się ze sobą (RDLP, krainy).
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
    tiles='OpenStreetMap',
    min_lat=min_lat,
    max_lat=max_lat,
    min_lon=min_lon,
    max_lon=max_lon,
    max_bounds=True
)


# Ortofotomapa
folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr='Esri',
    name='Ortofotomapa',
    overlay=False,
    max_zoom=max_zoom,
    min_zoom=6,
).add_to(m)

folium.TileLayer(
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

#RDLP

fields = ["RDLP", "Powierzchnia lasów\nw zarządzie PGL LP [tys. ha]", 
                                    "Miąższość [mln m³ grubizny brutto]\nlasów w zarządzie PGL LP", 
                                    "Zasobność [m³/ha grubizny brutto] lasów w zarządzie PGL LP", 
                                    "Średni wiek lasów",
                                    "Martwe drewno [m³/ha grubizny brutto]"]

popup = folium.GeoJsonPopup(fields=fields,
                            aliases=["RDLP:", "Powierzchnia lasów w PGL LP(tys. ha):", 
                                     "Miąższość w PGL LP(mln m³):", 
                                     "Zasobność w PGL LP(m³/ha):", 
                                     "Średni wiek lasów w PGL LP(lata):",
                                     "Martwe drewno [m³/ha grubizny brutto]:"],
                            localize=True,
                            labels=True
                            )

rdlp_granice = uprosc_warstwe(gpd.read_file('data/rdlp.geojson'))
rdlp = rdlp_granice.rename(columns={'NAZWA': 'RDLP'})

rdlp_info = pd.DataFrame(wisl_rdlp_info(cykl))

rdlp['RDLP'] = rdlp['RDLP'].astype(str)
rdlp_info['RDLP'] = rdlp_info['RDLP'].astype(str)

rdlp = rdlp.merge(rdlp_info, on='RDLP', how='inner')

rdlp_layer = folium.GeoJson(
    rdlp,
    name='RDLP - Opis',
    style_function=lambda feature: {
        'fillColor': 'blue',
        'fillOpacity': 0.1,
        'color': 'blue',
        'weight': 1.5,
    },
    highlight_function=lambda feature: {
        'fillColor': 'yellow',
        'fillOpacity': 0.5,
        'color': 'blue',
        'weight': 1,
    },
    popup=popup
)
rdlp_layer.add_to(m)

#Krainy

krainy = uprosc_warstwe(gpd.read_file('data/krainy.geojson'))

popup = folium.GeoJsonPopup(fields=['Kraina','Nazwa'],
                            localize=True,
                            labels=True
                            )

krainy_layer = folium.GeoJson(
    krainy,
    name='Krainy przyr.',
    style_function=lambda feature: {
        'fillColor': 'orange',
        'fillOpacity': 0.1,
        'color': 'orange',
        'weight': 1.5,
    },
    highlight_function=lambda feature: {
        'fillColor': 'yellow',
        'fillOpacity': 0.5,
        'color': 'orange',
        'weight': 1,
    },
    popup=popup,
    show = False
)
krainy_layer.add_to(m)

#województwa

wojewodztwa = gpd.read_file('data/wojewodztwa.geojson')

popup = folium.GeoJsonPopup(fields=['JPT_NAZWA_'],
                            aliases=['Województwo'],
                            localize=True,
                            labels=True
                            )

wojewodztwa_layer = folium.GeoJson(
    wojewodztwa,
    name='Województwa',
    style_function=lambda feature: {
        'fillColor': 'pink',
        'fillOpacity': 0.1,
        'color': 'pink',
        'weight': 1.5,
    },
    highlight_function=lambda feature: {
        'fillColor': 'yellow',
        'fillOpacity': 0.5,
        'color': 'pink',
        'weight': 1,
    },
    popup=popup,
    show = False
)
wojewodztwa_layer.add_to(m)

#Kraj Granica
granica_collection =[]

fg_kraj = folium.FeatureGroup(name='Wyłącz warstwę', show=False)
kraj = gpd.read_file('data/kraj_granica.geojson')

folium.GeoJson(kraj,
               name = 'Ukryj aktualną warstwę',
               show = False,
               style_function=lambda feature: {
            'fillColor': 'None',
            'fillOpacity': 0.0,
            'color': 'None',
            'weight': 1.5,
    }).add_to(fg_kraj)

granica_collection.append(fg_kraj)
fg_kraj.add_to(m)

#RDLP Choropleth

choro_collection = []
names = ["Powierzchnia lasów", "Miąższość lasów", "Zasobność lasów", "Średni wiek lasów", "Martwe drewno"]

for col, name in zip(fields[1:], names):
    colormap = linear.YlGn_09.scale(rdlp[col].min(), rdlp[col].max())
    
    rdlp_dict = rdlp.set_index("RDLP")[col]

    fg_choro = folium.FeatureGroup(name=name, show=False)

    folium.GeoJson(
        rdlp,
        name=f"RDLP - {name}",
        show=True,
        style_function=lambda feature, cm=colormap, d=rdlp_dict: {
            "fillColor": cm(d[feature["properties"]["RDLP"]]),
            "color": "black",
            "weight": 1,
            "fillOpacity": 0.9,
        },
        highlight_function=lambda feature: {
        "fillColor": "yellow",
        "color": "black"},
        tooltip=folium.GeoJsonTooltip(
        fields=['RDLP', col], localize=True)
    ).add_to(fg_choro)

    fg_choro.add_to(m)
    choro_collection.append(fg_choro)

# Wykresy

df = zasob_time_rdlp()
gdf = rdlp_granice
gdf_unique = gdf.drop_duplicates('NAZWA')

def make_chart(rdlp_name, df):
    data = df[df['rdlp'] == rdlp_name][['lata', 'zasobnosc']].copy()
    chart = alt.Chart(data).mark_line(point=True).encode(
        x=alt.X('lata:O', title='Okres',
                axis=alt.Axis(labelAngle=-45, labelOverlap=False)),
        y=alt.Y('zasobnosc:Q', title='Zasobność [m³/ha]', scale=alt.Scale(zero=False)),
        tooltip=['lata', 'zasobnosc']
    ).properties(
        title=rdlp_name,
        width=300,
        height=200
    )
    return chart

def style_fn(feature):
    return {'fillColor': '#228B22', 'color': 'black', 'weight': 1, 'fillOpacity': 0.4}


# FeatureGroup dla warstwy z wykresami
fg_zasobnosc = folium.FeatureGroup(name='Zasobność lasów', show=False)

for _, row in gdf_unique.iterrows():
    name = row['NAZWA']
    chart = make_chart(name, df)
    popup = folium.Popup(max_width=400)
    folium.VegaLite(chart, width=350, height=250).add_to(popup)
    folium.GeoJson(
        row['geometry'].__geo_interface__,
        style_function=style_fn,
        popup=popup,
        tooltip=name,
    ).add_to(fg_zasobnosc)

fg_zasobnosc.add_to(m)

#################################################
# Warstwy KDE (panel Temat / Wariant / Okres)
#################################################
dodaj_panel_kde(m, output_dir)

m.add_child(folium.LatLngPopup())

#Wyszukiwarka miejscowości
folium.plugins.Geocoder().add_to(m)

# Wstrzyknięcie JS zmieniającego placeholder
napis_w_oknie = """
<script>
document.addEventListener("DOMContentLoaded", function() {
    var input = document.querySelector('.leaflet-control-geocoder input');
    if (input) {
        input.placeholder = 'Wyszukaj adres...';
    }
});
</script>
"""
m.get_root().html.add_child(folium.Element(napis_w_oknie))

#Minimapa nawigacyjna
MiniMap(position="topleft",
        toggle_display=True).add_to(m)


folium.LayerControl(collapsed=False).add_to(m)

GroupedLayerControl(
    groups={'Wyłącz wyświetlanie': granica_collection,
            'RDLP - choropleth': choro_collection,
            'RDLP - Wykresy': [fg_zasobnosc]},
    collapsed=False,
    exclusive_groups=False
).add_to(m)

scrol = """
<style>
.leaflet-control-layers-list {
    overflow-y: visible !important;
    max-height: none !important;
}

.leaflet-control-layers,
.leaflet-control-layers-group {
    width: 250px !important;
    min-width: 250px !important;
}

.leaflet-control-layers-expanded {
    display: none !important;
}

#layers-hover-wrapper {
    position: fixed;
    top: 10px;
    right: 10px;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
}

#layers-toggle-btn {
    width: 34px;
    height: 34px;
    background: white;
    border: 2px solid rgba(0,0,0,0.2);
    border-radius: 4px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 1px 5px rgba(0,0,0,0.3);
}

#layers-toggle-btn svg {
    width: 20px;
    height: 20px;
    fill: none;
    stroke: #555;
    stroke-width: 2;
    stroke-linecap: round;
}

#layers-hover-wrapper .leaflet-control-layers {
    display: none;
    margin: 0 !important;
}

#layers-hover-wrapper:hover .leaflet-control-layers {
    display: block !important;
}

/* === SIMPLE LAYER CONTROL — scroll === */
#simple-layer-control .leaflet-control-layers-list {
    overflow-y: auto !important;
    max-height: 40vh !important;
    padding-right: 5px;
}

/* === GROUPED LAYER CONTROL === */
#grouped-layer-control .leaflet-control-layers-overlays {
    max-height: 50vh;
    overflow-y: auto;
    padding-right: 5px;
}

#grouped-layer-control input[type="checkbox"] {
    display: none !important;
}

#grouped-layer-control label {
    cursor: pointer;
    padding: 3px 6px;
    border-radius: 4px;
    display: block;
    transition: background 0.15s;
    user-select: none;
}

#grouped-layer-control label:hover {
    background: #f0f0f0;
}

#grouped-layer-control label.active-layer {
    background: #c8e6c9;
    font-weight: bold;
}

</style>

<script>
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(function() {

        var controls = document.querySelectorAll('.leaflet-control-layers');
        if (controls.length === 0) return;

        var wrapper = document.createElement('div');
        wrapper.id = 'layers-hover-wrapper';

        var btn = document.createElement('div');
        btn.id = 'layers-toggle-btn';
        btn.innerHTML = `
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <line x1="3" y1="6"  x2="21" y2="6"/>
                <line x1="3" y1="12" x2="21" y2="12"/>
                <line x1="3" y1="18" x2="21" y2="18"/>
            </svg>`;
        wrapper.appendChild(btn);

        var groupedControl = null;
        var simpleControl = null;

        controls.forEach(function(ctrl) {
            ctrl.parentNode.removeChild(ctrl);
            ctrl.classList.add('leaflet-control-layers-expanded');

            // GroupedLayerControl ma elementy z klasą leaflet-control-layers-group
            var hasGroups = ctrl.querySelector('.leaflet-control-layers-group') !== null;

            if (hasGroups) {
                groupedControl = ctrl;
                ctrl.id = 'grouped-layer-control';
            } else {
                simpleControl = ctrl;
                ctrl.id = 'simple-layer-control';
            }

            wrapper.appendChild(ctrl);
        });

        document.body.appendChild(wrapper);

        // Fallback
        if (!groupedControl) {
            var allC = wrapper.querySelectorAll('.leaflet-control-layers');
            groupedControl = allC[allC.length - 1];
            if (groupedControl) groupedControl.id = 'grouped-layer-control';
        }

        if (!simpleControl) {
            var allC = wrapper.querySelectorAll('.leaflet-control-layers');
            simpleControl = allC[0];
            if (simpleControl && !simpleControl.id) simpleControl.id = 'simple-layer-control';
        }

        if (!groupedControl) return;

        // ── RADIO BEZ CHECKBOXÓW dla GroupedLayerControl ──────────
        function setupRadio() {
            var labels = groupedControl.querySelectorAll('label');
            if (labels.length === 0) {
                setTimeout(setupRadio, 300);
                return;
            }

            labels.forEach(function(label) {
                label.addEventListener('click', function(e) {
                    e.preventDefault();

                    var checkbox = label.querySelector('input[type="checkbox"]');
                    if (!checkbox) return;

                    var wasActive = label.classList.contains('active-layer');

                    groupedControl.querySelectorAll('label').forEach(function(lbl) {
                        var cb = lbl.querySelector('input[type="checkbox"]');
                        if (cb && cb.checked) cb.click();
                        lbl.classList.remove('active-layer');
                    });

                    if (!wasActive) {
                        checkbox.click();
                        label.classList.add('active-layer');
                    }
                });
            });
        }

        setTimeout(setupRadio, 500);

    }, 1000);
});
</script>
"""

m.get_root().html.add_child(folium.Element(scrol))

output_dir.mkdir(parents=True, exist_ok=True)
file_path = output_dir / 'aplikacja_mapowa.html'
m.save(file_path)
