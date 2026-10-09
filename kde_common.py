import numpy as np
import matplotlib.text as mtext
from matplotlib import patheffects
import shapely
from shapely.geometry import Polygon
from scipy.signal import fftconvolve
from scipy.stats import gaussian_kde
from matplotlib import patches as mpatches
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling

# Podkład map PNG zamiast kafelków Esri WorldGrayCanvas (warunki Esri nie
# pozwalają rozpowszechniać ich kafelków, a mapy PNG są do pobrania
# w portalu). Raster RGB, WGS 84, 1' (ok. 1,1 x 1,85 km nad Polską), Europa
# 36,4°W-82,4°E, 33,5-71,3°N - hipsometria z cieniowaniem rzeźby, wody
# i rzeki (wygląda jak Natural Earth I/II, domena publiczna).
PODKLAD_TIF = 'data/europa.tif'
PODKLAD_PODPIS = 'Podkład: Natural Earth'


def kontur_na_zasieg(segs):
    """
    Zamienia pętle konturu jednego progu (cs.allsegs[i] z ax.contour) na
    wielokąt obszaru >= prog. Pętle jednego poziomu nigdy się nie przecinają,
    więc obszar to różnica symetryczna (XOR) wszystkich pętli: pętla wewnątrz
    pętli to dziura (obszar PONIŻEJ progu otoczony wyższymi wartościami),
    pętla wewnątrz dziury - znów wyspa >= prog.

    Wcześniej pętle łączono przez union_all - pętla wewnętrzna była wtedy
    wchłaniana przez zewnętrzną i zasięg nie miał żadnych dziur (sprawdzone
    2026-10-05 na przyroście 2010-2014: zasięg > 10 m3/ha/rok obejmował 311
    tys. km2, czyli prawie całą Polskę razem z obszarem 9-10 w centrum).
    """
    zasieg = Polygon()
    for seg in segs:
        if len(seg) >= 3:
            petla = Polygon(seg)
            if not petla.is_valid:
                petla = shapely.make_valid(petla)
            zasieg = zasieg.symmetric_difference(petla)
    return zasieg.buffer(0)


