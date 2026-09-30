// Create an admin login or reset a password. The password is typed in hidden and never printed.
//   cd server && npm run admin
// Non-interactive (e.g. first start on the server): ADMIN_EMAIL=... ADMIN_PASSWORD=... npm run admin
const readline = require('readline');
const auth = require('../server/auth');
const store = require('../server/db');

function ask(question, hidden = false) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: true });
    if (hidden) {
      rl._writeToOutput = (s) => { if (s.includes(question)) rl.output.write(s); };
    }
    rl.question(question, (answer) => {
      rl.close();
      if (hidden) process.stdout.write('\n');
      resolve(answer.trim());
    });
  });
}

(async () => {
  const email = (process.env.ADMIN_EMAIL || await ask('E-Mail des Admins: ')).toLowerCase();
  const password = process.env.ADMIN_PASSWORD || await ask('Passwort (mind. 10 Zeichen, wird nicht angezeigt): ', true);
  if (!email.includes('@')) throw new Error('Ungültige E-Mail');
  if (password.length < 10) throw new Error('Passwort zu kurz (mind. 10 Zeichen)');
  const existing = store.db.prepare('SELECT id FROM admins WHERE email = ?').get(email);
  if (existing) {
    auth.setPassword(existing.id, password);
    console.log(`Passwort für ${email} geändert.`);
  } else {
    auth.createAdmin(email, password);
    console.log(`Admin ${email} angelegt. Login: /admin`);
  }
})().catch((e) => { console.error(e.message); process.exit(1); });
