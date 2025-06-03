# Bot tokens and MySQL configuration
BOT_TOKENS = {
    "lucia": "7432922492:AAFf_TdrDSJ_zpMwDQOj9Nt12c9p_J6SWII",
    "luna": "8151632568:AAEo3QPayXZgpIAZmUSAi_e0ZBZkBoH97nk",
    "leo": "7577560442:AAGktXqPI8aWsidkYCDSsELtW8himYw-n5c",
    "bella": "7973851098:AAH7Kj53el1_gpIhmhLPWLklkvmEP_J9ZFY"
}

MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "root",
    "database": "italy_db"
}

# Bot configurations
BOT_CONFIGS = {
    "lucia": {
        "target_group": "Test_From_1",
        "target_topic": "#Glasses",
        "adjust_price": True,
        "add_watermark": True,
        "forward_to_buyers": [],
        "sort_by_brand": False
    },
    "luna": {
        "target_group": "Test_From_1",
        "target_topic": "#Glasses",
        "adjust_price": True,
        "add_watermark": True,
        "forward_to_buyers": [],
        "sort_by_brand": False
    },
    "leo": {
        "target_group": "Test_From_1",
        "target_topic": "#Man",
        "adjust_price": True,
        "add_watermark": True,
        "forward_to_buyers": ["Test_Buy_Muj"],
        "sort_by_brand": False
    },
    "bella": {
        "target_group": None,  # Determined by brand sorting
        "target_topic": None,  # Determined by brand sorting
        "adjust_price": True,
        "add_watermark": True,
        "forward_to_buyers": ["Test_Buy_1", "Test_Buy_2"],
        "sort_by_brand": True
    }
}

PROJECT_BOT_IDS = [
    7432922492,  # Lucia
    8151632568,  # Luna
    7577560442,  # Leo
    7973851098  # Bella
]

# List of known brands for fuzzy matching
KNOWN_BRANDS = [
    "GUESS", "Gucci", "Burberry", "Dior", "Brunello Cucinelli", "Prada", "Versace",
    "Chanel", "Louis Vuitton", "Fendi", "Balenciaga", "Givenchy", "Armani",
    "Dolce & Gabbana", "Hermès", "Yves Saint Laurent", "Bottega Veneta", "Saint Laurent",
    "Alexander McQueen", "Celine", "Valentino", "Loro Piana", "Moncler", "Zegna",
    "Max Mara", "Salvatore Ferragamo", "Stella McCartney", "Miu Miu", "Chloé",
    "Balmain", "Loewe", "Kenzo", "Issey Miyake", "Acne Studios", "A.P.C.", "Off-White",
    "Rick Owens", "Comme des Garçons", "Maison Margiela", "Jil Sander", "Lanvin",
    "Proenza Schouler", "Sacai", "The Row", "Victoria Beckham", "Courrèges",
    # Italian brands
    "Trussardi", "Missoni", "Moschino", "Etro", "Emilio Pucci", "Alberta Ferretti",
    "Roberto Cavalli", "Tod’s", "Hogan", "Aspesi", "Boglioli", "Canali", "Corneliani",
    "Pal Zileri", "Kiton", "La Perla", "Aquazzura", "Giuseppe Zanotti", "Sergio Rossi",
    "A.Testoni", "Fratelli Rossetti", "Geox", "Pollini", "Les Copains", "Pinko",
    "Patrizia Pepe", "Liu Jo", "Blumarine", "Agnona", "Lardini", "Fay", "N°21",
    "Redemption", "Philosophy di Lorenzo Serafini", "MSGM", "GCDS", "Sunnei", "Plan C",
    "Marco de Vincenzo",
    # Other global brands
    "Tom Ford", "Ralph Lauren", "Calvin Klein", "Michael Kors", "Tory Burch", "Kate Spade",
    "DKNY", "Ganni", "Zimmermann", "Sandro", "Maje", "Ba&sh", "Claudie Pierlot",
    "Reformation", "Nanushka", "Staud", "Rixo", "Self-Portrait", "Ulla Johnson",
    "Veronica Beard", "Carolina Herrera", "Oscar de la Renta", "Marchesa", "Jason Wu",
    "Prabal Gurung", "Rodarte", "Thom Browne", "Altuzarra", "Brandon Maxwell", "Khaite",
    "Tibi", "Erdem", "Emilia Wickstead", "Roksanda", "Molly Goddard", "Simone Rocha",
    "Christopher Kane", "JW Anderson", "Anya Hindmarch", "Mulberry", "Strathberry",
    "Manu Atelier", "Coperni", "Amina Muaddi", "Mach & Mach", "Gia Borghini",
    "Paris Texas", "Le Silla", "Stuart Weitzman", "Jimmy Choo", "Manolo Blahnik",
    "Christian Louboutin", "Roger Vivier"
]

