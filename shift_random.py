import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from pyproj import Geod

def przesuń_punkty_losowo(gdf, min_odleglosc=500, max_odleglosc=1000):
    
    
    gdf_copy = gdf.copy()
    
    geod = Geod(ellps='WGS84')
    
    new_points = []
    
    for idx, row in gdf_copy.iterrows():
        punkt = row.geometry
        azimut = np.random.uniform(0, 360)
        odleglosc = np.random.uniform(min_odleglosc, max_odleglosc)
        lon2, lat2, _ = geod.fwd(punkt.x, punkt.y, azimut, odleglosc)
        new_points.append(Point(lon2, lat2))
    
    # Zamień geometrię
    gdf_copy.geometry = new_points
    
    return gdf_copy