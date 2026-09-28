from WislDb import DRZEWA_OD_7, OBL_DRZEWA_OD_7, OBL_ADRES_POW, ADRES_POW, DRZEWA_MARTWE, OBL_DRZEWA_MARTWE, engine
from sqlmodel import Session, select, func, cast, Float, Integer, literal_column, text
from sqlalchemy import or_, and_, case
import geopandas as gpd
import math

# R_POW_PR (słownik SL_R_POW_LES) - las BEZ aktualnego drzewostanu, ale wciąż
# część gospodarki leśnej: Halizna(7), Zrąb(8), Płazowina(9), Do naturalnej
# sukcesji(10), Objęte szczególną ochroną(11), Inne wylesienia(12). WCHODZĄ
# do tła (mianownika) map udziału gatunków, bo fizycznie SĄ powierzchnią
# leśną - tylko chwilowo bez drzew. Plantacje specjalnego przeznaczenia
# (2-6: nasienne, szybko rosnące, choinkowe, krzewów, poletka łowieckie) i
# infrastruktura leśna (13+: drogi, budynki, linie energetyczne, szkółki)
# są wykluczone - nie reprezentują gospodarczego rozmieszczenia gatunków.
KODY_R_POW_LAS = [1, 7, 8, 9, 10, 11, 12]

# Górny próg wieku dla "młodej uprawy" (patrz query_mlode_uprawy) - odsiewa
# podpowierzchnie R_POW_PR=1 bez drzew >=7cm o wieku znacznie wyższym (w
# danych: do 155 lat), które są najpewniej błędnie sklasyfikowanymi
# zrębami/haliznami z nieaktualnym, planistycznym opisem w GAT_PAN_PR.
MAX_WIEK_MLODEJ_UPRAWY = 20

# STATUS_GRUNTU (słownik SL_STATUS_GRUNTU) - jakość/wiarygodność opisu
# powierzchni. Zachowujemy 1 (Lasy przeznaczone do produkcji leśnej),
# 2 (Lasy z roślinnością o pokryciu >10% o innej funkcji niż produkcja
# leśna) i 3 (Lasy bez roślinności drzewiastej lub z małym pokryciem).
# Odrzucamy 4 (Grunty leśne poza ewidencją), 5 (Powierzchnia negatywnie
# zweryfikowana) i 9 (Podpowierzchnia dopełniająca - techniczne uzupełnienie
# geometrii, nie samodzielny pomiar) - te statusy nie są wiarygodnym lub
# samodzielnym źródłem danych o drzewostanie.
STATUS_GRUNTU_MAX = 3

# Zakresy lat odpowiadające formalnym cyklom WISL, w kolejności chronologicznej
# (sprawdzone w bazie - rozłączne, sąsiadujące: MIN/MAX(SUBSTRING(DATA,1,4))
# per NR_CYKLU). Tylko wygodny skrót do iterowania "po wszystkich historycznych
# okresach" w blokach __main__ - lista, nie słownik z numerem cyklu jako
# kluczem, bo numer cyklu nie jest już częścią interfejsu (funkcje zapytań
# przyjmują rok_start/rok_end wprost i nie wymagają, żeby zakres pokrywał się
# z którymkolwiek z tych cykli).
CYKLE_LATA = [(2005, 2009), (2010, 2014), (2015, 2019), (2020, 2025)]

# PRZYCZ_USZK (słownik SL_PRZYCZ_USZK, tabela ADRES_POW) - zarejestrowana
# przyczyna uszkodzenia drzewostanu. Kod 10 = drzewostan NIEUSZKODZONY, nie
# jest tu ujęty - ten słownik obejmuje wyłącznie faktyczne przyczyny, jako
# wartości parametru przycz_uszk w kde_uszkodzenia.py / kde_uszkodzenia_sparr.py.
PRZYCZYNY_USZK = {
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
    32: "Jemioła",
}


