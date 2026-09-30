# LATO SEGRETO – neue Seite

Gleiche Seite und gleicher Admin wie bisher, aber ohne Emergent: ein Node-Server liefert Seite, Admin,
Bilder und Videos aus. Alle Inhalte liegen in einer Datenbank-Datei plus Medienordner unter `data/`.

## Lokal starten

```
cd server
npm install
npm run import -- --ja      # Inhalte aus inhalte/ übernehmen (nur beim ersten Mal)
npm run admin               # Admin-Zugang anlegen (Passwort wird verdeckt eingegeben)
npm start                   # http://localhost:8001  ·  Admin: http://localhost:8001/admin
```

Frontend nach Änderungen neu bauen: `cd frontend && npm ci --legacy-peer-deps && npm run build`.

Tests (Server muss laufen): `node scripts/test-admin-api.js`

## Online stellen (Railway)

1. Railway-Konto der Betreiber, Kevin als Mitglied einladen.
2. Code in ein privates GitHub-Repo der Betreiber, in Railway „Deploy from GitHub repo“.
3. Am Dienst ein **Volume** anlegen, Mount-Pfad `/data`.
4. Variable `PUBLIC_BASE_URL` = `https://<domain>` (erst setzen, wenn die Domain verbunden ist).
5. Nach dem ersten Deploy in der Railway-Shell einmalig:
   ```
   npm run import -- --ja --medien-von=https://secret-side.emergent.host
   npm run admin
   ```
   Der Import holt alle Bilder und Videos direkt von der alten Seite.
6. Domain in Railway eintragen, DNS beim Domain-Anbieter setzen, Sitemap `https://<domain>/sitemap.xml`
   in der Google Search Console einreichen.
7. Erst wenn alles geprüft ist: Emergent kündigen.

## Was wo ist

| Pfad | Inhalt |
|---|---|
| `frontend/` | die bisherige React-Seite + Admin (Autopiloten entfernt) |
| `server/` | Server: `public.js` Seite-API, `admin.js` Admin-API, `seo.js` HTML für Google + Sitemap, `db.js` Datenbank |
| `scripts/` | Import, Admin anlegen, Admin-Test |
| `inhalte/` | Texte der alten Seite + Liste der Medien; `inhalte/medien/` = lokale Sicherungskopie (nicht in Git) |
| `data/` | Datenbank + hochgeladene Medien (nicht in Git, auf dem Server = Volume) |

Backup: den Ordner `data/` (bzw. das Railway-Volume) sichern – das ist alles.
