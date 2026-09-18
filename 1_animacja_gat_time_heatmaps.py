from pathlib import Path
import folium
import folium.plugins
import os
from WislDb import DRZEWA_OD_7, OBL_DRZEWA_OD_7, OBL_ADRES_POW, ADRES_POW, DRZEWA_MARTWE, OBL_DRZEWA_MARTWE, engine
from sqlmodel import Session, select, func, Integer
from heatmap_data import heatmap_gatunki
from Wisl_quert import STATUS_GRUNTU_MAX

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
                DRZEWA_OD_7.WAR != 10,
                ADRES_POW.STATUS_GRUNTU <= STATUS_GRUNTU_MAX)
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


def timelapse(gat, drzewostany, rok_ostatni):

    heat_data_time = []
    heat_data_time_index = []

    for i in range(2005, rok_ostatni - 4 + 1):
        sql_res = query_udzial_gat(gat, i, i+4)
        # cykl=1: query_udzial_gat już filtruje wg zakresu lat (rok_start-rok_end),
        # więc nie chcemy dodatkowego obcinania wg NR_CYKLU
        heat_data = heatmap_gatunki(sql_res, cykl=1, drzewostany=drzewostany)
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

    if not os.path.exists('wygerenowane_animacje'):
        os.makedirs('wygerenowane_animacje')

    output_dir = Path('wygerenowane_animacje')
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f'animacja_heatmap_{gat}.html'
    m.save(file_path)