def _filtr_lat(kolumna_data, rok_start, rok_end):
    # ADRES_POW.DATA to nvarchar(10) w formacie 'YYYY-MM-DD' - pierwsze 4
    # znaki to rok wykonania pomiaru. Filtrujemy PO ROKU, nie po sztywnym
    # NR_CYKLU: cykle WISL są rozłączne (1=2005-2009, 2=2010-2014,
    # 3=2015-2019, 4=2020-2025 - sprawdzone w bazie), ale filtr po roku
    # pozwala wybrać dowolny zakres, niekoniecznie pokrywający się z
    # formalnym cyklem (np. tylko 2 ostatnie lata cyklu, albo dwa cykle
    # naraz). NR_CYKLU jako KLUCZ ZŁĄCZENIA tabel (razem z NR_PODPOW)
    # zostaje bez zmian wszędzie - to nie jest filtr, tylko identyfikator
    # rekordu.
    rok = func.substring(kolumna_data, 1, 4).cast(Integer)
    return and_(rok >= rok_start, rok <= rok_end)


def _dopasowanie_gatunku(kolumna, gatunek):
    # Kody gatunków WISL rozróżniają podgatunki kropką (DB.S, DB.B, DB.C -
    # warianty dębu; podobnie SO.*, ŚW.*, BRZ.* itd.). Porównanie na sztywno
    # (GAT == 'DB') pomija je całkowicie - sprawdzone na danych: dla dębu to
    # 20,6% wszystkich drzew i 1990 podpowierzchni, które przy dosłownym
    # dopasowaniu znikają z wyników CAŁKOWICIE (nie mają żadnego drzewa z
    # czystym kodem 'DB'). Traktujemy podgatunek jako gatunek bazowy wszędzie,
    # więc dopasowanie to zawsze "dokładnie ten kod ALBO ten kod plus kropka".
    return or_(kolumna == gatunek, kolumna.like(gatunek + '.%'))


