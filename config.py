# Токены ботов и конфигурация MySQL
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

# Конфигурации ботов
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
        "target_topic": "#Glasses",  # Assuming same as Lucia
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

# Список известных брендов для нечеткого соответствия
KNOWN_BRANDS = [
    "GUESS", "Gucci", "Burberry", "Dior", "Brunello Cucinelli", "Prada", "Versace",
    "Chanel", "Louis Vuitton", "Fendi", "Balenciaga", "Givenchy", "Armani",
    "Dolce & Gabbana", "Hermès", "Yves Saint Laurent"
]