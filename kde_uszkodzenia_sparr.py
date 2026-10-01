import json
import os
import subprocess
import matplotlib.pyplot as plt
from matplotlib import patches as mpatches
from matplotlib import lines as mlines
import pandas as pd
import geopandas as gpd
import contextily as cx

from Wisl_quert import query_drzewostany_uszk, PRZYCZYNY_USZK
from matplotlib_map_utils.core.north_arrow import north_arrow
from matplotlib_map_utils.core.scale_bar import scale_bar

# ==============================================================================
# ŚCIEŻKA DO Rscript W ŚRODOWISKU CONDA
# ==============================================================================
RSCRIPT_PATH = "/home/piotr/miniconda3/envs/jupyter_env/bin/Rscript" 

CRS_OBLICZENIOWY = "EPSG:2180"

# Ten sam globalny próg wiarygodności modelu co w kde_uszkodzenia.py /
# kde_martwe_drewno.py / kde_gat.py - poniżej tej liczby traktów mapa w
# ogóle nie jest generowana.
MIN_TRAKTOW_WIARYGODNY = 100

# Progi dla samych uszkodzeń (analiza map z 2026-09-30: przy kilkudziesięciu
# uszkodzonych traktach test asymptotyczny sparr wskazywał obszary istotne
# o polu dziesiątek tys. km2 wyznaczone przez 3-6 punktów, np. zanieczyszczenia
# powietrza 2020-2025: 19 punktów w kraju, 4 w obszarze 34 tys. km2):
# - poniżej MIN_USZKODZONYCH_TRAKTOW w kraju test nie jest wykonywany - dobór
#   pasma (LSCV.risk) i asymptotyka p są wtedy niestabilne; mapa pokazuje
#   tylko punkty z adnotacją;
# - obszar istotny (spójna część wyniku) zostaje tylko, gdy zawiera co
#   najmniej MIN_TRAKTOW_W_OBSZARZE uszkodzonych traktów - problem jest
#   lokalny, więc sam próg krajowy go nie usuwa.
MIN_USZKODZONYCH_TRAKTOW = 50
MIN_TRAKTOW_W_OBSZARZE = 10


def odfiltruj_obszary(gdf_istotne, gdf_uszk, minimum=MIN_TRAKTOW_W_OBSZARZE):
    """
    Rozbija wynik R na spójne obszary (części wielokąta) i zostawia te,
    w których leży co najmniej `minimum` uszkodzonych traktów (punkt na
    granicy obszaru liczy się do niego). Zwraca (zachowane obszary z kolumną
    n_uszk, liczba obszarów przed filtrem).
    """
    obszary = gdf_istotne.explode(index_parts=False).reset_index(drop=True)
    obszary = obszary[obszary.geometry.notna() & ~obszary.geometry.is_empty].copy()
    obszary['n_uszk'] = [int(gdf_uszk.geometry.intersects(g).sum()) for g in obszary.geometry]
    return obszary[obszary['n_uszk'] >= minimum].reset_index(drop=True), len(obszary)