def etykietuj_kontury(ax, progi, zasiegi_geom, granica_polski, tekst_progu, kolor,
                      fontsize=6):
    """
    Nanosi etykiety progów wzdłuż linii konturu (TekstWzdlugKonturu) - na
    KAŻDEJ pętli konturu danego progu, czyli na obrysach zewnętrznych i na
    dziurach zasięgu >= prog (dziura = zamknięty kontur wokół obszaru PONIŻEJ
    progu; dawniej etykietowane były tylko obrysy zewnętrzne pierścienia
    pasma, więc takie kontury zostawały bez opisu). Pętle różnych progów się
    nie pokrywają, więc etykiety się nie dublują.

    Etykieta jest PROGOWA ("> 5%") - linia wyznacza przekroczenie progu.

    Pomijane są pętle, na których napis byłby nieczytelny:
    - pole wnętrza < MIN_POWIERZCHNIA (znikome strzępki zasięgu),
    - obwód < MIN_OBWOD_W_ETYKIETACH x długość napisu (z zapasem 1,8 z
      dlugosc_tekstu_w_danych) - na krótkiej pętli napis zawija się wokół
      niej i nachodzi sam na siebie.
    Punkty kotwiczące leżą dalej niż BORDER_TOL od granicy Polski (etykieta
    nie może wyglądać jak opis granicy kraju), wybierane zachłannie od
    najdalszego od granicy, w odstępach co najmniej MIN_ODSTEP.

    tekst_progu: funkcja prog -> napis etykiety.
    """
    MIN_POWIERZCHNIA = 3e8         # m^2 (300 km^2)
    # obwód pętli / długość napisu z zapasem 1,8, czyli ok. 2,5 x sam napis
    # (napis zajmuje najwyżej ~40% pętli). Dawne 4 (= 7,2 x napis, ok. 430 km
    # przy "> 10 m³/ha/rok") zostawiało bez etykiet obszary 4-9 tys. km2 -
    # sprawdzone 2026-10-09 na przyroście, użytkowaniu i martwym drewnie:
    # 85 z 439 pętli z etykietą, po zmianie 161.
    MIN_OBWOD_W_ETYKIETACH = 1.4
    BORDER_TOL = 15_000            # m
    MIN_ODSTEP = 150_000           # m

    kandydaci = []
    for prog, geom in zip(progi, zasiegi_geom):
        czesci = [g for g in getattr(geom, 'geoms', [geom])
                  if isinstance(g, Polygon) and not g.is_empty]
        for pierscien in [r for g in czesci for r in (g.exterior, *g.interiors)]:
            if Polygon(pierscien).area < MIN_POWIERZCHNIA:
                continue
            wierzcholki = np.array(pierscien.coords)
            odleglosc = shapely.distance(shapely.points(wierzcholki), granica_polski)
            maska_daleko = odleglosc > BORDER_TOL
            if not maska_daleko.any():
                continue
            wybrane_idx = []
            for idx in np.argsort(-np.where(maska_daleko, odleglosc, -np.inf)):
                if not maska_daleko[idx]:
                    break
                if all(np.linalg.norm(wierzcholki[idx] - wierzcholki[w]) >= MIN_ODSTEP
                       for w in wybrane_idx):
                    wybrane_idx.append(int(idx))
            kandydaci += [(prog, pierscien.length, wierzcholki, idx) for idx in wybrane_idx]

    if not kandydaci:
        return
    # Jednorazowe rysowanie figury daje działający renderer - potrzebny do
    # zmierzenia FAKTYCZNEJ szerokości napisu przed wycięciem fragmentu konturu.
    ax.get_figure().canvas.draw()
    renderer = ax.get_figure().canvas.get_renderer()
    for prog, obwod, wierzcholki, idx in kandydaci:
        tekst = tekst_progu(prog)
        dlugosc = dlugosc_tekstu_w_danych(ax, tekst, fontsize=fontsize, renderer=renderer)
        if obwod < MIN_OBWOD_W_ETYKIETACH * dlugosc:
            continue
        fragment = wytnij_fragment_konturu(wierzcholki, idx, dlugosc)
        if len(fragment) < 2:
            continue
        etykieta = TekstWzdlugKonturu(fragment[:, 0], fragment[:, 1], tekst, ax,
                                      fontsize=fontsize, color=kolor)
        etykieta.set_path_effects([patheffects.withStroke(linewidth=2.5, foreground='white')])


