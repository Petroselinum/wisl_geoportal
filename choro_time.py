from data import zasob_time_rdlp
import geopandas as gpd
import plotly.express as px
import json
import webbrowser
import os

df = zasob_time_rdlp()
gdf = gpd.read_file('rdlp.geojson')
gdf = gdf.merge(df, left_on='NAZWA', right_on='rdlp', how='inner')
# GeoJSON z ID jako nazwa RDLP (tylko unikalne geometrie)
gdf_unique = gdf.drop_duplicates('NAZWA')[['NAZWA', 'geometry']]
geojson = json.loads(gdf_unique.to_json())
for feature in geojson['features']:
    feature['id'] = feature['properties']['NAZWA']

fig = px.choropleth_map(
    df,
    geojson=geojson,
    locations='rdlp',
    color='zasobnosc',
    animation_frame='lata',
    color_continuous_scale='YlGn',
    range_color=[df['zasobnosc'].min(), df['zasobnosc'].max()],
    labels={'zasobnosc': 'Zasobność lasów', 'rdlp': 'RDLP', 'lata': 'Okres'},
    title='Zasobność lasów wg RDLP',
    map_style='open-street-map',  # dostępne bez tokena
    zoom=5,
    center=dict(lat=52.0, lon=19.0),
    opacity=0.8,
)

fig.update_layout(
    coloraxis_colorbar=dict(title='Zasobność<br>[m³/ha]'),
    margin=dict(l=0, r=0, t=40, b=0),
)


fig.write_html('animacja_rdlp.html')


webbrowser.open('file://' + os.path.abspath('animacja_rdlp.html'))