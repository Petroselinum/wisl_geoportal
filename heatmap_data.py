import pandas as pd
import geopandas as gpd
import numpy as np


def _wyciagnij_nr_trakt(row):
    """
    Wyciąga numer traktu z wiersza wyniku zapytania SQL, niezależnie od
    tego, czy zwraca on kolumnę NR_PUNKTU czy NR_PODPOW (obie konwencje
    występują w bazie WISL w różnych tabelach). Rzuca czytelny błąd
    z listą dostępnych kolumn, jeśli żadnej z nich nie znajdzie — żeby
    nie failować cichym/mylącym AttributeError.
    """
    mapping = row._mapping if hasattr(row, "_mapping") else row
    if "NR_PUNKTU" in mapping:
        return int(str(int(mapping["NR_PUNKTU"]))[:-1])
    if "NR_PODPOW" in mapping:
        return int(str(int(mapping["NR_PODPOW"]))[:-3])
    dostepne = list(mapping.keys())
    raise KeyError(
        "Nie znaleziono kolumny NR_PUNKTU ani NR_PODPOW w wyniku "
        f"query_all_wisl_plots(). Dostępne kolumny: {dostepne}. "
        "Popraw _wyciagnij_nr_trakt() w heatmap_data.py."
    )


def heatmap_tlo(surowe_wisl):
    """
    Tło — wszystkie zbadane powierzchnie WISL w danym cyklu (niezależnie
    od gatunku czy uszkodzenia), z jednakową wagą 1.0 na trakt.

    Służy jako mianownik przy liczeniu ryzyka względnego: gęstość
    zdarzenia (np. uszkodzeń) podzielona przez gęstość tła pokazuje,
    gdzie zdarzenie występuje częściej niż wynikałoby to z samej gęstości
    próbkowania WISL w danym miejscu — w przeciwieństwie do surowej gęstości
    zdarzenia, która przy zjawisku rozproszonym po całym kraju (jak
    uszkodzenia) prawie zawsze obejmuje niemal cały kraj.

    Parametr surowe_wisl: wynik query_all_wisl_plots(nr_cykl) — lista
    wierszy SQL z (m.in.) numerem punktu/podpowierzchni.
    """
    nr_traktu = [_wyciagnij_nr_trakt(row) for row in surowe_wisl]
    df_tlo = pd.DataFrame({"NR_TRAKTU": nr_traktu}).drop_duplicates(subset=["NR_TRAKTU"])

    #Łączymy z geometrią punktów pomiarowych (ten sam wzorzec co w innych funkcjach heatmap_*)
    wisl_gdf = gpd.read_file("data/wisl_punkty.gpkg", driver="GPKG")
    wisl_gdf.NR_PUNKTU = wisl_gdf.NR_PUNKTU.astype(int).astype(str).str[:-1].astype(int)
    wisl_gdf = (wisl_gdf.rename(columns={"NR_PUNKTU": "NR_TRAKTU"})
                .drop_duplicates(subset=["NR_TRAKTU"])
                .merge(df_tlo, on="NR_TRAKTU", how="inner"))

    wisl_gdf = wisl_gdf.to_crs("EPSG:4326")

    heat_data = []
    for row in wisl_gdf.itertuples():
        heat_data.append([row.geometry.y, row.geometry.x, 1.0])

    return heat_data


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
    wisl_gdf = gpd.read_file("data/wisl_punkty.gpkg", driver="GPKG")
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
    wisl_gdf = gpd.read_file("data/wisl_punkty.gpkg", driver="GPKG")
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
    wisl_gdf = gpd.read_file("data/wisl_punkty.gpkg", driver="GPKG")
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
    wisl_gdf = gpd.read_file("data/wisl_punkty.gpkg", driver="GPKG")
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