class TekstWzdlugKonturu(mtext.Text):
    """
    Etykieta rysowana znak po znaku wzdłuż podanej łamanej (fragmentu linii
    konturu), tak by jej KSZTAŁT i POŁOŻENIE dopasowywały się do przebiegu
    granicy zasięgu - w przeciwieństwie do zwykłego napisu (np. z
    ax.clabel), który jest sztywnym, jednolicie obróconym prostokątem
    nałożonym obok konturu i przy mocno wygiętych granicach przecina je pod
    przypadkowym kątem.

    Adaptacja klasycznego triku z osobnym artystą Text na każdy znak: obiekt
    macierzysty (ten) sam nic nie rysuje (pusty tekst), ale przy KAŻDYM
    rysowaniu figury przelicza pozycję i obrót swoich "dzieci" na podstawie
    faktycznie wyrenderowanej szerokości ich glifów (stąd potrzebny jest
    `renderer` - szerokości w jednostkach danych zależą od skali osi).
    Dzieci mają wyższy zorder niż rodzic, żeby w tym samym przebiegu
    Axes.draw() rodzic zdążył ustawić im pozycję, zanim same się narysują.

    Każdy znak ma DWÓCH "dzieci" w tym samym miejscu: `_otoczki` (rysuje
    tylko biały path effect z set_path_effects, bez właściwego glifu) i
    `_znaki` (zwykły, kolorowy glif, bez żadnego path effect). Otoczki
    WSZYSTKICH znaków mają niższy zorder niż glify WSZYSTKICH znaków, więc
    Axes.draw() rysuje całą warstwę otoczek, a dopiero potem całą warstwę
    glifów. Gdyby zamiast tego każdy znak sam rysował swoją otoczkę i glif
    jedno po drugim (zwykłe `Text.set_path_effects`), to przy znakach
    ułożonych ciasno obok siebie bez kerningu otoczka znaku narysowanego
    później potrafiła nachodzić na i przysłaniać glif sąsiada narysowanego
    wcześniej. Rozbicie na dwie warstwy gwarantuje, że każdy glif kończy na
    wierzchu wszystkich otoczek, niezależnie od kolejności rysowania
    poszczególnych znaków.
    """

    def __init__(self, sciezka_x, sciezka_y, tekst, axes, **kwargs):
        super().__init__(sciezka_x[0], sciezka_y[0], '', **kwargs)
        axes.add_artist(self)

        self._sciezka_x = np.asarray(sciezka_x, dtype=float)
        self._sciezka_y = np.asarray(sciezka_y, dtype=float)

        self._otoczki = []
        self._znaki = []
        for znak in tekst:
            otoczka = mtext.Text(0, 0, znak, **kwargs)
            otoczka.set_ha('center')
            otoczka.set_va('center')
            otoczka.set_rotation_mode('anchor')
            otoczka.set_zorder(self.get_zorder() + 1)
            axes.add_artist(otoczka)
            self._otoczki.append(otoczka)

            t = mtext.Text(0, 0, znak, **kwargs)
            t.set_ha('center')
            t.set_va('center')
            t.set_rotation_mode('anchor')
            t.set_zorder(self.get_zorder() + 2)
            axes.add_artist(t)
            self._znaki.append(t)

    def set_zorder(self, zorder):
        super().set_zorder(zorder)
        for o in self._otoczki:
            o.set_zorder(zorder + 1)
        for t in self._znaki:
            t.set_zorder(zorder + 2)

    def set_path_effects(self, path_effects):
        # Efekt (np. biała obwódka) trafia WYŁĄCZNIE na warstwę otoczek,
        # rysowaną w całości pod warstwą glifów - patrz docstring klasy.
        for o in self._otoczki:
            o.set_path_effects(path_effects)

    def draw(self, renderer, *args, **kwargs):
        if not self.get_visible() or not self._znaki:
            return
        super().draw(renderer, *args, **kwargs)

        xy_ekran = self.axes.transData.transform(
            np.column_stack([self._sciezka_x, self._sciezka_y])
        )
        dx = np.diff(xy_ekran[:, 0])
        dy = np.diff(xy_ekran[:, 1])
        odcinki = np.hypot(dx, dy)
        skum = np.insert(np.cumsum(odcinki), 0, 0.0)
        dlugosc_calkowita = skum[-1]
        if dlugosc_calkowita <= 0:
            return

        szerokosci = []
        for t in self._znaki:
            t.set_rotation(0)
            bbox = t.get_window_extent(renderer=renderer)
            szerokosci.append(max(bbox.width, 1.0))

        # Wyśrodkowanie napisu na dostępnym fragmencie ścieżki.
        pozycja = max(dlugosc_calkowita - sum(szerokosci), 0.0) / 2.0
        odwrotna_transformata = self.axes.transData.inverted()

        for t, o, szerokosc in zip(self._znaki, self._otoczki, szerokosci):
            srodek = min(pozycja + szerokosc / 2.0, dlugosc_calkowita)
            idx = int(np.clip(np.searchsorted(skum, srodek) - 1, 0, len(odcinki) - 1))
            odcinek_dl = odcinki[idx] if odcinki[idx] > 1e-9 else 1e-9
            frakcja = np.clip((srodek - skum[idx]) / odcinek_dl, 0.0, 1.0)

            px = xy_ekran[idx, 0] + frakcja * dx[idx]
            py = xy_ekran[idx, 1] + frakcja * dy[idx]
            kat = np.degrees(np.arctan2(dy[idx], dx[idx]))

            x_dane, y_dane = odwrotna_transformata.transform((px, py))
            t.set_position((x_dane, y_dane))
            t.set_rotation(kat)
            o.set_position((x_dane, y_dane))
            o.set_rotation(kat)

            pozycja += szerokosc


