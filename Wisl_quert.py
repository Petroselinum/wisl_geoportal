from WislDb import DRZEWA_OD_7, OBL_DRZEWA_OD_7, OBL_ADRES_POW, ADRES_POW, DRZEWA_MARTWE, OBL_DRZEWA_MARTWE, engine
from sqlmodel import Session, select, func, cast, Float, Integer, literal_column, text

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

def query_drzewostany_uszk(nr_cykl: int = None, nasil_uszk: int = None):
    with Session(engine) as session:
        powierzchnie_uszk = session.exec(
                                select(ADRES_POW.NR_PODPOW,
                                   ADRES_POW.GAT_PAN_PR,
                                   ADRES_POW.NASIL_USZK,
                                   OBL_ADRES_POW.WSP_Z,
                                   (ADRES_POW.NASIL_USZK * OBL_ADRES_POW.WSP_Z).label('waga_oddz'),
                                   ADRES_POW.PRZYCZ_USZK) \
            .join(OBL_ADRES_POW,
                (ADRES_POW.NR_PODPOW == OBL_ADRES_POW.NR_PODPOW) &
                (ADRES_POW.NR_CYKLU == OBL_ADRES_POW.NR_CYKLU)) \
            .where(ADRES_POW.NR_CYKLU == nr_cykl,
                   ADRES_POW.NASIL_USZK >= nasil_uszk)
        ).all()
    return powierzchnie_uszk

#Martwe - średnia ważona wsp Z w trakcie

def martwe_drewno(nr_cykl: int = None):
    with Session(engine) as session:
        sql = text("""
            WITH z_pow_les AS (
                SELECT 
                    NR_PODPOW / 1000 AS NR_Traktu,
                    CAST(SUM(WSP_Z) AS FLOAT) AS SUMA_WSP_Z
                FROM OBL_ADRES_POW
                WHERE NR_CYKLU = :nr_cykl
                  AND GAT IS NOT NULL
                GROUP BY NR_PODPOW / 1000
            ),
            martwe AS (
                SELECT
                    a.NR_PODPOW / 1000 AS NR_Traktu,
                    d.TYP,
                    CAST(SUM(od.MIAZSZOSC) * a.WSP_Z AS FLOAT) AS MIAZSZOSC_martwe_pow
                FROM DRZEWA_MARTWE d
                JOIN OBL_DRZEWA_MARTWE od ON d.ID = od.ID
                JOIN OBL_ADRES_POW a ON d.NR_PODPOW = a.NR_PODPOW
                                     AND d.NR_CYKLU = a.NR_CYKLU
                WHERE d.NR_CYKLU = :nr_cykl
                GROUP BY a.NR_PODPOW / 1000, d.NR_PODPOW, d.TYP, a.WSP_Z
            )
            SELECT
                m.NR_Traktu,
                m.TYP,
                SUM(m.MIAZSZOSC_martwe_pow) / z.SUMA_WSP_Z AS SR_MIAZSZOSC
            FROM martwe m
            JOIN z_pow_les z ON m.NR_Traktu = z.NR_Traktu
            GROUP BY m.NR_Traktu, m.TYP, z.SUMA_WSP_Z
        """)
        
        return session.execute(sql, {"nr_cykl": nr_cykl}).all()