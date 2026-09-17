import numpy as np
from scipy.signal import fftconvolve


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