def wytnij_fragment_konturu(wierzcholki, idx_start, dlugosc_docelowa):
    """
    Wycina z zamkniętej łamanej `wierzcholki` (np. exterior.coords wielokąta
    zasięgu) ciągły fragment o długości ~`dlugosc_docelowa`, wyśrodkowany na
    wierzchołku `idx_start` - do naniesienia na niego etykiety podążającej
    kształtem za konturem (TekstWzdlugKonturu).

    Tablicę obracamy (np.roll) tak, by `idx_start` znalazł się blisko
    środka - pozwala to ciąć zwykłym wycinkiem zamiast liczyć zawijanie się
    indeksów na krańcach zamkniętego pierścienia.
    """
    n = len(wierzcholki)
    if n < 2:
        return np.asarray(wierzcholki)

    srodek = n // 2
    przesuniecie = (srodek - idx_start) % n
    obrocone = np.roll(np.asarray(wierzcholki), przesuniecie, axis=0)

    odcinki = np.hypot(np.diff(obrocone[:, 0]), np.diff(obrocone[:, 1]))
    skum = np.insert(np.cumsum(odcinki), 0, 0.0)
    pozycja_srodka = skum[srodek]

    lo = max(int(np.searchsorted(skum, pozycja_srodka - dlugosc_docelowa / 2)), 0)
    hi = min(int(np.searchsorted(skum, pozycja_srodka + dlugosc_docelowa / 2)) + 1, n)
    fragment = obrocone[lo:hi]

    # Etykieta ma czytać się od lewej do prawej - jeśli wycięty fragment
    # biegnie "wstecz" względem osi X, odwracamy kolejność punktów, żeby
    # tekst nie wyszedł do góry nogami.
    if len(fragment) >= 2 and fragment[-1, 0] < fragment[0, 0]:
        fragment = fragment[::-1]
    return fragment


def dlugosc_tekstu_w_danych(ax, tekst, fontsize, renderer):
    """
    Szacuje długość (w jednostkach danych osi `ax`) potrzebną, by pomieścić
    `tekst` narysowany fontsize'em `fontsize`, na podstawie FAKTYCZNIE
    wyrenderowanej szerokości glifów (renderer) i bieżącej skali danych na
    piksel tej osi. Wynik służy tylko do wybrania, jak duży fragment
    konturu wyciąć (wytnij_fragment_konturu) - precyzja nie jest krytyczna,
    bo TekstWzdlugKonturu i tak przelicza finalną pozycję/obrót każdego
    znaku od nowa przy każdym renderowaniu figury.

    Mnożnik zapasu koryguje na to, że tekst będzie ułożony na krzywej (a nie
    po linii prostej) - krzywizna wydłuża potrzebny fragment konturu
    względem prostej szerokości napisu.
    """
    tymczasowy = mtext.Text(0, 0, tekst, fontsize=fontsize)
    tymczasowy.set_figure(ax.get_figure())
    szerokosc_px = tymczasowy.get_window_extent(renderer=renderer).width

    p0 = ax.transData.transform((0, 0))
    p1 = ax.transData.transform((1, 0))
    px_na_jednostke = max(np.hypot(*(p1 - p0)), 1e-9)

    ZAPAS_NA_KRZYWIZNE = 1.8
    return ZAPAS_NA_KRZYWIZNE * szerokosc_px / px_na_jednostke


