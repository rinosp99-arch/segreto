// Start for Railway: on an empty database the texts are imported first (seconds), the server starts,
// then missing media are fetched in the background. Nothing happens when content already exists.
const path = require('path');
const { spawn, spawnSync } = require('child_process');

const NODE = process.execPath;
const QUIET = '--disable-warning=ExperimentalWarning';
const IMPORT = path.join(__dirname, '..', 'scripts', 'import.js');
const from = (process.env.IMPORT_MEDIEN_VON || '').replace(/\/+$/, '');

// 1. texts (only if the database has no creators yet)
const r = spawnSync(NODE, [QUIET, IMPORT, '--ja', '--nur-wenn-leer', '--nur-db'], { stdio: 'inherit' });
if (r.status !== 0) console.error('Import der Texte fehlgeschlagen - Server startet trotzdem.');

// 1b. one-off content corrections (each one checks the old value, so nothing happens the second time)
try {
  require('./migrate').run();
} catch (e) {
  console.error('Inhalts-Korrekturen nicht ausgeführt:', e.message);
}

// 2. first admin from one-time variables (only if there is no admin yet)
try {
  const auth = require('./auth');
  if (process.env.ADMIN_EMAIL && process.env.ADMIN_PASSWORD && auth.adminCount() === 0) {
    auth.createAdmin(process.env.ADMIN_EMAIL, process.env.ADMIN_PASSWORD);
    console.log(`Admin ${process.env.ADMIN_EMAIL.toLowerCase()} angelegt. Variablen ADMIN_EMAIL und ADMIN_PASSWORD jetzt in Railway löschen.`);
  }
} catch (e) {
  console.error('Admin nicht angelegt:', e.message);
}

// 3. server
require('./index');

// 4. media in the background (skips files that already exist)
if (from) {
  const child = spawn(NODE, [QUIET, IMPORT, '--ja', '--nur-medien', `--medien-von=${from}`], { stdio: 'inherit' });
  child.on('exit', (code) => console.log(`Medien-Abgleich beendet (Code ${code}).`));
}
