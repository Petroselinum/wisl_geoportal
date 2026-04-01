import folium
import folium.plugins
import geopandas as gpd
import pandas as pd
import webbrowser
import os
from WislDb import DRZEWA_OD_7, OBL_DRZEWA_OD_7, OBL_ADRES_POW, ADRES_POW, DRZEWA_MARTWE, OBL_DRZEWA_MARTWE, engine
from sqlmodel import Session, select, func, Integer

def query_udzial_gat(gatunek: str, rok_start: int, rok_end: int):
    # Nawiązanie połączenia z bazą WISL
    with Session(engine) as session:
        # Pobiera unikalne kombinacje NR_PODPOW i NR_CYKLU dla danego gatunku
        powierzchnie_z_gatunkiem = select(
            DRZEWA_OD_7.NR_PODPOW,
            DRZEWA_OD_7.NR_CYKLU
        ).where(
            DRZEWA_OD_7.GAT == gatunek
        ).distinct().subquery()
        
    
        pow_miazszosc = (select(
                DRZEWA_OD_7.NR_PODPOW, 
                DRZEWA_OD_7.NR_CYKLU, 
                func.sum(OBL_DRZEWA_OD_7.MIAZSZOSC).label("SUMA_MIAZSZOSC")
            )
            .join(OBL_DRZEWA_OD_7, DRZEWA_OD_7.ID == OBL_DRZEWA_OD_7.ID)
            .join(
                powierzchnie_z_gatunkiem,
                (DRZEWA_OD_7.NR_PODPOW == powierzchnie_z_gatunkiem.c.NR_PODPOW) &
                (DRZEWA_OD_7.NR_CYKLU == powierzchnie_z_gatunkiem.c.NR_CYKLU)
            )
            .where(DRZEWA_OD_7.WAR != 10)
            .group_by(DRZEWA_OD_7.NR_PODPOW, DRZEWA_OD_7.NR_CYKLU)
        .subquery())

    
        gatunek_miazszosc = (select(
                DRZEWA_OD_7.NR_PODPOW, 
                DRZEWA_OD_7.NR_CYKLU,
                OBL_ADRES_POW.ZADRZEW,
                func.sum(OBL_DRZEWA_OD_7.MIAZSZOSC).label("SUMA_MIAZSZOSC_gat"),
                pow_miazszosc.c.SUMA_MIAZSZOSC,
                (func.sum(OBL_DRZEWA_OD_7.MIAZSZOSC) / pow_miazszosc.c.SUMA_MIAZSZOSC).label('UDZIAL_MIAZSZOSC'),
                ((func.sum(OBL_DRZEWA_OD_7.MIAZSZOSC) / pow_miazszosc.c.SUMA_MIAZSZOSC) * 
                func.coalesce(OBL_ADRES_POW.ZADRZEW, 0) * 
                func.coalesce(OBL_ADRES_POW.WSP_Z, 0)).label('reprezentatywnosc_gat')
            )
            .join(OBL_DRZEWA_OD_7, DRZEWA_OD_7.ID == OBL_DRZEWA_OD_7.ID)
            .join(
                powierzchnie_z_gatunkiem,
                (DRZEWA_OD_7.NR_PODPOW == powierzchnie_z_gatunkiem.c.NR_PODPOW) &
                (DRZEWA_OD_7.NR_CYKLU == powierzchnie_z_gatunkiem.c.NR_CYKLU)
            )
            .join(pow_miazszosc,
                (DRZEWA_OD_7.NR_PODPOW == pow_miazszosc.c.NR_PODPOW) &
                (DRZEWA_OD_7.NR_CYKLU == pow_miazszosc.c.NR_CYKLU))
            .join(OBL_ADRES_POW, 
                (DRZEWA_OD_7.NR_PODPOW == OBL_ADRES_POW.NR_PODPOW) &
                (DRZEWA_OD_7.NR_CYKLU == OBL_ADRES_POW.NR_CYKLU))
            .join(ADRES_POW,
                (DRZEWA_OD_7.NR_PODPOW == ADRES_POW.NR_PODPOW) &
                (DRZEWA_OD_7.NR_CYKLU == ADRES_POW.NR_CYKLU))
            .where(DRZEWA_OD_7.GAT == gatunek,
                func.substring(ADRES_POW.DATA, 1, 4).cast(Integer) >= rok_start,
                func.substring(ADRES_POW.DATA, 1, 4).cast(Integer) <= rok_end,
                DRZEWA_OD_7.WAR != 10)
            .group_by(DRZEWA_OD_7.NR_PODPOW, 
                    DRZEWA_OD_7.NR_CYKLU,
                    pow_miazszosc.c.SUMA_MIAZSZOSC,
                    OBL_ADRES_POW.ZADRZEW,
                    OBL_ADRES_POW.WSP_Z)).subquery()
        
        # Odrzucamy powierzchnie z samymi przestojami
        gatunek_miazszosc_filtr = session.exec(select(gatunek_miazszosc.c.NR_PODPOW,
                                                    gatunek_miazszosc.c.NR_CYKLU,
                                                    gatunek_miazszosc.c.UDZIAL_MIAZSZOSC,
                                                    gatunek_miazszosc.c.reprezentatywnosc_gat,
                                                    gatunek_miazszosc.c.ZADRZEW,
                                                    gatunek_miazszosc.c.SUMA_MIAZSZOSC_gat,
                                                    gatunek_miazszosc.c.SUMA_MIAZSZOSC)
                                            .where(gatunek_miazszosc.c.reprezentatywnosc_gat > 0)).all()
    return gatunek_miazszosc_filtr

def heatmap_gatunki(udzial_gat, drzewostany=True):
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
    wisl_gdf = wisl_gdf.to_crs("EPSG:4326")

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


def timelapse(gat, drzewostany, rok_ostatni):

    heat_data_time = []
    heat_data_time_index = []

    for i in range(2005, rok_ostatni - 4 + 1):
        sql_res = query_udzial_gat(gat, i, i+4)
        heat_data = heatmap_gatunki(sql_res, drzewostany=drzewostany)
        heat_data_time.append(heat_data)
        heat_data_time_index.append(str(i) + "-" + str(i+4))
    
    return heat_data_time, heat_data_time_index


if __name__ == '__main__':

    rok_ostatni = 2024
    gat = "JS"
    drzewostany=True

    # Mapa
    m = folium.Map(
        location=[52.0, 19.0],  # centrum Polski
        zoom_start=7,
        max_zoom=8,
        min_zoom=6,
        control_scale=True,
        tiles='OpenStreetMap'
    )

    # Dodajemy heatmapę do mapy

    heat_data_time, heat_data_time_index = timelapse(gat=gat, drzewostany=drzewostany, rok_ostatni=rok_ostatni)


    hm = folium.plugins.HeatMapWithTime(heat_data_time, 
                                        index=heat_data_time_index, 
                                        auto_play=True, 
                                        max_opacity=0.5,
                                        use_local_extrema=False
                                        )
    hm.add_to(m)


    m.save("heatmap_gatunku.html")
    webbrowser.open('file://' + os.path.abspath('heatmap_gatunku.html'))