def wymus_wspolne_pasmo(kde_docelowe, kde_wzorcowe):
    """
    Wymusza na `kde_docelowe` (scipy.stats.gaussian_kde) DOKŁADNIE tę samą
    fizyczną macierz kowariancji/pasma wygładzania co w `kde_wzorcowe`.

    Samo przekazanie `bw_method=kde_wzorcowe.factor` przy tworzeniu drugiego
    gaussian_kde NIE wystarcza: scipy zawsze liczy
    `covariance = factor**2 * kowariancja_WŁASNYCH danych tego KDE`
    (scipy.stats.gaussian_kde._compute_covariance), więc dwa zbiory punktów
    o innym rozrzucie lub innych wagach dostają różne fizyczne pasmo mimo
    identycznego `factor` - sprawdzone empirycznie (test na syntetycznych
    danych), różnica rzędu 10-100x przy realistycznym scenariuszu
    przestrzennego skupienia zdarzeń względem tła. To podważa poprawność
    ilorazu dwóch gęstości (ryzyko względne / lokalna średnia
    Nadaraya-Watson), który wymaga wspólnego pasma dla licznika i mianownika.

    Nadpisuje dokładnie te atrybuty, które scipy.stats.gaussian_kde.evaluate()
    faktycznie czyta (covariance, cho_cov, log_det, factor) - zweryfikowane
    numerycznie względem ręcznie policzonej ważonej gęstości Gaussa z zadaną
    macierzą kowariancji.
    """
    kde_docelowe.covariance = kde_wzorcowe.covariance
    kde_docelowe.cho_cov = kde_wzorcowe.cho_cov
    kde_docelowe.log_det = kde_wzorcowe.log_det
    kde_docelowe.factor = kde_wzorcowe.factor
    return kde_docelowe


def korekta_brzegowa(mask, x_grid, y_grid, covariance):
    """
    Korekta brzegowa Diggle'a (1985) dla ważonej 2D KDE na siatce regularnej.

    scipy.stats.gaussian_kde nie wie nic o granicy obszaru (tu: granicy
    Polski) - jądro wycentrowane blisko brzegu "traci" część masy poza
    obszar, w którym w ogóle mogłyby zostać zaobserwowane punkty, przez co
    gęstość blisko granicy jest systematycznie ZANIŻONA. To ten sam
    mechanizm, który po stronie R koryguje `edge="diggle"` w
    spatstat/sparr (patrz policz_ryzyko.R).

    Dla ILORAZU dwóch gęstości o tym samym pasmie (ryzyko względne,
    lokalna średnia Nadaraya-Watson - kde_uszkodzenia.py,
    kde_martwe_drewno.py) błąd brzegowy w liczniku i mianowniku jest ten
    sam i w przybliżeniu się kasuje, więc korekty tam celowo NIE stosujemy.
    Dla POJEDYNCZEJ gęstości (kde_gat.py - zasięg gatunku) nic go nie
    kasuje, więc trzeba korygować wprost.

    Zwraca macierz c(x) tego samego kształtu co siatka X/Y: ułamek masy
    jądra (o macierzy kowariancji `covariance`, tej samej co użyta do
    zbudowania ocenianej gęstości), który mieści się w oknie analizy
    `mask`. Estymator skorygowany to `Z / c(x)` (nie mnożenie).
    """
    dx = x_grid[1] - x_grid[0]
    dy = y_grid[1] - y_grid[0]

    inv_cov = np.linalg.inv(covariance)
    sigma_x = np.sqrt(covariance[0, 0])
    sigma_y = np.sqrt(covariance[1, 1])
    # promień jądra w komórkach siatki (~6 sigma wystarcza numerycznie -
    # masa Gaussa poza 6 sigma jest pomijalna)
    half_x = max(3, int(np.ceil(6 * sigma_x / dx)))
    half_y = max(3, int(np.ceil(6 * sigma_y / dy)))

    kx = np.arange(-half_x, half_x + 1) * dx
    ky = np.arange(-half_y, half_y + 1) * dy
    KX, KY = np.meshgrid(kx, ky)

    mahal = (
        inv_cov[0, 0] * KX ** 2
        + 2 * inv_cov[0, 1] * KX * KY
        + inv_cov[1, 1] * KY ** 2
    )
    norm = 2 * np.pi * np.sqrt(np.linalg.det(covariance))
    kernel = np.exp(-0.5 * mahal) / norm
    kernel *= dx * dy  # dyskretna aproksymacja całki (kernel sumuje się do ~1)

    c = fftconvolve(mask.astype(float), kernel, mode="same")
    # daleko od obszaru maska*jądro ~ 0 - zabezpieczenie przed dzieleniem
    # przez ~0 (i tak odcięte później przez maskę Polski na Z)
    return np.clip(c, 1e-3, 1.0)