def uszkodzenia(rok_start: int, rok_end: int, prog_nasil_uszk: int = None, gatunek: str = None,
                 przycz_uszk: int = None):
    okres = f"{rok_start}-{rok_end}"
    res = query_drzewostany_uszk(rok_start=rok_start, rok_end=rok_end)
    if not res:
        print(f"Brak danych z bazy dla lat {okres}.")
        return

    df = pd.DataFrame(res, columns=['NR_PUNKTU', 'NR_PODPOW', 'GAT_PAN_PR', 'WSP_Z', 'NASIL_USZK', 'PRZYCZ_USZK'])
    df['NR_TRAKTU'] = df['NR_PUNKTU'].str[:-1]

    trakty = gpd.read_file('data/trakty_wsp.geojson')

    if gatunek is not None:
        # Podgatunki (DB.S, DB.B, ...) jak gatunek bazowy - to samo dopasowanie
        # co Wisl_quert._dopasowanie_gatunku.
        maska = (df['GAT_PAN_PR'] == gatunek) | df['GAT_PAN_PR'].fillna('').str.startswith(gatunek + '.')
        df = df[maska].copy()

    if df.empty:
        print(f"Brak danych po odfiltrowaniu dla gatunku w latach {okres}.")
        return

    tlo = df.groupby('NR_TRAKTU').agg({'WSP_Z': 'sum'}).reset_index()

    # prog_nasil_uszk = minimalne nasilenie (klasa), od którego drzewostan
    # liczy się jako uszkodzony: >= prog. None = każde zarejestrowane
    # uszkodzenie (jak w kde_uszkodzenia.py).
    prog = prog_nasil_uszk if prog_nasil_uszk is not None else 0
    df_uszk_filtr = df[(df['NASIL_USZK'] > 0) & (df['NASIL_USZK'] >= prog)].copy()

    # przycz_uszk zawęża licznik do jednej przyczyny uszkodzenia (PRZYCZ_USZK
    # - słownik PRZYCZYNY_USZK w Wisl_quert.py); None = wszystkie przyczyny
    # razem, niezależnie od filtra po nasileniu powyżej.
    if przycz_uszk is not None:
        df_uszk_filtr = df_uszk_filtr[df_uszk_filtr['PRZYCZ_USZK'] == przycz_uszk]

    # NASIL_USZK to skala ciągła (3 = 30%, 5 = 50%; poniżej 30% drzewostan
    # uznaje się za nieuszkodzony), więc iloczyn z WSP_Z jest uzasadniony.
    # Skala (x10 do %) nie ma tu znaczenia - test sparr porównuje kształt
    # dwóch gęstości, nie ich wartości bezwzględne.
    df_uszk_filtr['iloczyn_nasilenia'] = df_uszk_filtr['WSP_Z'] * df_uszk_filtr['NASIL_USZK']
    df_uszk_trakty = df_uszk_filtr.groupby('NR_TRAKTU').agg(waga_uszk=('iloczyn_nasilenia', 'sum')).reset_index()

    trakty['nr_traktu'] = trakty['nr_punktu'].astype(int).astype(str).str[:-1]
    trakty_geom = trakty[['nr_traktu', 'geometry']].copy()

    tlo['NR_TRAKTU'] = tlo['NR_TRAKTU'].astype(int).astype(str)
    df_uszk_trakty['NR_TRAKTU'] = df_uszk_trakty['NR_TRAKTU'].astype(int).astype(str)

    df_model = pd.merge(tlo, df_uszk_trakty, on='NR_TRAKTU', how='left')
    df_model['waga_uszk'] = df_model['waga_uszk'].fillna(0.0)
    df_model = df_model.rename(columns={'WSP_Z': 'waga_tlo'})

    gdf_model = trakty_geom.merge(df_model, left_on='nr_traktu', right_on='NR_TRAKTU', how='inner')
    gdf_model = gpd.GeoDataFrame(gdf_model, geometry='geometry', crs=trakty.crs).to_crs(CRS_OBLICZENIOWY)
    gdf_model = gdf_model[gdf_model.geometry.notnull() & (gdf_model['waga_tlo'] > 0)].copy()

    if len(gdf_model) < 5:
        print(f"Zbyt mało danych dla lat {okres}.")
        return

    if len(gdf_model) < MIN_TRAKTOW_WIARYGODNY:
        print(
            f"Pominięto mapę: tylko {len(gdf_model)} traktów (wymagane min. "
            f"{MIN_TRAKTOW_WIARYGODNY}, lata {okres})."
        )
        return

    # ==============================================================================
    # 1. PRZYGOTOWANIE DANYCH WEJŚCIOWYCH DLA R
    # ==============================================================================
    os.makedirs("KDE_temp", exist_ok=True)
    os.makedirs("KDE_uszkodzenia_ryzyko", exist_ok=True)

    poland = gpd.read_file("data/poland_land.geojson").to_crs(CRS_OBLICZENIOWY)
    poland.to_file("KDE_temp/poland_bounds.geojson", driver="GeoJSON")

    df_tlo_pts = pd.DataFrame({
        'x': gdf_model.geometry.x,
        'y': gdf_model.geometry.y,
        'waga': gdf_model['waga_tlo']
    })
    df_tlo_pts.to_csv("KDE_temp/tlo_points.csv", index=False)

    gdf_uszk = gdf_model[gdf_model['waga_uszk'] > 0]
    df_uszk_pts = pd.DataFrame({
        'x': gdf_uszk.geometry.x,
        'y': gdf_uszk.geometry.y,
        'waga': gdf_uszk['waga_uszk']
    })
    df_uszk_pts.to_csv("KDE_temp/uszk_points.csv", index=False)

    sufix_gat = f"_{gatunek}" if gatunek else ""
    sufix_nasil = f"_nasil{prog_nasil_uszk}" if prog_nasil_uszk is not None else ""
    sufix_przycz = f"_przycz{przycz_uszk}" if przycz_uszk is not None else ""
    file_prefix = f"ryzyko_{okres}{sufix_gat}{sufix_nasil}{sufix_przycz}"

    geojson_path = f"KDE_uszkodzenia_ryzyko/istotne_{file_prefix}.geojson"
    info_path = f"KDE_uszkodzenia_ryzyko/istotne_{file_prefix}_info.json"
    # Wynik z poprzedniego przeliczenia nie może zostać, gdy R tym razem nie
    # zapisze nowego (za mało uszkodzeń, błąd R) - mapa pokazałaby stary obszar.
    if os.path.exists(geojson_path):
        os.remove(geojson_path)

    n_uszk = len(gdf_uszk)
    testowano = n_uszk >= MIN_USZKODZONYCH_TRAKTOW
    gdf_istotne = gpd.GeoDataFrame(geometry=[], crs=CRS_OBLICZENIOWY)
    n_obszarow_r = 0

    # ==============================================================================
    # 2. WYWOŁANIE SKRYPTU R
    # ==============================================================================
    if testowano:
        print(f"Obliczanie istotności statystycznej w R (sparr) dla lat {okres}...")
        try:
            subprocess.run(
                [RSCRIPT_PATH, "policz_ryzyko.R", file_prefix],
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            print(f"Błąd podczas wykonywania Rscript:\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}")
            return

        # ==========================================================================
        # 3. ODCZYT WYNIKÓW, REDEFINICJA CRS I FILTR OBSZARÓW
        # ==========================================================================
        if os.path.exists(geojson_path):
            wynik_r = gpd.read_file(geojson_path)
            if not wynik_r.empty:
                # R zwraca surowe metry, przypisujemy właściwy CRS siłą
                wynik_r = wynik_r.set_crs(CRS_OBLICZENIOWY, allow_override=True)
                gdf_istotne, n_obszarow_r = odfiltruj_obszary(wynik_r, gdf_uszk)
    else:
        print(
            f"Pominięto test istotności: {n_uszk} uszkodzonych traktów "
            f"(wymagane min. {MIN_USZKODZONYCH_TRAKTOW}, lata {okres})."
        )

    # Zawsze zapisujemy wynik (także pusty) i opis - portal odróżnia wtedy
    # "brak obszarów istotnych" od "test nie był wykonany".
    gdf_istotne.to_file(geojson_path, driver="GeoJSON")
    n_odrzuconych = n_obszarow_r - len(gdf_istotne)
    with open(info_path, 'w', encoding='utf-8') as f:
        json.dump({
            'n_uszkodzonych_traktow': n_uszk,
            'testowano': testowano,
            'min_uszkodzonych_traktow': MIN_USZKODZONYCH_TRAKTOW,
            'min_traktow_w_obszarze': MIN_TRAKTOW_W_OBSZARZE,
            'obszary_z_R': n_obszarow_r,
            'obszary_odrzucone': n_odrzuconych,
            'obszary_zachowane': len(gdf_istotne),
        }, f, ensure_ascii=False, indent=1)

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')

    if not gdf_istotne.empty:
        gdf_istotne.plot(
            ax=ax,
            facecolor='#ff7f00',
            edgecolor='#8b0000',
            linewidth=1.5,
            alpha=0.6
        )

    gdf_model.plot(ax=ax, color='gray', markersize=3, alpha=0.3)
    gdf_uszk.plot(ax=ax, color='red', markersize=8, alpha=0.7)
    poland.boundary.plot(ax=ax, color='black', linewidth=1)

    try:
        north_arrow(ax, location="upper left", rotation={"crs": poland.crs, "reference": "center"}, shadow=False, scale=0.4)
        scale_bar(ax, location="upper right", style="ticks", bar={"projection": poland.crs, "unit": "km"}, units={"loc": "bar"})
    except NameError:
        pass

    xmin, ymin, xmax, ymax = poland.total_bounds
    MARGIN = 20_000
    ax.set_xlim(xmin - MARGIN, xmax + MARGIN)
    ax.set_ylim(ymin - MARGIN, ymax + MARGIN)
    ax.grid(True, linestyle='--', alpha=0.5, color='gray')

    tytul_gatunek = f" | Gatunek: {gatunek}" if gatunek else ""
    tytul_przyczyna = (f" | Przyczyna: {PRZYCZYNY_USZK.get(przycz_uszk, przycz_uszk)}"
                        if przycz_uszk is not None else "")
    opis_progu = ("uszkodzenie ≥ 30%" if prog_nasil_uszk is None
                  else f"nasilenie uszk. ≥ {prog_nasil_uszk * 10}%")
    ax.set_title(f"Istotne ryzyko uszkodzeń p < 0.05 (Lata: {okres}, {opis_progu}){tytul_gatunek}{tytul_przyczyna}", fontsize=11)
    # Wynik eksploracyjny: p<0.05 liczone niezależnie w każdym pikselu siatki,
    # bez korekty na wielokrotne testowanie (patrz policz_ryzyko.R) - to
    # akceptowane w literaturze ograniczenie metody tolerance contours
    # (Kelsall & Diggle), ale trzeba je widzieć razem z wynikiem, nie tylko
    # w logu konsoli.
    if testowano:
        uwagi = ["Wynik eksploracyjny - bez korekty na wielokrotne testowanie",
                 f"Obszary istotne: min. {MIN_TRAKTOW_W_OBSZARZE} uszkodzonych traktów w obszarze"]
        if n_odrzuconych:
            uwagi.append(f"Pominięto obszary z < {MIN_TRAKTOW_W_OBSZARZE} uszkodzonymi traktami: "
                         f"{n_odrzuconych}")
    else:
        uwagi = [f"Za mało uszkodzonych traktów ({n_uszk} < {MIN_USZKODZONYCH_TRAKTOW}) - "
                 f"test istotności nie został wykonany"]
    # przypis pod mapą (pod opisem osi X) - w środku mapy każdy róg jest zajęty:
    # strzałka północy, podziałka, legenda, a w prawym dolnym są Bieszczady,
    # gdzie często wypadają obszary istotne
    ax.annotate(
        "\n".join(uwagi),
        xy=(0, 0), xycoords="axes fraction",
        xytext=(0, -40), textcoords="offset points",
        fontsize=8 if testowano else 9,
        color="#555555" if testowano else "#8b0000",
        va="top", ha="left", annotation_clip=False,
    )
    ax.set_xlabel("X [m] (EPSG:2180)")
    ax.set_ylabel("Y [m] (EPSG:2180)")
    ax.ticklabel_format(style='plain', useOffset=False)

    try:
        cx.add_basemap(ax, crs=poland.crs, source=cx.providers.Esri.WorldGrayCanvas, alpha=1, zoom=8)
    except Exception:
        pass

    legend_elements = ([
        mpatches.Patch(facecolor='#ff7f00', edgecolor='#8b0000', linewidth=1.5, alpha=0.6, label='Istotne ryzyko (p < 0.05)'),
    ] if testowano else []) + [
        mlines.Line2D([], [], color='red', marker='o', linestyle='None', markersize=6, alpha=0.7, label='Trakt uszkodzony'),
        mlines.Line2D([], [], color='gray', marker='o', linestyle='None', markersize=4, alpha=0.4, label='Trakt badany (tło)'),
        mlines.Line2D([], [], color='black', linewidth=1, label='Granica Polski'),
    ]
    ax.legend(handles=legend_elements, loc='lower left', bbox_to_anchor=(0.01, 0.03), frameon=True, facecolor='white')

    fig.savefig(f"KDE_uszkodzenia_ryzyko/{file_prefix}_sparr.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Zakończono pomyślnie. Mapę {'z testem sparr' if testowano else 'bez testu'} "
          f"zapisano dla lat {okres}.")

if __name__ == "__main__":
    '''
    from Wisl_quert import CYKLE_LATA
    for rok_start, rok_end in CYKLE_LATA:
        #for gat in ['SO', 'ŚW', 'JD', 'MD', 'DB', 'BK', 'BRZ', 'OL']:
        uszkodzenia(rok_start=rok_start, rok_end=rok_end, gatunek=None)
    '''
    from Wisl_quert import CYKLE_LATA
    for rok_start, rok_end in CYKLE_LATA:
        for uszk in PRZYCZYNY_USZK.keys():
            uszkodzenia(rok_start=rok_start, rok_end=rok_end, gatunek=None, przycz_uszk=uszk)