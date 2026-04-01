import folium
from folium.plugins import DualMap, HeatMap
import webbrowser
import os
from opacity import calculate_min_opacity_log
from Wisl_quert import query_udzial_gat
from heatmap_data import heatmap_gatunki

def compare_maps(cykl_lewa=None, cykl_prawa=None, gatunek="ŚW", drzewostany=True):
    # Oblicza udziały miaższościowe
    udzal_gat_lewa = query_udzial_gat(gatunek, cykl_lewa)
    udzal_gat_prawa = query_udzial_gat(gatunek, cykl_prawa)
    
    # Tworzy dane do mapy cieplnej
    heat_data_lewa = heatmap_gatunki(udzal_gat_lewa, cykl=cykl_lewa, drzewostany=drzewostany)
    heat_data_prawa = heatmap_gatunki(udzal_gat_prawa, cykl=cykl_prawa, drzewostany=drzewostany)
    
    # Debug
    print(f"Liczba punktów lewa (cykl {cykl_lewa}): {len(heat_data_lewa)}")
    print(f"Liczba punktów prawa (cykl {cykl_prawa}): {len(heat_data_prawa)}")
    
    # Tworzy DualMap (dwie mapy obok siebie)
    m = DualMap(
        location=[52.0, 19.0],
        zoom_start=7,
        tiles='OpenStreetMap'
    )
    
    # Dodaje HeatMap do LEWEJ mapy (m.m1)
    HeatMap(
        heat_data_lewa,
        min_opacity=calculate_min_opacity_log(len(heat_data_lewa), min_val=0.4, max_val=0.9),
        radius=15,
        blur=20,
        gradient={
            0.0: 'blue',
            0.5: 'lime',
            0.7: 'yellow',
            1.0: 'red'
        },
        name=f'Cykl {cykl_lewa}'
    ).add_to(m.m1)
    
    # Dodaje HeatMap do PRAWEJ mapy (m.m2)
    HeatMap(
        heat_data_prawa,
        min_opacity=calculate_min_opacity_log(len(heat_data_prawa), min_val=0.4, max_val=0.9),
        radius=15,
        blur=20,
        gradient={
            0.0: 'blue',
            0.5: 'lime',
            0.7: 'yellow',
            1.0: 'red'
        },
        name=f'Cykl {cykl_prawa}'
    ).add_to(m.m2)
    
    # Zapisuje i otwiera
    m.save('heatmap_gatunki.html')
    webbrowser.open('file://' + os.path.abspath('heatmap_gatunki.html'))
    print("Mapa otwarta w przeglądarce!")
    
    return m

# Wywołanie
compare_maps(cykl_lewa=1, cykl_prawa=4, gatunek="ŚW")