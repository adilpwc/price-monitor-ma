from pathlib import Path
import yaml

def load_products(path:str='config/products.yml'):
    return yaml.safe_load(Path(path).read_text())
