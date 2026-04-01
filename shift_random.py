import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from pyproj import Geod

def przesuń_punkty_losowo(gdf, min_odleglosc=500, max_odleglosc=1000):
    """
    Przesuwa punkty w GeoDataFrame w losowym kierunku o losową odległość.
    
    Parameters:
    -----------
    gdf : GeoDataFrame
        GeoDataFrame z geometrią punktową
    min_odleglosc : float
        Minimalna odległość przesunięcia w metrach (domyślnie 500)
    max_odleglosc : float
        Maksymalna odległość przesunięcia w metrach (domyślnie 1000)
    
    Returns:
    --------
    GeoDataFrame z przesuniętymi punktami
    """
    # Kopia GeoDataFrame
    gdf_copy = gdf.copy()
    
    # Geod do obliczeń geodezyjnych
    geod = Geod(ellps='WGS84')
    
    # Lista na nowe punkty
    new_points = []
    
    for idx, row in gdf_copy.iterrows():
        punkt = row.geometry
        
        # Losowy kierunek (azymut) 0-360 stopni
        azimut = np.random.uniform(0, 360)
        
        # Losowa odległość w metrach
        odleglosc = np.random.uniform(min_odleglosc, max_odleglosc)
        
        # Oblicz nowe współrzędne
        lon2, lat2, _ = geod.fwd(punkt.x, punkt.y, azimut, odleglosc)
        
        # Stwórz nowy punkt
        new_points.append(Point(lon2, lat2))
    
    # Zamień geometrię
    gdf_copy.geometry = new_points
    
    return gdf_copy