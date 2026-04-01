import altair as alt
import folium
from folium.plugins import GroupedLayerControl
from data import zasob_time_rdlp
import geopandas as gpd

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

m = folium.Map(location=[52.0, 19.0], zoom_start=6)

# FeatureGroup dla warstwy z wykresami
fg_zasobnosc = folium.FeatureGroup(name='Zasobność lasów', show=True)

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

GroupedLayerControl(
    groups={'Warstwy': [fg_zasobnosc]},
    collapsed=False,
).add_to(m)

m.save('mapa_popup.html')

import webbrowser, os
webbrowser.open('file://' + os.path.abspath('mapa_popup.html'))