def dodaj_podklad(ax, crs, szary=True, rozjasnienie=0.65, rozdzielczosc_px=2500,
                  plik=PODKLAD_TIF, podpis=PODKLAD_PODPIS):
    """
    Rysuje podkład z rastra `plik` pod wszystkimi warstwami osi (zorder 0),
    w zasięgu BIEŻĄCYCH granic osi - wywoływać po ax.set_xlim/set_ylim, jak
    wcześniej contextily.add_basemap. Raster jest przeliczany do `crs` osi
    (np. EPSG:2180) na siatkę rozdzielczosc_px po dłuższym boku, interpolacja
    dwuliniowa (raster jest ok. 5x grubszy niż piksel mapy PNG 300 dpi).

    szary=True - odcienie szarości (luminancja) rozjaśnione o `rozjasnienie`
        (0 = bez zmian, 1 = biel), żeby barwne pasma KDE czytały się jak na
        dawnym szarym podkładzie - wariant wybrany przez użytkownika na stałe
        (2026-10-09). Przy 0,35 szare punkty traktów (gray, alpha 0.3) ginęły
        w teksturze cieniowania rzeźby; 0,7 było już czytelne, użytkownik
        wybrał odrobinę ciemniejsze 0,65; False - kolory oryginalne.
    podpis - tekst w lewym dolnym rogu osi (jak atrybucja kafelków); None = brak.
    """
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    skala = rozdzielczosc_px / max(xmax - xmin, ymax - ymin)
    szer, wys = max(1, round((xmax - xmin) * skala)), max(1, round((ymax - ymin) * skala))
    obraz = np.zeros((3, wys, szer), dtype=np.uint8)
    with rasterio.open(plik) as src:
        for i in range(3):
            reproject(rasterio.band(src, i + 1), obraz[i],
                      dst_transform=from_bounds(xmin, ymin, xmax, ymax, szer, wys),
                      dst_crs=crs, resampling=Resampling.bilinear)
    obraz = np.moveaxis(obraz, 0, -1).astype(float) / 255
    if szary:
        jasnosc = obraz @ np.array([0.299, 0.587, 0.114])
        obraz = np.repeat(jasnosc[..., None], 3, axis=2)
    obraz = obraz + (1 - obraz) * rozjasnienie
    ax.imshow(obraz, extent=(xmin, xmax, ymin, ymax), origin='upper', zorder=0,
              interpolation='bilinear')
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    if podpis:
        ax.text(0.005, 0.005, podpis, transform=ax.transAxes, fontsize=6,
                color='#333333', ha='left', va='bottom', zorder=10)


# Wiarygodność modelu: obszary, w których lokalny wynik opiera się na małej
# liczbie traktów, są kreskowane na mapach PNG i zapisywane osobno
# (KDE_*/wiarygodnosc/<nazwa>.geojson) dla portalu. Miarą jest efektywna
# liczba traktów tła n_eff - ile traktów faktycznie decyduje o wyniku w danym
# miejscu przy tych samych wagach i paśmie co KDE tła (2026-10-09: przy
# mapach ze wszystkich traktów n_eff >= 92 w każdym miejscu, przy tle jednego
# gatunku, np. jodły, poniżej 30 na 45% obszaru). Ograniczenie: n_eff mówi
# o liczbie traktów TŁA, nie o rzadkości zjawiska w liczniku (np. jedna
# przyczyna uszkodzeń) - tego miara nie obejmuje.
MIN_EFEKTYWNYCH_TRAKTOW = 30
# Poniżej MIN_TRAKTOW_DO_MAPY wyniku w ogóle nie ma (decyzja użytkownika
# 2026-10-09, jak min. 10 traktów w obszarze sparr): przy n_eff < 10 przedział
# ufności udziału ~30% to ok. +-28 punktów, czyli kilka pasm naraz - np. pasma
# "> 50%" uszkodzeń jodły 2020-2025 w Sudetach i na Roztoczu opierały się na
# 3-5 traktach. Między 10 a 30 - wynik z kreskowaniem.
MIN_TRAKTOW_DO_MAPY = 10
PRZYPIS_ODCIECIA = (f"Bez koloru tam, gdzie wynik opierałby się na efektywnie mniej niż "
                    f"{MIN_TRAKTOW_DO_MAPY} traktach.")


