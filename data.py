import pandas as pd

def wisl_rdlp_info(cykl):
    wisl_rdlp_cykl4 = {
        'RDLP':['BIAŁYSTOK', 'GDAŃSK', 'KATOWICE', 'KRAKÓW', 
                'KROSNO', 'LUBLIN', 'ŁÓDŹ', 'OLSZTYN', 'PIŁA', 
                'POZNAŃ', 'RADOM', 'SZCZECIN', 'SZCZECINEK',
                'TORUŃ', 'WARSZAWA', 'WROCŁAW', 'ZIELONA GÓRA'],
        'Powierzchnia lasów\nw zarządzie PGL LP [tys. ha]':[574.6, 284.6, 599.4, 167.6, 401.9, 
                                                        398.1, 283.4, 577.6, 339.3, 408.3, 309.4,
                                                        640.9, 570.8, 422.0, 183.8, 527.2, 425.1],
        'Miąższość [mln m³ grubizny brutto]\nlasów w zarządzie PGL LP':[168.4, 82.7, 168.9, 61.3, 136.3,
                                                                        116.1, 77.6, 169.4, 93.0, 110.4,
                                                                        84.9, 200.4, 163.6, 118.8, 48.8,
                                                                        154.4, 111.1],
        'Zasobność [m³/ha grubizny brutto] lasów w zarządzie PGL LP': [292.9, 290.4, 281.9, 365.8, 339.1,
                                                                    291.7, 273.9, 293.3,
                                                                    274.2, 270.3, 274.2, 312.6, 286.5,
                                                                    281.6, 265.7, 292.9, 261.4],
        'Średni wiek lasów': [57, 65, 57, 73, 67, 63, 61, 58, 55, 61, 65, 56, 57, 62, 58, 60, 57],
        'Martwe drewno [m³/ha grubizny brutto]': [18.7, 9.1, 10.7, 18.5, 27.2, 9.4, 8.9, 10.9, 8.0, 11.2, 8.5, 7.9, 8.7, 5.5, 8.4, 11.2, 8.0]

    }
    if cykl == 4:
        return wisl_rdlp_cykl4

rdlp = ['BIAŁYSTOK', 'GDAŃSK', 'KATOWICE', 'KRAKÓW', 
                'KROSNO', 'LUBLIN', 'ŁÓDŹ', 'OLSZTYN', 'PIŁA', 
                'POZNAŃ', 'RADOM', 'SZCZECIN', 'SZCZECINEK',
                'TORUŃ', 'WARSZAWA', 'WROCŁAW', 'ZIELONA GÓRA']
def lata(rok):
    return [f'{rok} - {rok + 4}' for i in range(17)]

