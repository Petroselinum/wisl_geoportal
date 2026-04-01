import folium
from folium.plugins import HeatMap, GroupedLayerControl, MiniMap, Search
from folium import Element
import webbrowser
import os
from opacity import calculate_min_opacity_log
from Wisl_quert import query_udzial_gat, query_drzewostany_uszk, martwe_drewno
from heatmap_data import heatmap_gatunki, heatmap_uszkodzenia, heatmap_uszkodzenia_typy, heatmap_martwe_drewno
from data import wisl_rdlp_info
import geopandas as gpd
import pandas as pd
from branca.colormap import linear
import altair as alt
from data import zasob_time_rdlp
from time_heatmaps import timelapse

cykl = 4
max_zoom = 9

slownik_gatunkow = {
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

gatunek = ['SO','ŚW','JD','MD','DB','BK','GB','BRZ','OL','JS','LP','JW']

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


# ESA WorldCover 2021 przez WMS
folium.WmsTileLayer(
    url="https://services.terrascope.be/wms/v2",
    layers="WORLDCOVER_2021_MAP",
    fmt="image/png",
    transparent=True,
    name="ESA WorldCover 2021 WMS",
    attr="ESA WorldCover",
    opacity=1,
    min_zoom=6,
    max_zoom=max_zoom,
    overlay=False
).add_to(m)

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
    <img src="WISL_logo_opis.png" 
         style="width: 100%; height: 100%; object-fit: contain;">
</div>
'''

m.get_root().html.add_child(Element(logo_html))

#Nadleśnictwa

nadlesnictwa = gpd.read_file('nadlesnictwa_simple.geojson')

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

rdlp = gpd.read_file('rdlp.geojson')
rdlp = rdlp.rename(columns={'NAZWA': 'RDLP'})

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

krainy = gpd.read_file('krainy.geojson')

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

wojewodztwa = gpd.read_file('wojewodztwa.geojson')

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
kraj = gpd.read_file('kraj_granica.geojson')

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
gdf = gpd.read_file('rdlp.geojson')
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
# Heatmapa z wagami
#################################################
def col_gat(drzewostany = True):
    collection = []

    for gat in gatunek:
        udzal_gat = query_udzial_gat(gat, cykl)
        heat_data = heatmap_gatunki(udzal_gat, cykl=cykl, drzewostany=drzewostany)

        fg = folium.FeatureGroup(name=slownik_gatunkow[gat], show=False)

        HeatMap(
            heat_data,
            min_opacity=calculate_min_opacity_log(len(heat_data), min_val=0.4, max_val=0.9),
            radius=15,
            blur=20,
            gradient={
                0.0: 'blue',
                0.5: 'lime',
                0.7: 'yellow',
                1.0: 'red'
            }
        ).add_to(fg)
        fg.add_to(m)
        collection.append(fg)

    return collection


drzewostany_collection = col_gat(drzewostany=True)
gatunek_collection = col_gat(drzewostany=False)


legend_html = '''
<div style="position: fixed; 
            bottom: 50px; left: 10px; width: 150px; 
            background-color: white; border:2px solid grey; z-index:9999; 
            font-size:14px; padding: 15px; border-radius: 8px;
            box-shadow: 3px 3px 10px rgba(0,0,0,0.4);">
    <p style="margin: 5px 0; font-weight: bold;">Koncentracja:</p>
    <div style="background: linear-gradient(to right, 
                blue 0%, lime 50%, yellow 70%, red 100%); 
                height: 25px; width: 100%; border: 1px solid #999; 
                border-radius: 3px;"></div>
    <div style="display: flex; justify-content: space-between; 
                font-size: 11px; margin-top: 5px; color: #555;">
        <span>niska</span>
        <span style="text-align: right;">wysoka</span>
    </div>
