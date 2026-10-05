import numpy as np
import matplotlib.text as mtext
from matplotlib import patheffects
import shapely
from shapely.geometry import Polygon
from scipy.signal import fftconvolve


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
    - obwód < MIN_OBWOD_W_ETYKIETACH x długość napisu - na krótkiej pętli
      napis zawija się wokół niej i nachodzi sam na siebie.
    Punkty kotwiczące leżą dalej niż BORDER_TOL od granicy Polski (etykieta
    nie może wyglądać jak opis granicy kraju), wybierane zachłannie od
    najdalszego od granicy, w odstępach co najmniej MIN_ODSTEP.

    tekst_progu: funkcja prog -> napis etykiety.
    """
    MIN_POWIERZCHNIA = 3e8         # m^2 (300 km^2)
    MIN_OBWOD_W_ETYKIETACH = 4     # obwód pętli / długość napisu (z zapasem na krzywiznę)
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
