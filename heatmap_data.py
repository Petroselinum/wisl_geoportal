import pandas as pd
import geopandas as gpd
import numpy as np


def heatmap_gatunki(udzial_gat, cykl = 3, drzewostany=True):
    #Tworzymy dataframe
    data_gat = pd.DataFrame(udzial_gat, 
                            columns=['NR_PODPOW', 'NR_CYKLU', 'UDZIAL_MIAZSZOSC', 'reprezentatywnosc_gat', 'ZADRZEW', 'SUMA_MIAZSZOSC_gat', 'SUMA_MIAZSZOSC'])

    #Filtrujemy powierzchnie, gdzie udział miazszosci gatunku jest większy niż 50% - gatunek dominuje w drzewostanie (nie jest domieszką)
    if drzewostany:
        data_gat = data_gat.query("UDZIAL_MIAZSZOSC > 0.5 & ZADRZEW >= 0.3")

    #Wyciągamy trakty
    data_gat['NR_TRAKTU'] = data_gat['NR_PODPOW'].astype(str).str[:-3].astype(int)

    #Sumujemy reprezentatywności w danym trakcie
    data_gat_grouped = data_gat.groupby(['NR_TRAKTU', 'NR_CYKLU'],
                    as_index=False).agg({'reprezentatywnosc_gat': 'sum'})

    #Łączymy z geometrią punktów pomiarowych
    wisl_gdf = gpd.read_file("wisl_punkty.gpkg", driver="GPKG")
    wisl_gdf.NR_PUNKTU = wisl_gdf.NR_PUNKTU.astype(int).astype(str).str[:-1].astype(int)
    wisl_gdf = (wisl_gdf.rename(columns={"NR_PUNKTU": "NR_TRAKTU"})
                .drop_duplicates(subset=["NR_TRAKTU"])
                .merge(data_gat_grouped, on="NR_TRAKTU", how="inner"))

    #Filtrujemy wg numeru cyklu i konwertujemy na WGS 84
    wisl_gdf = wisl_gdf.query("NR_CYKLU >= @cykl").to_crs("EPSG:4326")

    #Ukrywamy rzeczywistą lokalizację wisl
    #wisl_gdf = przesuń_punkty_losowo(wisl_gdf, min_odleglosc=500, max_odleglosc=1000)

    #Heatmap folium
    heat_data = []
    for row in wisl_gdf.iterrows():
        lat = row[1].geometry.y 
        lon = row[1].geometry.x 
        weight = row[1].reprezentatywnosc_gat 
        
        heat_data.append([lat, lon, weight])
    
    return heat_data

def heatmap_uszkodzenia(uszkodzone, gatunek = ''):
    #Tworzymy dataframe
    if not gatunek:
        data_uszk = pd.DataFrame(uszkodzone, 
                            columns=['NR_PODPOW', 'GAT_PAN_PR', 'NASIL_USZK', 'Z', 'WAGA', 'PRZYCZ_USZK'])
    else:
        data_uszk = pd.DataFrame(uszkodzone, 
                            columns=['NR_PODPOW', 'GAT_PAN_PR', 'NASIL_USZK', 'Z', 'WAGA', 'PRZYCZ_USZK']).query("GAT_PAN_PR == @gatunek")

    #Wyciągamy trakty
    data_uszk['NR_TRAKTU'] = data_uszk['NR_PODPOW'].astype(str).str[:-3].astype(int)

    #Sumujemy uszkodzenia w danym trakcie
    data_uszk_grouped = data_uszk.groupby(['NR_TRAKTU'],
                    as_index=False).agg({'WAGA': 'sum'})

    #Łączymy z geometrią punktów pomiarowych
    wisl_gdf = gpd.read_file("wisl_punkty.gpkg", driver="GPKG")
    wisl_gdf.NR_PUNKTU = wisl_gdf.NR_PUNKTU.astype(int).astype(str).str[:-1].astype(int)
    wisl_gdf = (wisl_gdf.rename(columns={"NR_PUNKTU": "NR_TRAKTU"})
                .drop_duplicates(subset=["NR_TRAKTU"])
                .merge(data_uszk_grouped, on="NR_TRAKTU", how="inner"))

    #Konwertujemy na WGS 84
    wisl_gdf = wisl_gdf.to_crs("EPSG:4326")

    #Heatmap folium
    heat_data = []
    for row in wisl_gdf.iterrows():
        lat = row[1].geometry.y 
        lon = row[1].geometry.x 
        weight = row[1].WAGA 
        
        heat_data.append([lat, lon, weight])
    
    return heat_data