def query_udzial_gat(gatunek: str, rok_start: int = None, rok_end: int = None):
    # Nawiązanie połączenia z bazą WISL
    with Session(engine) as session:
        # Pobiera unikalne kombinacje NR_PODPOW i NR_CYKLU dla danego gatunku
        powierzchnie_z_gatunkiem = select(
            DRZEWA_OD_7.NR_PODPOW,
            DRZEWA_OD_7.NR_CYKLU
        ).where(
            _dopasowanie_gatunku(DRZEWA_OD_7.GAT, gatunek)
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
            # STATUS_GRUNTU jest wyłącznie w ADRES_POW (nie w OBL_ADRES_POW),
            # stąd dodatkowy JOIN - konieczny dla spójności z query_tlo_lasu /
            # query_mlode_uprawy, które ten warunek już mają: licznik i
            # mianownik muszą operować na tym samym uniwersum podpowierzchni.
            .join(ADRES_POW,
                (DRZEWA_OD_7.NR_PODPOW == ADRES_POW.NR_PODPOW) &
                (DRZEWA_OD_7.NR_CYKLU == ADRES_POW.NR_CYKLU))
            .where(_dopasowanie_gatunku(DRZEWA_OD_7.GAT, gatunek),
                _filtr_lat(ADRES_POW.DATA, rok_start, rok_end),
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

def query_tlo_lasu(rok_start: int = None, rok_end: int = None):
    # TŁO (mianownik g) do map udziału gatunków: CAŁA badana powierzchnia
    # leśna w danym cyklu - drzewostany (R_POW_PR=1) oraz fragmenty lasu
    # chwilowo bez drzewostanu (R_POW_PR 7-12 - patrz KODY_R_POW_LAS) - nie
    # tylko podpowierzchnie z danym gatunkiem.
    #
    # Iloraz sum(waga_gat) / sum(waga_tlo) jest ważoną średnią udziału
    # gatunku - wielkością BEZWZGLĘDNĄ, porównywalną między cyklami.
    # Pojedyncza znormalizowana gęstość KDE tego nie daje: integruje się
    # zawsze do 1, więc przyrost gatunku w jednym regionie automatycznie
    # obniża wartości we wszystkich pozostałych, nawet gdy nic się tam
    # fizycznie nie zmieniło (gra o sumie zerowej).
    #
    # Waga = WSP_Z. BEZ zadrzewienia (ZADRZEW): podpowierzchnie bez drzew
    # >=7cm (młode uprawy - query_mlode_uprawy, oraz R_POW_PR 7-12) mają w tej
    # bazie ZADRZEW zawsze NULL (sprawdzone: 0/2088), więc jego użycie w
    # wadze wykluczyłoby je z tła, a chodzi dokładnie o to, żeby je uwzględnić
    # - inaczej cała powierzchnia lasu przed/po wycince byłaby niewidoczna
    # w mianowniku, sztucznie zawyżając udział wszystkich gatunków.
    KODY_LAS_SQL = KODY_R_POW_LAS
    with Session(engine) as session:
        waga_tlo = cast(OBL_ADRES_POW.WSP_Z, Float)
        # NR_CYKLU zwracany, bo NR_PODPOW NIE jest unikalny między cyklami
        # (82% podpowierzchni powtarza się w kolejnych cyklach) - przy zakresie
        # lat obejmującym kilka cykli jedyny poprawny klucz rekordu to para
        # (NR_PODPOW, NR_CYKLU).
        return session.exec(
            select(
                OBL_ADRES_POW.NR_PODPOW,
                ADRES_POW.NR_CYKLU,
                waga_tlo.label('waga_tlo'),
            )
            .join(ADRES_POW,
                (ADRES_POW.NR_PODPOW == OBL_ADRES_POW.NR_PODPOW) &
                (ADRES_POW.NR_CYKLU == OBL_ADRES_POW.NR_CYKLU))
            .where(_filtr_lat(ADRES_POW.DATA, rok_start, rok_end),
                   ADRES_POW.R_POW_PR.in_(KODY_LAS_SQL),
                   ADRES_POW.STATUS_GRUNTU <= STATUS_GRUNTU_MAX,
                   waga_tlo > 0)
        ).all()


def query_mlode_uprawy(rok_start: int = None, rok_end: int = None):
    # Podpowierzchnie R_POW_PR=1 (Drzewostan) bez ŻADNEGO drzewa >=7cm i z
    # WIEK_PAN_PR <= MAX_WIEK_MLODEJ_UPRAWY - młode uprawy leśne, gdzie
    # gatunek określamy na podstawie GAT_PAN_PR (gatunek panujący wg opisu
    # taksacyjnego), bo nie ma jeszcze mierzalnej miąższości do policzenia
    # UDZIAL_MIAZSZOSC. Dotyczy WYŁĄCZNIE miary powierzchniowej (drzewostany)
    # - dla miąższościowej nie ma czego zmierzyć.
    #
    # Bez tego 2088 podpowierzchni R_POW_PR=1 znika CAŁKOWICIE z modelu (nie
    # ma ich ani w liczniku, ani w mianowniku), bo obie strony ilorazu opierały
    # się na obecności drzew w DRZEWA_OD_7. To systematycznie zaniżało udział
    # gatunków silnie reprezentowanych w młodym pokoleniu (odnowieniowych).
    #
    # Waga = WSP_Z (ZADRZEW jest tu zawsze NULL w bazie).
    with Session(engine) as session:
        # ma_drzewa musi filtrować DOKŁADNIE ten sam zakres lat co główne
        # zapytanie - stąd JOIN z ADRES_POW tutaj też (DRZEWA_OD_7 samo nie
        # ma kolumny DATA), mimo że wynik ma_drzewa nie jest bezpośrednio
        # zwracany.
        # Złączenie ma_drzewa po PEŁNYM kluczu (NR_PODPOW, NR_CYKLU): przy
        # zakresie lat obejmującym kilka cykli sam NR_PODPOW pomyliłby młodą
        # uprawę z cyklu N z tą samą podpowierzchnią z cyklu N+1, gdzie drzewa
        # >=7cm już urosły - i uprawa zniknęłaby z wyniku.
        ma_drzewa = (
            select(DRZEWA_OD_7.NR_PODPOW, DRZEWA_OD_7.NR_CYKLU)
            .join(ADRES_POW,
                (ADRES_POW.NR_PODPOW == DRZEWA_OD_7.NR_PODPOW) &
                (ADRES_POW.NR_CYKLU == DRZEWA_OD_7.NR_CYKLU))
            .where(_filtr_lat(ADRES_POW.DATA, rok_start, rok_end), DRZEWA_OD_7.WAR != 10)
            .distinct()
        ).subquery()

        waga_tlo = cast(OBL_ADRES_POW.WSP_Z, Float)
        return session.exec(
            select(
                ADRES_POW.NR_PODPOW,
                ADRES_POW.NR_CYKLU,
                ADRES_POW.GAT_PAN_PR,
                waga_tlo.label('waga_tlo'),
            )
            .join(OBL_ADRES_POW,
                (OBL_ADRES_POW.NR_PODPOW == ADRES_POW.NR_PODPOW) &
                (OBL_ADRES_POW.NR_CYKLU == ADRES_POW.NR_CYKLU))
            .outerjoin(ma_drzewa,
                (ma_drzewa.c.NR_PODPOW == ADRES_POW.NR_PODPOW) &
                (ma_drzewa.c.NR_CYKLU == ADRES_POW.NR_CYKLU))
            .where(_filtr_lat(ADRES_POW.DATA, rok_start, rok_end),
                   ADRES_POW.R_POW_PR == 1,
                   ADRES_POW.WIEK_PAN_PR <= MAX_WIEK_MLODEJ_UPRAWY,
                   ADRES_POW.GAT_PAN_PR.isnot(None),
                   ADRES_POW.STATUS_GRUNTU <= STATUS_GRUNTU_MAX,
                   waga_tlo > 0,
                   ma_drzewa.c.NR_PODPOW.is_(None))
        ).all()


def query_zasobnosc(rok_start: int = None, rok_end: int = None):
    # ZASOBNOSC (OBL_ADRES_POW) to miąższość drzew ŻYWYCH na 1 ha danej
    # podpowierzchni [m3/ha] - gotowa gęstość, w przeciwieństwie do martwego
    # drewna, gdzie MIAZSZOSC jest surową objętością z koła próbnego i trzeba
    # ją dopiero przeliczyć na hektar.
    #
    # Zwraca na TRAKT: średnią zasobność ważoną reprezentowaną powierzchnią
    # (SR_ZASOBNOSC = sum(ZASOBNOSC*WSP_Z)/sum(WSP_Z)) oraz samą SUMA_WSP_Z,
    # bo ta druga jest potrzebna osobno jako waga reprezentatywności przy
    # przestrzennym wygładzaniu KDE.
    #
    # UNIWERSUM: tylko drzewostany (R_POW_PR=1), czyli grunty ZALESIONE -
    # zgodnie z tym, jak zasobność raportuje BULiGL. Halizny, zręby i
    # płazowiny (R_POW_PR 7-12) to grunty NIEZALESIONE i do zasobności nie
    # wchodzą (w bazie mają zresztą ZASOBNOSC = NULL).
    #
    # OBSŁUGA NULL - dwa różne przypadki, których nie wolno mylić:
    #  - NULL i BRAK drzew >=7cm (1795 podpow. w cyklu 4): młoda uprawa,
    #    fizycznie zerowa miąższość drzew grubych - wchodzi jako 0 i
    #    poprawnie obniża średnią;
    #  - NULL MIMO obecności drzew >=7cm (848 podpow.): braku danych nie
    #    wolno czytać jako zera, więc taka podpowierzchnia jest POMIJANA.
    # Sprawdzone na danych: przy takim podziale średnia krajowa wynosi
    # 262,4 / 279,5 / 291,7 / 302,2 m3/ha w kolejnych cyklach, wobec
    # 263,2 / 276,5 / 291,1 / 292,9 raportowanych przez BULiGL (data.py).
    # Potraktowanie wszystkich NULL jako braku danych dawało 312,8 m3/ha
    # w cyklu 4, czyli wyraźnie powyżej wartości raportowanych.
    with Session(engine) as session:
        ma_drzewa = (
            select(DRZEWA_OD_7.NR_PODPOW, DRZEWA_OD_7.NR_CYKLU)
            .where(DRZEWA_OD_7.WAR != 10)
            .distinct()
        ).subquery()

        wsp_z = cast(OBL_ADRES_POW.WSP_Z, Float)
        zasobnosc = func.coalesce(cast(OBL_ADRES_POW.ZASOBNOSC, Float), 0.0)
        NR_Traktu = (OBL_ADRES_POW.NR_PODPOW // literal_column('1000')).label('NR_Traktu')

        return session.exec(
            select(
                NR_Traktu,
                (func.sum(zasobnosc * wsp_z) / func.sum(wsp_z)).label('SR_ZASOBNOSC'),
                func.sum(wsp_z).label('SUMA_WSP_Z'),
            )
            .join(ADRES_POW,
                (ADRES_POW.NR_PODPOW == OBL_ADRES_POW.NR_PODPOW) &
                (ADRES_POW.NR_CYKLU == OBL_ADRES_POW.NR_CYKLU))
            .outerjoin(ma_drzewa,
                (ma_drzewa.c.NR_PODPOW == OBL_ADRES_POW.NR_PODPOW) &
                (ma_drzewa.c.NR_CYKLU == OBL_ADRES_POW.NR_CYKLU))
            .where(_filtr_lat(ADRES_POW.DATA, rok_start, rok_end),
                   ADRES_POW.R_POW_PR == 1,
                   ADRES_POW.STATUS_GRUNTU <= STATUS_GRUNTU_MAX,
                   wsp_z > 0,
                   # pomijamy braki danych, ale zostawiamy zerowe uprawy
                   or_(OBL_ADRES_POW.ZASOBNOSC.isnot(None),
                       ma_drzewa.c.NR_PODPOW.is_(None)),
                   # Ujemna miąższość to błąd danych (3 rekordy w bazie, min
                   # -2,57 m3/ha). Bez tego trakt dostaje ujemną wagę i
                   # gaussian_kde przerywa: "aweights cannot be negative".
                   or_(OBL_ADRES_POW.ZASOBNOSC.is_(None),
                       cast(OBL_ADRES_POW.ZASOBNOSC, Float) >= 0))
            .group_by(NR_Traktu)
        ).all()


def query_zasobnosc_gat(gatunek: str, rok_start: int = None, rok_end: int = None):
    # Zasobność JEDNEGO gatunku [m3/ha] - odpowiednik query_zasobnosc, ale
    # liczony od dołu, z miąższości pojedynczych drzew (OBL_DRZEWA_OD_7.
    # MIAZSZOSC, objętość grubizny drzewa w m3). Na podpowierzchnię:
    #   ZAS_GAT = SUMA(MIAZSZOSC drzew gatunku) / (WSP_Z * POW_KOLA_HA)
    # czyli suma objętości / rzeczywiście reprezentowana powierzchnia koła.
    #
    # POWIERZCHNIA KOŁA NIE JEST STAŁA i nie ma jej w żadnej kolumnie bazy.
    # Sprawdzone na danych (SUMA(MIAZSZOSC) / (ZASOBNOSC * WSP_Z)):
    #  - cykle 3-4 (2015-2025): zawsze 400 m2 (r = 11,28 m), 100% podpow.;
    #  - cykle 1-2 (2005-2014): 200 m2 w drzewostanach do ~60 lat, 400 m2
    #    w starszych, część 500 m2, a na części powierzchni wartości pośrednie
    #    (koła koncentryczne - grubsze drzewa mierzone na większym kole).
    # Dlatego POW_KOLA_HA odtwarzamy z ZASOBNOSC samej bazy, która ma już
    # uwzględnioną właściwą metodykę danego cyklu:
    #   POW_KOLA_HA = SUMA(MIAZSZOSC wszystkich drzew) / (ZASOBNOSC * WSP_Z)
    # Dzięki temu suma zasobności wszystkich gatunków na podpowierzchni daje
    # dokładnie ZASOBNOSC, a średnie krajowe są spójne z query_zasobnosc.
    #
    # Uniwersum, filtry i obsługa NULL - identyczne jak w query_zasobnosc
    # (drzewostany R_POW_PR=1; młode uprawy bez drzew >=7cm wchodzą jako 0;
    # NULL ZASOBNOSC mimo obecności drzew = brak danych, pomijane). Podpow.
    # bez danego gatunku wchodzą jako 0 - to one tworzą tło (mianownik).
    # Przestoje (WAR=10) pominięte jak wszędzie - ZASOBNOSC w bazie też ich
    # nie zawiera (sprawdzone: bez nich 400 m2 wychodzi na większej liczbie
    # podpowierzchni).
    #
    # DRZEWA BEZ MIĄŻSZOŚCI (brak wiersza w OBL_DRZEWA_OD_7; cykl 4: ~120 tys.
    # drzew, 11%) są POMIJANE - nie wchodzą do żadnej sumy. Tak samo liczy je
    # sama baza: na podpowierzchniach z takimi drzewami ZASOBNOSC odpowiada
    # dokładnie sumie miąższości POZOSTAŁYCH drzew na 400 m2 (sprawdzone,
    # cykle 3-4: 100% / 99,96% podpow.), więc POW_KOLA_HA odtworzone z
    # ZASOBNOSC jest poprawne i niczego nie "dolicza" za brakujące drzewa.
    with Session(engine) as session:
        miazszosc = cast(OBL_DRZEWA_OD_7.MIAZSZOSC, Float)
        miazszosc_pow = (
            select(
                DRZEWA_OD_7.NR_PODPOW,
                DRZEWA_OD_7.NR_CYKLU,
                func.sum(miazszosc).label('SUMA_MIAZSZOSC'),
                func.sum(case((_dopasowanie_gatunku(DRZEWA_OD_7.GAT, gatunek), miazszosc),
                              else_=0.0)).label('SUMA_MIAZSZOSC_GAT'),
            )
            # LEFT JOIN: o tym, czy podpowierzchnia MA drzewa, decyduje
            # DRZEWA_OD_7 (jak ma_drzewa w query_zasobnosc); drzewa bez
            # miąższości dają NULL, który SUM pomija.
            .outerjoin(OBL_DRZEWA_OD_7, DRZEWA_OD_7.ID == OBL_DRZEWA_OD_7.ID)
            .where(DRZEWA_OD_7.WAR != 10)
            .group_by(DRZEWA_OD_7.NR_PODPOW, DRZEWA_OD_7.NR_CYKLU)
        ).subquery()

        wsp_z = cast(OBL_ADRES_POW.WSP_Z, Float)
        zasobnosc = cast(OBL_ADRES_POW.ZASOBNOSC, Float)
        # Jawne cast(..., Float) po każdym dzieleniu: bez tego SQLAlchemy
        # rzutuje mianownik nullif(...) na NUMERIC (w MSSQL domyślnie (18,0)),
        # co obcina ułamek hektara do zera -> "Divide by zero".
        pow_kola_ha = cast(
            miazszosc_pow.c.SUMA_MIAZSZOSC / cast(func.nullif(zasobnosc * wsp_z, 0), Float),
            Float)
        # Brak gatunku albo brak drzew w ogóle (młoda uprawa) -> 0 m3/ha.
        # ZASOBNOSC = 0 mimo drzew daje pow_kola_ha = NULL, więc i tu NULL,
        # który SUM pomija - czyli podpowierzchnia liczy się jak 0.
        zas_gat = case(
            (miazszosc_pow.c.SUMA_MIAZSZOSC_GAT > 0,
             miazszosc_pow.c.SUMA_MIAZSZOSC_GAT
             / cast(func.nullif(wsp_z * pow_kola_ha, 0), Float)),
            else_=0.0,
        )
        NR_Traktu = (OBL_ADRES_POW.NR_PODPOW // literal_column('1000')).label('NR_Traktu')

        return session.exec(
            select(
                NR_Traktu,
                (func.sum(zas_gat * wsp_z) / func.sum(wsp_z)).label('SR_ZASOBNOSC'),
                func.sum(wsp_z).label('SUMA_WSP_Z'),
            )
            .join(ADRES_POW,
                (ADRES_POW.NR_PODPOW == OBL_ADRES_POW.NR_PODPOW) &
                (ADRES_POW.NR_CYKLU == OBL_ADRES_POW.NR_CYKLU))
            .outerjoin(miazszosc_pow,
                (miazszosc_pow.c.NR_PODPOW == OBL_ADRES_POW.NR_PODPOW) &
                (miazszosc_pow.c.NR_CYKLU == OBL_ADRES_POW.NR_CYKLU))
            .where(_filtr_lat(ADRES_POW.DATA, rok_start, rok_end),
                   ADRES_POW.R_POW_PR == 1,
                   ADRES_POW.STATUS_GRUNTU <= STATUS_GRUNTU_MAX,
                   wsp_z > 0,
                   # Zostawiamy zerowe uprawy (brak drzew >=7cm) oraz
                   # podpowierzchnie ze znaną ZASOBNOSC i znanym składem
                   # (SUMA_MIAZSZOSC > 0; ZASOBNOSC = 0 też jest poprawnym
                   # zerem). Pomijamy braki danych: ZASOBNOSC NULL mimo drzew
                   # (jak w query_zasobnosc) oraz ZASOBNOSC > 0 przy braku
                   # miąższości wszystkich drzew (w bazie nie występuje).
                   or_(miazszosc_pow.c.NR_PODPOW.is_(None),
                       and_(OBL_ADRES_POW.ZASOBNOSC.isnot(None),
                            or_(miazszosc_pow.c.SUMA_MIAZSZOSC > 0, zasobnosc == 0))),
                   or_(OBL_ADRES_POW.ZASOBNOSC.is_(None), zasobnosc >= 0))
            .group_by(NR_Traktu)
        ).all()


def query_drzewostany_uszk(rok_start: int = None, rok_end: int = None):
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
            .where(_filtr_lat(ADRES_POW.DATA, rok_start, rok_end),
                   ADRES_POW.R_POW_PR == 1,
                   ADRES_POW.STATUS_GRUNTU <= STATUS_GRUNTU_MAX)
        ).all()
    return powierzchnie_uszk

#Martwe - średnia ważona wsp Z w trakcie

def martwe_drewno(rok_start: int = None, rok_end: int = None):
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
                _filtr_lat(ADRES_POW.DATA, rok_start, rok_end),
                ADRES_POW.R_POW_PR.in_([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]),
                ADRES_POW.STATUS_GRUNTU <= STATUS_GRUNTU_MAX
            )
            .group_by(NR_Traktu_z)
        ).cte('z_pow_les')

        # ADRES_POW dociągnięty tu tylko po to, żeby filtrować DRZEWA_MARTWE
        # po tym samym zakresie lat co z_pow_les (DRZEWA_MARTWE nie ma
        # kolumny DATA) - martwe drewno z podpowierzchni poza [rok_start,
        # rok_end] albo o odrzucanym STATUS_GRUNTU nie powinno wejść do sumy.
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
            .join(ADRES_POW,
                (DRZEWA_MARTWE.NR_PODPOW == ADRES_POW.NR_PODPOW) &
                (DRZEWA_MARTWE.NR_CYKLU == ADRES_POW.NR_CYKLU))
            .where(_filtr_lat(ADRES_POW.DATA, rok_start, rok_end),
                   ADRES_POW.STATUS_GRUNTU <= STATUS_GRUNTU_MAX)
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


def query_all_wisl_plots(rok_start, rok_end):
    with Session(engine) as session:
        sql = text(f'''
            SELECT * FROM "PUNKTY_TRAKTU" AS pk
            INNER JOIN "ADRES_POW" as ap on ap."NR_PUNKTU" = pk."NR_PUNKTU"
            WHERE CAST(SUBSTRING(ap."DATA", 1, 4) AS INT) BETWEEN {rok_start} AND {rok_end}
              AND ap."STATUS_GRUNTU" <= {STATUS_GRUNTU_MAX}
        ''')
        return session.execute(sql).all()