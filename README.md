# Lecture rapide — RSVP + ORP

Prototype web : lecture mot à mot avec lettre ORP rouge centrée, import **EPUB** / **TXT**, et recherche de livres libres (**Project Gutenberg** via Gutendex + **Gallica** BnF).

## Lancer (recommandé)

Le serveur local sert les fichiers **et** un proxy CORS pour Gutendex, Gutenberg et Gallica :

```bash
cd /workspace/lecture-rapide
python3 server.py
# → http://127.0.0.1:8765/
```

Port optionnel : `python3 server.py 9000`.

Sans proxy (`python3 -m http.server` ou `file://`) : l’import local fonctionne ; la recherche Gutendex peut marcher (CORS ouvert), mais le **téléchargement** des EPUB Gutenberg/Gallica est bloqué par le navigateur — utilisez `server.py`.

## Utiliser un livre

### Fichier local
1. Panneau **Livres** → **Choisir un fichier…** (`.epub` / `.txt`)
2. Le titre s’affiche en en-tête → **Lire**

### Catalogue libre
1. Saisir un auteur ou un titre (ex. `Hugo`, `Dumas`)
2. Filtrer : Gutenberg / Gallica / les deux
3. **Chercher** → **Lire** sur un résultat (charge l’EPUB dans le lecteur RSVP)

Fixture de test : `fixtures/1984.epub` (Orwell, trad. Romain Vigier / Renard Rebelle, sans DRM).

## Proxy

- Santé : `GET /api/health` → `{"ok":true,"proxy":true}`
- Proxy : `GET /api/proxy?url=<url-encodée>` (hôtes autorisés : gutendex.com, gutenberg.org, gallica.bnf.fr)

## Vérif parse Node (optionnel)

```bash
npm install jszip
node fixtures/parse-epub.mjs fixtures/1984.epub
```
