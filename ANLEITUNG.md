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

Tests (Server muss laufen): `node scripts/test-admin-api.js` und
`BASE=http://localhost:8001 ADMIN_EMAIL=... ADMIN_PASSWORD=... node scripts/test-ai-api.js`.
Beide nur gegen einen lokalen Server mit Wegwerf-Daten laufen lassen (`DATA_DIR=<Testordner>` beim Serverstart und beim Admin-Test).

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

## KI-Schnittstelle (Custom GPT)

Ein eigener GPT (GPT Actions) kann die Seite über `/api/v2/ai` lesen und pflegen – gleiche 12 Operationen wie beim alten System.
Alles dazu steht im Admin unter **Impostazioni → Interfaccia AI (Custom GPT)**.

1. **Schlüssel anlegen:** Name eintragen, Rechte wählen (*Solo lettura* oder *Completi*), „Crea chiave“. Der Schlüssel (`ls_…`) wird
   **genau einmal** angezeigt – sofort kopieren. Gespeichert wird nur ein Hash; verloren = neuen Schlüssel anlegen, alten löschen.
2. **Im GPT eintragen:** Configure → Actions → „Import from URL“ mit der im Admin angezeigten Schema-Adresse
   `https://<domain>/api/v2/ai/openapi-chatgpt.json`. Authentication: **API Key**, Auth Type **Bearer**, Schlüssel einfügen.
   Der Schlüssel gehört nur in dieses Feld, nie in die Instructions. Nach einem Domainwechsel das Schema neu importieren.
3. **READ_ONLY oder FULL** (Schalter „Modifiche consentite“): Standard ist READ_ONLY – der GPT kann lesen, prüfen und Vorschauen zeigen,
   ändert aber nichts. Erst mit FULL werden Änderungen gespeichert, und nur mit einem Schlüssel „Completi“.
   Heikle Aktionen (vom Netz nehmen, löschen, Basis-URL ändern) brauchen zusätzlich eine ausdrückliche Bestätigung im Chat.
4. **Not-Aus** (Schalter „Interfaccia attiva“): aus = alle Schlüssel sind sofort gesperrt. Website und Admin laufen normal weiter.
   Einzelne Schlüssel lassen sich in der Liste deaktivieren oder löschen.

Jede Aktion des GPT steht unter „Ultime 20 azioni“ und im Registro attività. Änderungen lassen sich über den GPT zurücknehmen
(„annulla“ → Rollback der Sitzung). Veröffentlichen geht nur, wenn die Pflichtangaben vollständig sind; die Bestätigung der
Volljährigkeit kann nur ein Mensch im Admin setzen. Hochgeladene Dateien bleiben bei einem Rollback im Medienordner liegen.

Die Basis-URL der Seite kommt aus `PUBLIC_BASE_URL`; sie kann über den GPT geändert werden (`config.site.update`), aber nur auf eine
https-Domain, die schon auf diese App zeigt. Der gespeicherte Wert hat dann Vorrang vor der Variable.

## Bilder, Titel und Google (seit 10/2026)

- **Verkleinerte Bilder:** `/api/uploads/<datei>?w=640` liefert eine WebP-Kopie in dieser Breite (erlaubt: 320, 480, 640, 960, 1280, 1600;
  mit `&f=jpg` als JPEG für Vorschaubilder in sozialen Netzen). Die Kopien entstehen einmal und liegen unter `data/cache/img`
  (auf dem Server im Volume). Nach dem Start bereitet der Server sie im Hintergrund vor („Verkleinerte Bilder bereit“ im Log).
  Der Ordner `cache/` darf jederzeit gelöscht werden, er baut sich neu auf. Die Originale bleiben unverändert.
- **Kopf der Seite kommt vom Server** (`server/seo.js`): Titel, Beschreibung, Canonical, strukturierte Daten. Auf der Seite, auf der
  ein Besucher ankommt, lässt die React-App diesen Kopf stehen (`frontend/src/lib/seo.js`). Der Text der Startseite steht zweimal:
  `HOME_ABOUT` in `server/seo.js` und in `frontend/src/pages/Home.js` – immer beide ändern.
- **Einmalige Inhalts-Korrekturen** (`server/migrate.js`) laufen bei jedem Start, ändern aber nur, was noch den alten Wert hat.
- **Icons** (`favicon.ico`, `icon-192.png`, `icon-512.png`, `apple-touch-icon.png`) liegen in `frontend/public`; neu erzeugen mit
  `node scripts/icons.js`.

## Was wo ist

| Pfad | Inhalt |
|---|---|
| `frontend/` | die bisherige React-Seite + Admin (Autopiloten entfernt) |
| `server/` | Server: `public.js` Seite-API, `admin.js` Admin-API, `rules.js` gemeinsame Schreibregeln, `seo.js` HTML für Google + Sitemap, `images.js` verkleinerte Bilder, `migrate.js` einmalige Inhalts-Korrekturen, `site.js` Basis-URL, `db.js` Datenbank, `ai*.js` KI-Schnittstelle |
| `scripts/` | Import, Admin anlegen, Admin-Test, KI-Test, `icons.js` (Icons neu erzeugen) |
| `inhalte/` | Texte der alten Seite + Liste der Medien; `inhalte/medien/` = lokale Sicherungskopie (nicht in Git) |
| `data/` | Datenbank + hochgeladene Medien (nicht in Git, auf dem Server = Volume) |

Backup: den Ordner `data/` (bzw. das Railway-Volume) sichern – das ist alles.
