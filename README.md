# price-monitor-ma

Moniteur de prix Python pour six boutiques marocaines actives : **Jumia Maroc, UltraPC, Cosmos, Biougnach, ElectroSalam et MyMarket**.

**Electroplanet** et **Marjane Mall** restent configurés mais sont désactivés, car leurs protections refusent actuellement les requêtes provenant de GitHub Actions avec HTTP 403. **MicroMagma** est également désactivé, car sa route de recherche configurée redirige actuellement vers une page 404. Ils ne doivent être réactivés qu'après validation d'un accès automatisé autorisé et d'une route fonctionnelle.

Des configurations sectorielles sont fournies mais désactivées par défaut pour **Decathlon Maroc, IKEA Maroc, Mafiaway Store, Bringo, DeFacto, Palmarosa, PlanetSport et Avito**. Elles ne sont pas interrogées pour le MacBook suivi. `Moteur.ma` et `Mubawab` ne sont pas ajoutés : leurs verticales automobile et immobilier ne correspondent pas à un moniteur de produits de détail.

## Garanties et limites

- Extraction HTML configurable avec repli JSON-LD.
- Tests unitaires hors réseau pour les fournisseurs configurés.
- Les tests hors réseau valident le parseur, pas la stabilité future du HTML réel.
- Aucun contournement de CAPTCHA, connexion ou protection anti-bot.
- Avant activation, vérifier les CGU et `robots.txt` de chaque site. La fréquence par défaut est limitée à une exécution toutes les deux heures et 10 résultats/site.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Python 3.11 et 3.12 sont couverts par la CI.

## Configuration

- `config/settings.yml` : sites, sélecteurs, HTTP et alertes.
- `config/products.yml` : produits, seuils, alias, termes obligatoires et exclusions.
- Les secrets ne doivent jamais être placés dans ces fichiers.

Secrets GitHub Actions requis pour les notifications :

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Exécution

Test local sans Telegram :

```bash
price-monitor-ma --dry-run --database /tmp/prices.db
```

Exécution avec variables d'environnement déjà définies dans un coffre sécurisé :

```bash
price-monitor-ma
```

## Validation

```bash
ruff check .
mypy src
pytest
python -m build
python -m pip check
```

## Workflows

- `.github/workflows/ci.yml` : Ruff, mypy, pytest, validation de la configuration, build et contrôle des dépendances sous Python 3.11/3.12.
- `.github/workflows/price-monitor.yml` : surveillance toutes les deux heures, cache SQLite privé et sauvegarde en artefact pendant 30 jours. Le workflow ne pousse plus de base binaire sur `main`.

## Diagnostic

Une erreur d'un site est isolée et journalisée. Les réponses HTTP incluent la durée, le statut, le volume et le type de contenu. Un HTTP 403 est signalé comme un refus d'accès automatisé et n'est pas réessayé : le moniteur ne contourne ni CAPTCHA ni protection anti-bot. Les URL externes sont rejetées et les paramètres de suivi (`utm_*`, `fbclid`, `gclid`) supprimés.

Si le HTML d'une boutique change, ajuster uniquement ses sélecteurs dans `config/settings.yml`, ajouter une fixture représentative, puis relancer `pytest`.
