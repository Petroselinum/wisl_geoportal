from WislDb import DRZEWA_OD_7, OBL_DRZEWA_OD_7, OBL_ADRES_POW, ADRES_POW, DRZEWA_MARTWE, OBL_DRZEWA_MARTWE, engine
from sqlmodel import Session, select, func, cast, Float, Integer, literal_column, text
import geopandas as gpd
import math

def query_udzial_gat(gatunek: str, nr_cykl: int = None):
    # Nawiązanie połączenia z bazą WISL
    with Session(engine) as session:
        # Pobiera unikalne kombinacje NR_PODPOW i NR_CYKLU dla danego gatunku
        powierzchnie_z_gatunkiem = select(
            DRZEWA_OD_7.NR_PODPOW,
            DRZEWA_OD_7.NR_CYKLU
        ).where(
            DRZEWA_OD_7.GAT == gatunek
        ).distinct().subquery()
        
        # Oblicza całkowitą MIAZSZOSC dla każdej kombinacji NR_PODPOW i NR_CYKLU z pominięciem przestoi
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

        #Oblicza stopień reprezentatywności gatunku na podstawie udziału miazszosci, zadrzewienia i współczynnika Z
        #Zwraca 1 dla powierzchni niepodzielonej na podpowierzchnie z zadrzewieniem 1 i współczynnikiem Z 1
        #Zwraca 0 dla powierzchni z samymi przestojami
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
            .where(DRZEWA_OD_7.GAT == gatunek,
                DRZEWA_OD_7.NR_CYKLU == nr_cykl,
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

def query_drzewostany_uszk(nr_cykl: int = None):
    with Session(engine) as session:
        powierzchnie_uszk = session.exec(
                                select(
                                   ADRES_POW.NR_PUNKTU, 
                                   ADRES_POW.NR_PODPOW,
                                   ADRES_POW.GAT_PAN_PR,
                                   OBL_ADRES_POW.WSP_Z,
                                   func.coalesce(ADRES_POW.NASIL_USZK, 0).label('NASIL_USZK'),
                                   ADRES_POW.PRZYCZ_USZK) \
            .join(OBL_ADRES_POW,
                (ADRES_POW.NR_PODPOW == OBL_ADRES_POW.NR_PODPOW) &
                (ADRES_POW.NR_CYKLU == OBL_ADRES_POW.NR_CYKLU)) \
            .where(ADRES_POW.NR_CYKLU == nr_cykl,
                   ADRES_POW.R_POW_PR == 1)
        ).all()
    return powierzchnie_uszk

#Martwe - średnia ważona wsp Z w trakcie

def martwe_drewno(nr_cykl: int = None):
    # MIAZSZOSC w OBL_DRZEWA_MARTWE to surowa objętość zmierzona na kole
    # próbnym o stałym promieniu 11,28 m (pole = pi*11,28^2 ~= 399,73 m^2 =
    # ~0,04 ha). WSP_Z to udział podpowierzchni w pełnej powierzchni próbnej
    # (nie zawsze 1,0 - schematyczna siatka WISL: czasem tylko część
    # podpowierzchni faktycznie wypada w lesie). WSP_Z * pole_kola to więc
    # RZECZYWIŚCIE REPREZENTOWANA powierzchnia danej podpowierzchni - nie
    # waga, przez którą mnoży się samą objętość.
    #
    # Poprawny estymator gęstości (m3/ha) na trakt to:
    #   SUMA surowej objętości / (SUMA_WSP_Z * pole_jednego_kola_w_ha)
    # czyli "całkowita zmierzona objętość" / "całkowita reprezentowana
    # powierzchnia" - NIE średnia ważona objętości przez WSP_Z (to dwie
    # różne rzeczy: ważenie objętości przez WSP_Z przed uśrednieniem
    # systematycznie zaniża wkład podpowierzchni o niskiej reprezentatywności,
    # nawet jeśli akurat na nich znaleziono dużo martwego drewna - sprawdzone
    # przykładem liczbowym: 66,7 vs 133,4 m3/ha dla tych samych danych,
    # w zależności od tego, która wersja wzoru jest użyta).
    PRZELICZNIK_NA_HEKTAR = 10000.0 / (math.pi * 11.28 ** 2)

    with Session(engine) as session:
        NR_Traktu_z = (OBL_ADRES_POW.NR_PODPOW // literal_column('1000')).label('NR_Traktu')
        z_pow_les = (
            select(
                NR_Traktu_z,
                cast(func.sum(OBL_ADRES_POW.WSP_Z), Float).label('SUMA_WSP_Z')
            )
            .join(ADRES_POW,
                (ADRES_POW.NR_PODPOW == OBL_ADRES_POW.NR_PODPOW) &
                (ADRES_POW.NR_CYKLU == OBL_ADRES_POW.NR_CYKLU))
            .where(
                OBL_ADRES_POW.NR_CYKLU == nr_cykl,
                ADRES_POW.R_POW_PR.in_([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
            )
            .group_by(NR_Traktu_z)
        ).cte('z_pow_les')

        NR_Traktu_m = (OBL_ADRES_POW.NR_PODPOW // literal_column('1000')).label('NR_Traktu')
        martwe = (
            select(
                NR_Traktu_m,
                DRZEWA_MARTWE.TYP,
                cast(func.sum(OBL_DRZEWA_MARTWE.MIAZSZOSC), Float).label('MIAZSZOSC_martwe_pow')
            )
            .join(OBL_DRZEWA_MARTWE, DRZEWA_MARTWE.ID == OBL_DRZEWA_MARTWE.ID)
            .join(OBL_ADRES_POW,
                (DRZEWA_MARTWE.NR_PODPOW == OBL_ADRES_POW.NR_PODPOW) &
                (DRZEWA_MARTWE.NR_CYKLU == OBL_ADRES_POW.NR_CYKLU))
            .where(DRZEWA_MARTWE.NR_CYKLU == nr_cykl)
            .group_by(NR_Traktu_m, OBL_ADRES_POW.NR_PODPOW, DRZEWA_MARTWE.TYP)
        ).cte('martwe')

        wynik = session.exec(
            select(
                z_pow_les.c.NR_Traktu,
                martwe.c.TYP,
                ((func.coalesce(func.sum(martwe.c.MIAZSZOSC_martwe_pow), 0) / z_pow_les.c.SUMA_WSP_Z)
                 * PRZELICZNIK_NA_HEKTAR).label('SR_MIAZSZOSC'),
                z_pow_les.c.SUMA_WSP_Z
            )
            .select_from(z_pow_les)
            .join(martwe, martwe.c.NR_Traktu == z_pow_les.c.NR_Traktu, isouter=True)
            .group_by(z_pow_les.c.NR_Traktu, martwe.c.TYP, z_pow_les.c.SUMA_WSP_Z)
        ).all()

        return wynik


def query_all_wisl_plots(nr_cykl):
    with Session(engine) as session:
        sql = text(f'''
            SELECT * FROM "PUNKTY_TRAKTU" AS pk
            INNER JOIN "ADRES_POW" as ap on ap."NR_PUNKTU" = pk."NR_PUNKTU"
            WHERE ap."NR_CYKLU" = {nr_cykl}
        ''')
        return session.execute(sql).all()