def zasob_time_rdlp():
    wisl_zasob_2005_rdlp ={
        'lata': lata(2005),
        'rdlp': rdlp,
        'zasobnosc':[261.9,
272.4,
262.1,
317.0,
300.0,
269.0,
256.7,
267.6,
240.4,
247.5,
258.7,
265.8,
255.2,
247.1,
253.2,
267.9,
231.4]
    }

    wisl_zasob_2006_rdlp ={
        'lata': lata(2006),
        'rdlp': rdlp,
        'zasobnosc':[263.4, 275.8, 263.5, 323.7, 300.5, 272.8, 257.8, 269.0, 240.1, 248.6, 258.2, 268.3, 258.9, 251.6, 252.9, 270.2, 235.4]
    }

    wisl_zasob_2007_rdlp ={
        'lata': lata(2007),
        'rdlp': rdlp,
        'zasobnosc':[267.2, 278.4, 266.8, 329.0, 301.3, 273.6, 258.7, 269.8, 243.8, 250.9, 260.1, 271.4, 261.4, 256.6, 258.1, 273.6, 239.2]
    }

    wisl_zasob_2008_rdlp ={
        'lata': lata(2008),
        'rdlp': rdlp,
        'zasobnosc':[270.9, 281.2, 270.6, 335.9, 307.4, 275.5, 261.2, 271.0, 246.5, 252.9, 262.8, 276.6, 262.4, 262.2, 259.7, 274.8, 240.1]
    }

    wisl_zasob_2009_rdlp ={
        'lata': lata(2009),
        'rdlp': rdlp,
        'zasobnosc':[275.1, 280.6, 272.6, 337.0, 312.1, 278.8, 261.7, 273.1, 246.2, 257.5, 264.1, 281.4, 265.7, 265.5, 260.0, 279.0, 242.5]
    }

    wisl_zasob_2010_rdlp ={
        'lata': lata(2010),
        'rdlp': rdlp,
        'zasobnosc':[277.0, 281.0, 275.0, 340.0, 316.0, 281.0, 264.0, 277.0, 249.0, 260.0, 266.0, 286.0, 267.0, 270.0, 264.0, 282.0, 245.0]
    }

    wisl_zasob_2011_rdlp ={
        'lata': lata(2011),
        'rdlp': rdlp,
        'zasobnosc':[281.0, 284.6, 277.1, 342.1, 319.4, 281.4, 264.7, 282.5, 253.9, 262.2, 269.2, 290.9, 271.8, 275.8, 262.6, 286.1, 249.1]
    }

    wisl_zasob_2012_rdlp ={
        'lata': lata(2012),
        'rdlp': rdlp,
        'zasobnosc':[285.4, 288.8, 280.0, 348.8, 324.9, 283.9, 269.2, 284.4, 258.5, 263.9, 268.8, 295.9, 277.2, 279.5, 264.6, 289.0, 252.8]
    }

    wisl_zasob_2013_rdlp ={
        'lata': lata(2013),
        'rdlp': rdlp,
        'zasobnosc':[288.4, 291.4, 281.8, 357.6, 327.9, 288.7, 272.3, 287.5, 265.0, 266.6, 270.2, 302.4, 278.7, 281.6, 267.8, 290.8, 257.2]
    }

    wisl_zasob_2014_rdlp ={
        'lata': lata(2014),
        'rdlp': rdlp,
        'zasobnosc':[289.0, 290.8, 280.3, 357.3, 335.9, 289.2, 271.7, 291.4, 269.5, 269.2, 272.4, 309.5, 282.5, 282.6, 266.2, 291.9, 261.0]
    }

    wisl_zasob_2015_rdlp ={
        'lata': lata(2015),
        'rdlp': rdlp,
        'zasobnosc':[292.9, 290.4, 281.9, 365.8, 339.1, 291.7, 273.9, 293.3, 274.2, 270.3, 274.2, 312.6, 286.5, 281.6, 265.7, 292.9, 261.4]
    }

    wisl_zasob_2016_rdlp ={
        'lata': lata(2016),
        'rdlp': rdlp,
        'zasobnosc':[292.8, 289.4, 281.6, 368.3, 341.2, 293.1, 274.1, 292.8, 276.4, 269.8, 273.8, 312.3, 287.7, 280.2, 265.4, 290.1, 262.6]
    }

    wisl_zasob_2017_rdlp ={
        'lata': lata(2017),
        'rdlp': rdlp,
        'zasobnosc':[293.6, 289.8, 279.8, 370.6, 347.3, 293.7, 273.9, 291.5, 275.9, 270.3, 277.3, 312.0, 289.5, 275.4, 263.5, 291.1, 263.7]
    }

    wisl_zasob_2018_rdlp ={
        'lata': lata(2018),
        'rdlp': rdlp,
        'zasobnosc':[293.4, 287.8, 276.9, 377.8, 349.4, 295.2, 272.1, 294.1, 277.3, 267.8, 272.9, 311.5, 289.0, 271.5, 264.7, 289.2, 264.6]
    }

    wisl_zasob_2019_rdlp ={
        'lata': lata(2019),
        'rdlp': rdlp,
        'zasobnosc':[295.3, 286.3, 276.7, 379.2, 351.8, 294.1, 274.4, 296.9, 275.8, 268.3, 271.2, 310.4, 288.6, 271.0, 267.8, 287.7, 267.0]
    }

    wisl_zasob_2020_rdlp ={
        'lata': lata(2020),
        'rdlp': rdlp,
        'zasobnosc':[296.7, 287.3, 280.6, 382.4, 355.0, 298.0, 276.0, 297.6, 275.5, 268.3, 271.7, 309.3, 287.7, 272.2, 266.7, 287.7, 266.8]
    }

    df = pd.DataFrame()

    for i in [wisl_zasob_2005_rdlp,
            wisl_zasob_2006_rdlp,
            wisl_zasob_2007_rdlp,
            wisl_zasob_2008_rdlp,
            wisl_zasob_2009_rdlp,
            wisl_zasob_2010_rdlp,
            wisl_zasob_2011_rdlp,
            wisl_zasob_2012_rdlp,
            wisl_zasob_2013_rdlp,
            wisl_zasob_2014_rdlp,
            wisl_zasob_2015_rdlp,
            wisl_zasob_2016_rdlp,
            wisl_zasob_2017_rdlp,
            wisl_zasob_2018_rdlp,
            wisl_zasob_2019_rdlp,
            wisl_zasob_2020_rdlp]:
        
        df_i = pd.DataFrame(i)
        df = pd.concat([df, df_i], axis = 0)

    return df