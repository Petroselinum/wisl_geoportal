import numpy as np

def calculate_min_opacity_log(num_points, min_val=0.0, max_val=0.8):
    """
    Logarytmiczne skalowanie opacity - płynniejsze przejścia.
    """
    if num_points < 10:
        return max_val
    
    
    log_points = np.log10(num_points)
    log_min = np.log10(10)     
    log_max = np.log10(20_000)  
    
    # Normalizuj do zakresu [0, 1]
    normalized = (log_points - log_min) / (log_max - log_min)
    normalized = np.clip(normalized, 0, 1)
    
    # Odwróć (więcej punktów = niższa opacity)
    opacity = max_val - normalized * (max_val - min_val)
    
    return round(opacity, 2)