def odetnij_malo_traktow(wartosc, n_eff, minimum=MIN_TRAKTOW_DO_MAPY):
    """NaN w `wartosc` i `n_eff` (w miejscu) tam, gdzie n_eff < minimum.
    Wołać PRZED wyznaczeniem maksimum i progów mapy. Zwraca True, gdy coś
    odcięto (wtedy pod mapą PRZYPIS_ODCIECIA)."""
    odciete = np.isfinite(n_eff) & (n_eff < minimum)
    wartosc[odciete] = np.nan
    n_eff[odciete] = np.nan
    return bool(odciete.any())


def dodaj_przypis(ax, tekst, szerokosc=120):
    """Uwaga pod mapą, pod opisem osi X (jak adnotacje kde_uszkodzenia_sparr.py)."""
    import textwrap
    ax.annotate("\n".join(textwrap.wrap(tekst, szerokosc)), xy=(0, 0), xycoords="axes fraction",
                xytext=(0, -40), textcoords="offset points", fontsize=8, color="#555555",
                va="top", ha="left", annotation_clip=False)


def efektywna_liczba_traktow(coords, wagi, kernel_tla, positions, g_tla=None):
    """
    n_eff(x) = (sum w_i K_i(x))^2 / sum (w_i K_i(x))^2 na punktach `positions`,
    K - jądro Gaussa z kowariancją kernel_tla.covariance (to samo pasmo co tło).
    Liczone analitycznie: K^2 to jądro o kowariancji Sigma/2 przemnożone przez
    1 / (4 pi sqrt|Sigma|), więc mianownik to drugie KDE (wagi w^2, Sigma/2).
    Sprawdzone 2026-10-09 względem sumowania wprost (różnica ~1e-15).
    kernel_tla - KDE tła z TYMI SAMYMI wagami `wagi`; g_tla - jego wartości
    w `positions`, jeśli już policzone (oszczędza jedną ewaluację KDE).
    """
    wagi = np.asarray(wagi, dtype=float)
    cov = kernel_tla.covariance
    k2 = gaussian_kde(coords, weights=wagi ** 2)
    k2.covariance = cov / 2
    k2.cho_cov = np.linalg.cholesky(cov / 2)
    k2.log_det = 2 * np.log(np.diag(k2.cho_cov * np.sqrt(2 * np.pi))).sum()
    g1 = kernel_tla(positions) if g_tla is None else np.asarray(g_tla).ravel()
    g2 = k2(positions)
    with np.errstate(divide='ignore', invalid='ignore'):
        return (4 * np.pi * np.sqrt(np.linalg.det(cov)) * wagi.sum() ** 2 / (wagi ** 2).sum()
                * g1 ** 2 / g2)


def oznacz_niska_wiarygodnosc(ax, X, Y, n_eff, prog=MIN_EFEKTYWNYCH_TRAKTOW):
    """
    Kreskuje obszar n_eff < prog (n_eff = NaN poza obszarem z wartościami
    mapy - tam nic nie rysuje). Zwraca (wielokąt obszaru w układzie osi albo
    None, uchwyt do legendy albo None).
    """
    n = np.asarray(n_eff, dtype=float).reshape(X.shape)
    if not np.any(n < prog):
        return None, None
    kreski = ax.contourf(X, Y, np.where(n < prog, 1.0, np.nan), levels=[0.5, 1.5],
                         colors='none', hatches=['////'], zorder=3)
    kreski.set_edgecolor((0.25, 0.25, 0.25, 0.55))
    kreski.set_linewidth(0)
    # wielokąt obszaru: kontur (prog - n_eff) >= 0, NaN poza mapą jako -1 -
    # pętle zamknięte jak w pozostałych konturach (kontur_na_zasieg)
    pomocniczy = ax.contour(X, Y, np.nan_to_num(prog - n, nan=-1.0), levels=[0.0],
                            linewidths=0)
    obszar = kontur_na_zasieg(pomocniczy.allsegs[0])
    pomocniczy.remove()
    uchwyt = mpatches.Patch(facecolor='none', edgecolor=(0.25, 0.25, 0.25, 0.8), hatch='////',
                            label=f'Mało traktów (efektywnie {MIN_TRAKTOW_DO_MAPY}–{prog})')
    return obszar, uchwyt