# List of brand abbreviations
BRAND_ABBREVIATIONS = {
    'lv': 'Louis Vuitton',
    'ysl': 'Yves Saint Laurent',
    'd&g': 'Dolce & Gabbana',
    'cc': 'Chanel',
    'bv': 'Bottega Veneta',
    'sl': 'Saint Laurent',
    'mcq': 'Alexander McQueen',
    'dg': 'Dolce & Gabbana',
    'apc': 'A.P.C.',
    'mm': 'Maison Margiela',
    'cdg': 'Comme des Garçons',
    'mcm': 'Moncler',
    'sf': 'Salvatore Ferragamo',
    'sm': 'Stella McCartney',
    'zm': 'Zegna',
    'mmr': 'Max Mara',
    'lo': 'Loewe',
    'kn': 'Kenzo',
    'im': 'Issey Miyake',
    'as': 'Acne Studios',
    'ow': 'Off-White',
    'ro': 'Rick Owens',
    'js': 'Jil Sander',
    'ln': 'Lanvin',
    'ps': 'Proenza Schouler',
    'sc': 'Sacai',
    'tr': 'The Row',
    'vb': 'Victoria Beckham',
    'cr': 'Courrèges',
    'pr': 'Prada',
    'vs': 'Versace',
    'ar': 'Armani',
    'hm': 'Hermès',
    'bl': 'Balenciaga',
    'gv': 'Givenchy',
    'fd': 'Fendi',
    'di': 'Dior',
    'bc': 'Burberry',
    'gs': 'GUESS',
    # Italian brands
    'tr': 'Trussardi',
    'ms': 'Missoni',
    'mo': 'Moschino',
    'et': 'Etro',
    'pu': 'Emilio Pucci',
    'af': 'Alberta Ferretti',
    'rc': 'Roberto Cavalli',
    'td': 'Tod’s',
    'hg': 'Hogan',
    'ap': 'Aspesi',
    'bg': 'Boglioli',
    'cn': 'Canali',
    'co': 'Corneliani',
    'pz': 'Pal Zileri',
    'kt': 'Kiton',
    'lp': 'La Perla',
    'aq': 'Aquazzura',
    'gz': 'Giuseppe Zanotti',
    'sr': 'Sergio Rossi',
    'at': 'A.Testoni',
    'fr': 'Fratelli Rossetti',
    'gx': 'Geox',
    'pl': 'Pollini',
    'lc': 'Les Copains',
    'pk': 'Pinko',
    'pp': 'Patrizia Pepe',
    'lj': 'Liu Jo',
    'bm': 'Blumarine',
    'ag': 'Agnona',
    'ld': 'Lardini',
    'fy': 'Fay',
    'n21': 'N°21',
    'rd': 'Redemption',
    'ph': 'Philosophy di Lorenzo Serafini',
    'mg': 'MSGM',
    'gc': 'GCDS',
    'sn': 'Sunnei',
    'pc': 'Plan C',
    'mv': 'Marco de Vincenzo',
    # Other global brands
    'tf': 'Tom Ford',
    'rl': 'Ralph Lauren',
    'ck': 'Calvin Klein',
    'mk': 'Michael Kors',
    'tb': 'Tory Burch',
    'ks': 'Kate Spade',
    'dk': 'DKNY',
    'gn': 'Ganni',
    'zm': 'Zimmermann',
    'sd': 'Sandro',
    'mj': 'Maje',
    'bs': 'Ba&sh',
    'cp': 'Claudie Pierlot',
    'rf': 'Reformation',
    'nn': 'Nanushka',
    'st': 'Staud',
    'rx': 'Rixo',
    'sp': 'Self-Portrait',
    'uj': 'Ulla Johnson',
    'vb': 'Veronica Beard',
    'ch': 'Carolina Herrera',
    'od': 'Oscar de la Renta',
    'ma': 'Marchesa',
    'jw': 'Jason Wu',
    'pg': 'Prabal Gurung',
    'rt': 'Rodarte',
    'az': 'Altuzarra',
    'bm': 'Brandon Maxwell',
    'kh': 'Khaite',
    'ti': 'Tibi',
    'ed': 'Erdem',
    'ew': 'Emilia Wickstead',
    'rk': 'Roksanda',
    'mg': 'Molly Goddard',
    'sr': 'Simone Rocha',
    'ck': 'Christopher Kane',
    'ja': 'JW Anderson',
    'ah': 'Anya Hindmarch',
    'mb': 'Mulberry',
    'sb': 'Strathberry',
    'mt': 'Manu Atelier',
    'am': 'Amina Muaddi',
    'gb': 'Gia Borghini',
    'pt': 'Paris Texas',
    'ls': 'Le Silla',
    'sw': 'Stuart Weitzman',
    'jc': 'Jimmy Choo',
    'cl': 'Christian Louboutin',
    'rv': 'Roger Vivier'
}