</div>
'''
"""
map_id = m.get_name()
heatmap_id = heatmap.get_name()
"""
js_script = """
<script>
    var map = {map_id};
    var heatLayer = {heatmap_id};

    map.on('zoomend', function() {{
        var currentZoom = map.getZoom();
        if (currentZoom >= 12) {{
            if (map.hasLayer(heatLayer)) {{
                map.removeLayer(heatLayer);
            }}
        }} else {{
            if (!map.hasLayer(heatLayer)) {{
                map.addLayer(heatLayer);
            }}
        }}
    }});
</script>
"""

uszk_collection = []

uszk = query_drzewostany_uszk(cykl, nasil_uszk=6)

for gat in [''] + gatunek:
    heat_data_uszk = heatmap_uszkodzenia(uszk, gatunek=gat)

    if gat == '':
        fg_uszk = folium.FeatureGroup(name='wszystkie', show=False)
    else:
        fg_uszk = folium.FeatureGroup(name=slownik_gatunkow[gat], show=False)

    HeatMap(
    heat_data_uszk,
    min_opacity=calculate_min_opacity_log(len(heat_data_uszk), min_val=0.4, max_val=0.9),
    radius=15,
    name='Mapa cieplna drzewostanów uszkodzonych',
    blur=20,
        gradient={
            0.0: 'blue',
            0.5: 'lime',
            0.7: 'yellow',
            1.0: 'red'
        }
    ).add_to(fg_uszk)
    fg_uszk.add_to(m)
    uszk_collection.append(fg_uszk)


uszkodzenia = {
    11: "Opieńkowa zgnilizna korzeni",
    12: "Huba korzeni",
    13: "Owady, szkodniki pierwotne",
    14: "Inne choroby infekcyjne",
    15: "Wiatr",
    16: "Pożar",
    17: "Zwierzyna spałowanie",
    18: "Zwierzyna zgryzanie",
19: "Zwierzyna inne",
20: "Górnictwo",
21: "Śnieg (okiść)",
22: "Inne",
23: "Zalanie",
24: "Bezpośrednie działanie człowieka",
25: "Zanieczyszczenia powietrza",
26: "Wiele czynników sprawczych",
27: "Owady, szkodniki wtórne",
28: "Inne owady",
29: "Konkurencja",
30: "Niezydentyfikowane",
31: "Obniżenie poziomu wód gruntowych",
32: "Jemioła"}

uszk_collection_typ = []

uszkodz = query_drzewostany_uszk(cykl, nasil_uszk=5)

for uszk in uszkodzenia.keys():
    heat_data_uszk = heatmap_uszkodzenia_typy(uszkodz, typ=uszk)

    fg_uszk = folium.FeatureGroup(name=uszkodzenia[uszk], show=False)

    HeatMap(
    heat_data_uszk,
    min_opacity=calculate_min_opacity_log(len(heat_data_uszk), min_val=0.4, max_val=0.9),
    radius=15,
    name='Mapa cieplna drzewostanów uszkodzonych',
    blur=20,
        gradient={
            0.0: 'blue',
            0.5: 'lime',
            0.7: 'yellow',
            1.0: 'red'
        }
    ).add_to(fg_uszk)
    fg_uszk.add_to(m)
    uszk_collection_typ.append(fg_uszk)

# Martwe drewno
martwe = {'Wszystkie': 0,
          'Leżące': [1, 2, 3],
          'Posusz': 4,
          'Złomy': 5}

wisl_mar= martwe_drewno(cykl)
martwe_collection = []

for key, val in martwe.items():
    heat_data_mar = heatmap_martwe_drewno(wisl_mar, typ=val)

    fg_mar = folium.FeatureGroup(name=key, show=False)

    HeatMap(
    heat_data_mar,
    min_opacity=calculate_min_opacity_log(len(heat_data_mar), min_val=0.4, max_val=0.9),
    radius=15,
    name='Mapa cieplna martwego drewna',
    blur=20,
        gradient={
            0.0: 'blue',
            0.5: 'lime',
            0.7: 'yellow',
            1.0: 'red'
        }
    ).add_to(fg_mar)
    fg_mar.add_to(m)
    martwe_collection.append(fg_mar)


#m.get_root().html.add_child(folium.Element(js_script))
m.get_root().html.add_child(folium.Element(legend_html))
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
            'RDLP - Wykresy': [fg_zasobnosc],
            'Zasięgi drzewostanów:': drzewostany_collection,
            'Zasięgi gatunków:': gatunek_collection,
            'Zasięgi drzewostanów uszkodzonych:': uszk_collection,
            'Zasięgi wg typów uszkodzeń:': uszk_collection_typ,
            'Martwe drewno': martwe_collection},
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


m.save('heatmap_gatunki.html')
webbrowser.open('file://' + os.path.abspath('heatmap_gatunki.html'))
print("Mapa otwarta w przeglądarce!")