def zapisz_wiarygodnosc(obszar, sciezka_geojson, crs, crs_zapisu="EPSG:4326",
                        prog=MIN_EFEKTYWNYCH_TRAKTOW):
    """Zapis obszaru małej liczby traktów obok wyniku mapy:
    KDE_x/nazwa.geojson -> KDE_x/wiarygodnosc/nazwa.geojson (podkatalog, żeby
    wzorce plików portalu go nie łapały). Brak obszaru = brak pliku (stary
    plik jest usuwany)."""
    import os
    import geopandas as gpd
    katalog, nazwa = os.path.split(sciezka_geojson)
    cel = os.path.join(katalog, 'wiarygodnosc', nazwa)
    if os.path.exists(cel):
        os.remove(cel)
    if obszar is None or obszar.is_empty:
        return None
    os.makedirs(os.path.dirname(cel), exist_ok=True)
    gpd.GeoDataFrame([{'min_efektywnych_traktow': prog, 'min_traktow_do_mapy': MIN_TRAKTOW_DO_MAPY,
                       'geometry': obszar}],
                     geometry='geometry', crs=crs).to_crs(crs_zapisu).to_file(cel, driver='GeoJSON')
    return cel


def efektywna_liczba_traktow_siatka(coords, wagi, kernel_tla, X, Y, wartosc=None, krok=5,
                                    progi=(MIN_TRAKTOW_DO_MAPY, MIN_EFEKTYWNYCH_TRAKTOW),
                                    margines=0.3):
    """
    n_eff na siatce X, Y (meshgrid), liczone co `krok` punktów i dwuliniowo
    interpolowane - n_eff zmienia się płynnie w skali pasma (~30 km), a oczko
    siatki 500x500 to ~1,4 km, więc rzadsza siatka wystarcza, a jest ~krok^2
    razy szybsza.
    Interpolacja myli się najbardziej tam, gdzie traktów jest mało i n_eff
    zmienia się stromo (brzegi skupisk gatunku - jodła 2020-2025: do 7,5%,
    mapy ze wszystkich traktów: ~1%), więc oczka z wynikiem w pobliżu progów
    (odcięcia i kreskowania, ±margines) są liczone dokładnie - granice są
    takie jak przy obliczeniu na pełnej siatce.
    wartosc: powierzchnia mapy - poza nią (NaN) n_eff = NaN.
    """
    from scipy.interpolate import RegularGridInterpolator
    xs, ys = X[0, ::krok], Y[::krok, 0]
    if xs[-1] != X[0, -1]:
        xs, ys = np.append(xs, X[0, -1]), np.append(ys, Y[-1, 0])
    XX, YY = np.meshgrid(xs, ys)
    rzadka = efektywna_liczba_traktow(coords, wagi, kernel_tla,
                                      np.vstack([XX.ravel(), YY.ravel()])).reshape(XX.shape)
    interp = RegularGridInterpolator((ys, xs), rzadka)
    n_eff = interp(np.column_stack([Y.ravel(), X.ravel()])).reshape(X.shape)
    if wartosc is not None:
        n_eff[np.isnan(wartosc)] = np.nan
    blisko = np.isfinite(n_eff) & np.any([np.abs(n_eff / p - 1) < margines for p in progi], axis=0)
    if blisko.any():
        n_eff[blisko] = efektywna_liczba_traktow(coords, wagi, kernel_tla, np.vstack([X[blisko], Y[blisko]]))
    return n_eff
