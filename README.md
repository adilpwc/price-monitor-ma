# Price Monitor MA — V1

Surveillance open-source des prix marocains. Cette V1 recherche les produits configurés sur **UltraPC**, historise les offres dans SQLite et envoie une alerte Telegram lorsque le prix passe sous le seuil ou varie significativement.

> Le scraper utilise uniquement les pages publiques et ne contourne ni CAPTCHA, ni authentification, ni protection anti-bot. Vérifiez régulièrement les conditions d'utilisation et `robots.txt` du site.

## Fonctionnalités

- produits et seuils dans YAML, sans modification du code ;
- scraper UltraPC avec sélecteurs HTML et repli JSON-LD ;
- normalisation, tokens obligatoires et fuzzy matching ;
- prix MAD avec espaces, points et virgules ;
- historique SQLite, prix précédent, minimum et variation ;
- alertes Telegram sans doublons ;
- reprise réseau et isolation des erreurs ;
- exécution locale, planifiée toutes les deux heures et manuelle ;
- tests, Ruff et mypy dans la CI.

## Installation locale

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell : .venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pytest
```

## Configuration des produits

Modifier `config/products.yml` :

```yaml
products:
  - name: "Lenovo Legion 27U-10"
    max_price: 4500
    enabled: true
    aliases: ["Lenovo Legion 27U 10"]
    required_tokens: ["lenovo", "legion", "27u", "10"]
    excluded_tokens: []
```

Les `required_tokens` constituent la protection la plus importante contre les variantes incompatibles. Utiliser `excluded_tokens` pour exclure une référence connue.

Les paramètres réseau, matching, alertes et UltraPC sont dans `config/settings.yml`.

## Telegram

1. Créer un bot avec BotFather.
2. Envoyer un message au bot, puis récupérer l'identifiant du chat via l'API Telegram.
3. En local, définir les variables sans les écrire dans Git :

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

Dans GitHub : **Settings > Secrets and variables > Actions > New repository secret**, créer exactement :

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Ne jamais coller ces valeurs dans un fichier versionné ni dans un journal.

## Exécution

```bash
price-monitor-ma --dry-run
price-monitor-ma
```

`--dry-run` effectue la recherche et l'historisation, mais n'envoie pas Telegram. Sans secrets, le programme journalise un avertissement et continue.

## GitHub Actions

- `.github/workflows/ci.yml` valide chaque push et pull request.
- `.github/workflows/price-monitor.yml` s'exécute à la minute 17 toutes les deux heures et via **Actions > Surveillance des prix > Run workflow**.
- L'historique `data/prices.db` est committé par `github-actions[bot]` sur `main` afin de survivre aux runners éphémères.

Si `main` est protégée, autoriser GitHub Actions à pousser, ou remplacer la persistance par un artefact, une branche dédiée, GitHub Cache ou un stockage externe. Pour un dépôt public, la base ne doit contenir aucune donnée personnelle ou secrète.

## Base SQLite

Tables :

- `products` : configuration synchronisée ;
- `price_checks` : chaque offre et date de vérification ;
- `alert_state` : dernier prix notifié par produit et site.

Inspection locale :

```bash
sqlite3 data/prices.db ".tables"
sqlite3 data/prices.db "SELECT site,title,price,available,checked_at FROM price_checks ORDER BY checked_at DESC LIMIT 20;"
```

## Ajouter un scraper

1. Implémenter `BaseScraper` dans `src/price_monitor/scrapers/`.
2. Ajouter ses paramètres dans `config/settings.yml` et `config.py`.
3. L'enregistrer dans `main.py`.
4. Ajouter une fixture HTML et des tests sans requête réseau.
5. Respecter les règles du site, les délais et l'absence de contournement.

## Limites connues

- Le HTML d'UltraPC peut évoluer. Les fixtures valident le parseur connu, pas le site en direct.
- Le matching réduit les faux positifs sans pouvoir les supprimer totalement.
- Une base SQLite commitée grossit au fil du temps. Prévoir une rétention ou une base externe à plus grande échelle.
- Les horaires GitHub Actions sont en UTC et peuvent être retardés par GitHub.

## Validation avant push

```bash
ruff check .
mypy src
pytest --cov=price_monitor --cov-report=term-missing
price-monitor-ma --dry-run
```

## Licence

MIT. Voir `LICENSE`.