def heatmap_uszkodzenia_typy(uszkodzone, typ):
    data_uszk = pd.DataFrame(uszkodzone, 
                            columns=['NR_PODPOW', 'GAT_PAN_PR', 'NASIL_USZK', 'Z', 'WAGA', 'PRZYCZ_USZK']).query("PRZYCZ_USZK == @typ")
    
    #Wyciągamy trakty
    data_uszk['NR_TRAKTU'] = data_uszk['NR_PODPOW'].astype(str).str[:-3].astype(int)

    #Sumujemy uszkodzenia w danym trakcie
    data_uszk_grouped = data_uszk.groupby(['NR_TRAKTU'],
                    as_index=False).agg({'WAGA': 'sum'})

    #Łączymy z geometrią punktów pomiarowych
    wisl_gdf = gpd.read_file("wisl_punkty.gpkg", driver="GPKG")
    wisl_gdf.NR_PUNKTU = wisl_gdf.NR_PUNKTU.astype(int).astype(str).str[:-1].astype(int)
    wisl_gdf = (wisl_gdf.rename(columns={"NR_PUNKTU": "NR_TRAKTU"})
                .drop_duplicates(subset=["NR_TRAKTU"])
                .merge(data_uszk_grouped, on="NR_TRAKTU", how="inner"))

    #Konwertujemy na WGS 84
    wisl_gdf = wisl_gdf.to_crs("EPSG:4326")

    #Heatmap folium
    heat_data = []
    for row in wisl_gdf.iterrows():
        lat = row[1].geometry.y 
        lon = row[1].geometry.x 
        weight = row[1].WAGA 
        
        heat_data.append([lat, lon, weight])
    
    return heat_data

def heatmap_martwe_drewno(martwe, typ = 0):
    data_martwe = pd.DataFrame(martwe, 
                            columns=['NR_Traktu', 'TYP', 'SR_MIAZSZOSC'])

    if isinstance(typ, int) and typ != 0:
            data_martwe = data_martwe.query("TYP == @typ")
    elif isinstance(typ, list):
        data_martwe = data_martwe.query("TYP in @typ")
    
    #Sumujemy martwe drewno w danym trakcie
    data_martwe_grouped = data_martwe.groupby(['NR_Traktu'],
                    as_index=False).agg({'SR_MIAZSZOSC': 'sum'})

    #Łączymy z geometrią punktów pomiarowych
    wisl_gdf = gpd.read_file("wisl_punkty.gpkg", driver="GPKG")
    wisl_gdf.NR_PUNKTU = wisl_gdf.NR_PUNKTU.astype(int).astype(str).str[:-1].astype(int)
    wisl_gdf = (wisl_gdf.rename(columns={"NR_PUNKTU": "NR_Traktu"})
                .drop_duplicates(subset=["NR_Traktu"])
                .merge(data_martwe_grouped, on="NR_Traktu", how="inner"))

    #Konwertujemy na WGS 84
    wisl_gdf = wisl_gdf.to_crs("EPSG:4326")

    #Heatmap folium
    heat_data = []
    for row in wisl_gdf.iterrows():
        lat = row[1].geometry.y 
        lon = row[1].geometry.x 
        weight = np.log1p(row[1].SR_MIAZSZOSC)
        
        heat_data.append([lat, lon, weight])
    
    return heat_data