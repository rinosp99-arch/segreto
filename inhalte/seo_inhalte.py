"""SEO content for the new site: guide articles, expanded thin articles, category texts.

    python seo_inhalte.py      -> writes seo-inhalte.json (read by scripts/import.js)

Articles with the slug of an existing article replace it (same id, URL stays the same).
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
models = {m['pubblico']['slug']: m['pubblico'] for m in json.load(open(HERE / 'daten' / 'modelle.json', encoding='utf8'))}
old_articles = {a['slug']: a for a in json.load(open(HERE / 'daten' / 'artikel.json', encoding='utf8'))}


def name(slug):
    return models[slug]['nome_artistico'].strip().title()


def link(slug):
    return f'<a href="/modelle/{slug}">{name(slug)}</a>'


def cover(slug):
    m = models[slug]
    return m.get('foto_copertina') or m.get('foto_card') or ''


DISCLAIMER = ('<p><em>LATO SEGRETO è un sito indipendente: non è affiliato a OnlyFans. Tutte le creator presenti sono '
              'maggiorenni e i link portano ai loro profili ufficiali. Contenuti riservati a un pubblico adulto (18+).</em></p>')


FAQ = {
    'onlyfans-italiane-guida': [
        ('Come trovo creator italiane su OnlyFans?', 'OnlyFans non ha una ricerca per nazionalità. Il modo più rapido è usare una directory come LATO SEGRETO, dove le creator italiane sono raccolte per stile e categoria, con il link al profilo ufficiale.'),
        ('Le creator di LATO SEGRETO sono italiane?', 'Sì, la selezione è dedicata a creator italiane. Tutte sono maggiorenni e i link portano ai loro profili ufficiali.'),
        ('Esistono creator italiane con profilo gratuito?', 'Sì, diverse creator hanno un profilo gratuito o offrono prove gratuite. Su LATO SEGRETO puoi intanto guardare gratis il lato pubblico e il lato segreto di ogni profilo.'),
        ('Come capisco se un profilo è falso?', 'Il link ufficiale ha sempre la forma onlyfans.com/nomeutente. Diffida di chi chiede pagamenti fuori dalla piattaforma o manda link a siti intermedi.'),
    ],
    'come-funziona-onlyfans': [
        ('OnlyFans è gratis?', 'Registrarsi è gratis. Si paga solo l’abbonamento ai profili a pagamento e gli eventuali contenuti extra che scegli di sbloccare.'),
        ('Serve il nome reale per iscriversi a OnlyFans?', 'No: come utente scegli un nome utente, ed è quello che vedono le creator. Servono un’email e un metodo di pagamento quando acquisti qualcosa.'),
        ('Come si annulla un abbonamento OnlyFans?', 'Dal profilo della creator disattivi il rinnovo automatico. L’accesso resta attivo fino alla fine del periodo già pagato.'),
        ('Cosa sono i messaggi a pagamento?', 'Sono contenuti inviati in chat che si sbloccano con un pagamento singolo. Il prezzo è visibile prima di confermare e non c’è alcun obbligo.'),
    ],
    'onlyfans-gratis': [
        ('Si può vedere OnlyFans gratis?', 'Sì, in modo legale: seguendo i profili gratuiti, usando le prove gratuite ufficiali e guardando le anteprime pubblicate con il consenso delle creator.'),
        ('I siti di leak OnlyFans sono legali?', 'No. Pubblicano contenuti senza il consenso delle creator e spesso nascondono malware, phishing o abbonamenti ingannevoli.'),
        ('Dove trovo prove gratuite di OnlyFans?', 'Le creator le condividono di solito sui loro social ufficiali. Ricordati di disattivare il rinnovo automatico se vuoi solo provare.'),
    ],
    'quanto-costa-onlyfans': [
        ('Quanto costa un abbonamento OnlyFans al mese?', 'Dipende dalla creator: attualmente gli abbonamenti vanno da circa 5 a 50 dollari al mese, e molti profili sono gratuiti.'),
        ('OnlyFans si paga in euro o in dollari?', 'I prezzi sono in dollari. La banca converte l’importo in euro; alcune banche applicano una piccola commissione.'),
        ('Ci sono costi nascosti su OnlyFans?', 'No, ma l’abbonamento si rinnova in automatico. Disattiva il rinnovo se non vuoi pagare il mese successivo.'),
        ('Conviene il pacchetto di più mesi?', 'Sì, se segui una creator con costanza: i pacchetti di tre, sei o dodici mesi hanno spesso uno sconto.'),
    ],
    'onlyfans-e-sicuro': [
        ('La creator vede il mio nome reale?', 'No. Vede il tuo nome utente e i messaggi che scrivi, non i dati della tua carta.'),
        ('Come compare OnlyFans sull’estratto conto?', 'Come un normale acquisto online. Se vuoi più discrezione puoi usare una carta virtuale o prepagata.'),
        ('Si può usare OnlyFans in modo anonimo?', 'Sì: usa un nome utente neutro, un’email dedicata e attiva l’autenticazione a due fattori.'),
        ('Come evito le truffe su OnlyFans?', 'Paga solo all’interno della piattaforma, usa link ufficiali onlyfans.com/nomeutente e ignora chi chiede bonifici o carte regalo.'),
    ],
}


def faq_html(slug):
    items = FAQ.get(slug, [])
    if not items:
        return ''
    return '<h2>Domande frequenti</h2>' + ''.join(f'<h3>{q}</h3><p>{a}</p>' for q, a in items)


ARTICLES = []


def article(slug, titolo, keyword, secondarie, seo_title, meta, estratto, contenuto, correlate, img_from, data='2026-10-02T09:00:00+00:00'):
    old = old_articles.get(slug, {})
    ARTICLES.append({
        'id': old.get('id'), 'slug': slug, 'titolo': titolo, 'estratto': estratto,
        'contenuto': contenuto.strip() + faq_html(slug) + DISCLAIMER,
        'faq': [{'q': q, 'a': a} for q, a in FAQ.get(slug, [])],
        'immagine_principale': cover(img_from), 'alt_text': f'{name(img_from)} – LATO SEGRETO',
        'og_image': cover(img_from), 'autore': 'Redazione LATO SEGRETO',
        'data_pubblicazione': old.get('data_pubblicazione') or data, 'stato': 'pubblicato',
        'keyword_principale': keyword, 'keyword_secondarie': secondarie,
        'seo_title': seo_title, 'meta_description': meta, 'indicizzabile': True,
        'modelle_correlate': correlate, 'categorie': [], 'tag': [],
    })


# ---------------------------------------------------------------- 1. pillar page
article(
    'onlyfans-italiane-guida',
    'OnlyFans italiane: come scoprire le creator più interessanti',
    'onlyfans italiane', ['creator italiane', 'ragazze italiane onlyfans', 'migliori onlyfans italiane'],
    'OnlyFans italiane: guida alle creator da scoprire (2026) | LATO SEGRETO',
    'Come trovare le migliori creator italiane su OnlyFans: categorie, profili gratuiti e a pagamento, come riconoscere i profili ufficiali.',
    'Cercare creator italiane su OnlyFans può richiedere ore. Ecco come orientarsi tra stili, categorie e profili ufficiali senza perdere tempo.',
    f'''
<p>Chi cerca <strong>OnlyFans italiane</strong> si scontra quasi sempre con lo stesso problema: la piattaforma non ha una vera
funzione di ricerca per nazionalità o stile. Trovare creator italiane interessanti significa passare da un social all’altro,
seguire link sparsi e sperare che il profilo sia quello giusto. Questa guida ti mostra come orientarti in modo semplice.</p>

<h2>Perché è difficile trovare creator italiane su OnlyFans</h2>
<p>OnlyFans è pensato per chi conosce già il nome della creator. Non esiste un catalogo da sfogliare, né filtri per città,
lingua o categoria. Per questo la maggior parte delle persone scopre i profili attraverso Instagram, X, TikTok o Telegram –
e spesso finisce su account copiati o link non ufficiali.</p>
<p>Le directory come LATO SEGRETO nascono proprio per questo: raccolgono creator selezionate in un unico posto, con una
presentazione curata e il link diretto al profilo ufficiale.</p>

<h2>Come scegliere: parti dallo stile, non dalla foto</h2>
<p>Una foto attira l’attenzione, ma è lo stile che ti fa restare. Prima di abbonarti chiediti che tipo di contenuto e di
personalità cerchi. Su LATO SEGRETO puoi partire dalle categorie:</p>
<ul>
<li><a href="/categorie/more">Creator more</a> – sguardi intensi e fascino mediterraneo</li>
<li><a href="/categorie/bionde">Creator bionde</a> – luce, dolcezza e presenza</li>
<li><a href="/categorie/tatuate">Creator tatuate</a> – stile alternativo e carattere</li>
<li><a href="/categorie/eleganti">Creator eleganti</a> – fashion, classe e atmosfera</li>
<li><a href="/categorie/sportive">Creator sportive</a> – energia, fitness e disciplina</li>
<li><a href="/categorie/cosplay">Creator cosplay</a> – personaggi, fantasia e creatività</li>
</ul>
<p>Ogni profilo ha un <strong>lato pubblico</strong>, che mostra chi è la creator, e un <strong>lato segreto</strong>, che ti dà
un’anteprima del suo mondo prima di decidere se continuare su OnlyFans.</p>

<h2>Profili gratuiti e profili a pagamento</h2>
<p>Su OnlyFans esistono due tipi di profilo. Quelli <strong>gratuiti</strong> si seguono senza abbonamento: vedi i post
pubblici e paghi solo i contenuti extra che scegli. Quelli <strong>a pagamento</strong> richiedono un abbonamento mensile,
con un prezzo deciso dalla creator. Molte offrono prove gratuite o sconti sui pacchetti di più mesi. Se vuoi capire nel
dettaglio le cifre, leggi la nostra guida su <a href="/articoli/quanto-costa-onlyfans">quanto costa OnlyFans</a>.</p>

<h2>Come riconoscere un profilo ufficiale</h2>
<p>Gli account falsi sono il rischio più comune. Alcuni consigli pratici:</p>
<ul>
<li>il link deve portare a <strong>onlyfans.com/nomeutente</strong>, non a siti intermedi sconosciuti;</li>
<li>diffida di chi chiede pagamenti fuori dalla piattaforma, via bonifico o carte regalo;</li>
<li>i siti che promettono contenuti “gratis” copiati dai profili sono illegali e spesso pieni di truffe
(ne parliamo in <a href="/articoli/onlyfans-gratis">OnlyFans gratis: cosa puoi vedere senza pagare</a>);</li>
<li>controlla che il nome e lo stile coincidano con i social ufficiali della creator.</li>
</ul>
<p>Su LATO SEGRETO ogni pulsante “Continua con me” porta direttamente al profilo ufficiale della creator.</p>

<h2>Da dove iniziare</h2>
<p>Se è la prima volta, scegli due o tre profili che ti incuriosiscono davvero e guarda il loro lato segreto. Tra le creator
più seguite del momento trovi {link('vanessa-bella')}, {link('flavia-russo-4')}, {link('valeria-trapani')} e {link('martina')}.
Se non hai mai usato la piattaforma, la nostra guida <a href="/articoli/come-funziona-onlyfans">come funziona OnlyFans</a>
ti spiega tutto in cinque minuti.</p>
''',
    ['vanessa-bella', 'flavia-russo-4', 'valeria-trapani', 'martina'], 'vanessa-bella',
)

# ---------------------------------------------------------------- 2. how it works
article(
    'come-funziona-onlyfans',
    'Come funziona OnlyFans: guida semplice per chi inizia',
    'come funziona onlyfans', ['onlyfans come iscriversi', 'abbonamento onlyfans', 'onlyfans cos’è'],
    'Come funziona OnlyFans: iscrizione, abbonamenti e messaggi | LATO SEGRETO',
    'Come funziona OnlyFans spiegato semplice: registrazione, abbonamenti, contenuti extra, mance, rinnovo automatico e privacy.',
    'Iscrizione, abbonamenti, messaggi e rinnovi: tutto quello che serve sapere su OnlyFans prima di seguire la tua prima creator.',
    f'''
<p>OnlyFans è una piattaforma in abbonamento dove le creator pubblicano contenuti esclusivi per chi le segue. Se non l’hai
mai usata, il funzionamento può sembrare confuso. In realtà è semplice: ti iscrivi, scegli una creator e decidi tu quanto
e come spendere.</p>

<h2>1. La registrazione</h2>
<p>Per creare un account servono un indirizzo email e una password. La piattaforma è riservata ai <strong>maggiorenni</strong>.
Il nome utente che scegli è quello che vedono le creator: non serve usare il tuo nome reale. Molti preferiscono un indirizzo
email dedicato, per tenere separate le notifiche.</p>

<h2>2. Seguire una creator</h2>
<p>Una volta registrato, apri il profilo di una creator. Se il profilo è <strong>gratuito</strong> puoi seguirlo subito.
Se è <strong>a pagamento</strong>, l’abbonamento mensile sblocca i post del profilo. Il prezzo lo decide la creator e spesso
ci sono promozioni: prove gratuite, sconti sul primo mese o pacchetti di tre, sei o dodici mesi.</p>

<h2>3. Contenuti extra e messaggi</h2>
<p>Oltre ai post del profilo, molte creator inviano contenuti extra in chat, che si sbloccano con un pagamento singolo
(si chiamano spesso <em>PPV</em>, pay-per-view). Puoi anche lasciare una <strong>mancia</strong> per apprezzare un contenuto.
Nessuno di questi pagamenti è obbligatorio: vedi il prezzo prima di confermare.</p>

<h2>4. Rinnovo automatico</h2>
<p>Gli abbonamenti si rinnovano in automatico ogni mese. Se vuoi provare un profilo solo per un periodo, puoi disattivare il
rinnovo subito dopo l’iscrizione: l’accesso resta attivo fino alla fine del periodo già pagato. È il modo più semplice per
tenere sotto controllo la spesa.</p>

<h2>5. Pagamenti</h2>
<p>Si paga con carta di credito o di debito. I prezzi sono in dollari e la banca li converte in euro. Per tutti i dettagli
su cifre e costi leggi <a href="/articoli/quanto-costa-onlyfans">quanto costa OnlyFans</a>.</p>

<h2>6. Privacy</h2>
<p>La creator vede il tuo nome utente, non i dati della tua carta. Se vuoi più discrezione puoi usare un nome utente
anonimo e una carta virtuale o prepagata. Ne parliamo in dettaglio in
<a href="/articoli/onlyfans-e-sicuro">OnlyFans è sicuro?</a>.</p>

<h2>Il modo più rapido per iniziare</h2>
<p>Invece di cercare a caso sui social, guarda prima chi ti interessa davvero. Su LATO SEGRETO ogni creator ha un lato
pubblico e un lato segreto: puoi farti un’idea del suo stile prima di passare al profilo ufficiale. Inizia dalle
<a href="/categorie/eleganti">creator eleganti</a>, dalle <a href="/categorie/tatuate">tatuate</a> o da profili come
{link('chiara-lamora')} e {link('anna-bionda')}.</p>
''',
    ['chiara-lamora', 'anna-bionda', 'serena-torre', 'francesca-minetti'], 'anna-bionda',
)

# ---------------------------------------------------------------- 3. free
article(
    'onlyfans-gratis',
    'OnlyFans gratis: cosa puoi vedere senza pagare (e cosa evitare)',
    'onlyfans gratis', ['onlyfans gratis italiane', 'profili onlyfans gratuiti', 'onlyfans free'],
    'OnlyFans gratis: profili gratuiti, prove e cosa evitare | LATO SEGRETO',
    'Si può usare OnlyFans gratis? Profili gratuiti, prove, anteprime ufficiali e perché i siti di “leak” sono illegali e pericolosi.',
    'Profili gratuiti, prove e anteprime: ecco cosa si può davvero vedere gratis su OnlyFans, e perché conviene stare lontani dai siti di leak.',
    f'''
<p>“OnlyFans gratis” è una delle ricerche più frequenti. La risposta breve: sì, una parte di OnlyFans si può usare senza
pagare, in modo del tutto legale. Ma la rete è piena di siti che promettono di più – e quelli conviene evitarli.</p>

<h2>Profili gratuiti: esistono davvero</h2>
<p>Molte creator hanno un <strong>profilo gratuito</strong>. Lo segui senza abbonamento e vedi i post pubblici; paghi solo i
contenuti extra che scegli, se li vuoi. È il modo migliore per conoscere una creator senza impegno.</p>

<h2>Prove gratuite e promozioni</h2>
<p>Anche i profili a pagamento offrono spesso <strong>link di prova</strong> gratuiti per alcuni giorni, o sconti sul primo
mese. Le creator li pubblicano di solito sui loro social ufficiali. Ricordati di disattivare il rinnovo automatico se vuoi
solo provare.</p>

<h2>Anteprime ufficiali</h2>
<p>Un altro modo per farsi un’idea senza spendere sono le anteprime pubblicate con il consenso delle creator. Su LATO SEGRETO
ogni profilo mostra un <strong>lato pubblico</strong> e un <strong>lato segreto</strong>: foto e video scelti dalle creator
stesse, visibili gratis, prima di decidere se continuare sul profilo ufficiale. Prova con {link('morena')} o
{link('daiana-rossi')}.</p>

<h2>Perché evitare i siti di “leak”</h2>
<p>I siti che promettono contenuti OnlyFans gratis copiati dai profili a pagamento hanno tre problemi:</p>
<ul>
<li><strong>Sono illegali.</strong> Pubblicano contenuti senza il consenso delle creator, violando i loro diritti.</li>
<li><strong>Sono pericolosi.</strong> Pubblicità ingannevoli, download falsi, malware e pagine che rubano dati e password.</li>
<li><strong>Spesso non mantengono le promesse.</strong> Dietro molti pulsanti “guarda gratis” c’è solo un abbonamento
nascosto o un tentativo di phishing.</li>
</ul>
<p>In più, chi crea contenuti vive del proprio lavoro: sostenerla direttamente è anche una questione di rispetto.</p>

<h2>Il modo intelligente di risparmiare</h2>
<ul>
<li>segui prima i profili gratuiti;</li>
<li>usa le prove gratuite ufficiali e disattiva il rinnovo;</li>
<li>scegli i pacchetti di più mesi solo per le creator che ti piacciono davvero;</li>
<li>guarda le anteprime su LATO SEGRETO prima di abbonarti.</li>
</ul>
<p>Vuoi sapere quanto si spende davvero? Leggi <a href="/articoli/quanto-costa-onlyfans">quanto costa OnlyFans</a>.</p>
''',
    ['morena', 'daiana-rossi', 'ambra-celeste', 'zaira'], 'morena',
)

# ---------------------------------------------------------------- 4. cost
article(
    'quanto-costa-onlyfans',
    'Quanto costa OnlyFans? Abbonamenti, messaggi e mance spiegati',
    'quanto costa onlyfans', ['prezzo abbonamento onlyfans', 'onlyfans costo mensile', 'onlyfans prezzi'],
    'Quanto costa OnlyFans? Prezzi di abbonamenti e contenuti | LATO SEGRETO',
    'Quanto costa OnlyFans: iscrizione gratuita, abbonamenti mensili decisi dalle creator, contenuti extra, mance e come controllare la spesa.',
    'L’iscrizione è gratuita, il resto lo decidi tu. Ecco come funzionano i prezzi su OnlyFans e come tenere sotto controllo la spesa.',
    f'''
<p>Su OnlyFans non esiste un prezzo unico: ogni creator decide il proprio. Capire le voci di spesa però è semplice, e ti
aiuta a scegliere senza sorprese.</p>

<h2>L’iscrizione è gratuita</h2>
<p>Creare un account non costa nulla. Paghi solo quando decidi di abbonarti a un profilo o di sbloccare un contenuto.</p>

<h2>L’abbonamento mensile</h2>
<p>I profili a pagamento hanno un abbonamento mensile. Il prezzo lo fissa la creator: attualmente la piattaforma consente
abbonamenti da circa <strong>5 a 50 dollari al mese</strong>, e la maggior parte dei profili si colloca nella fascia bassa e
media. I profili gratuiti, invece, non hanno abbonamento.</p>
<p>Molte creator offrono <strong>pacchetti</strong> di tre, sei o dodici mesi con uno sconto, oltre a promozioni sul primo mese.</p>

<h2>Contenuti extra (PPV)</h2>
<p>Alcuni contenuti vengono inviati in chat e si sbloccano con un pagamento singolo. Il prezzo è sempre visibile prima di
confermare, e sei tu a decidere se acquistarli.</p>

<h2>Mance</h2>
<p>Puoi lasciare una mancia a una creator per ringraziarla di un contenuto o di una conversazione. Anche questa è sempre
facoltativa.</p>

<h2>Dollari ed euro</h2>
<p>I prezzi sono in dollari statunitensi. La tua banca converte l’importo in euro al cambio del giorno; alcune banche
applicano una piccola commissione sulle operazioni in valuta estera.</p>

<h2>Come tenere sotto controllo la spesa</h2>
<ul>
<li>parti dai profili gratuiti;</li>
<li>disattiva il rinnovo automatico subito dopo esserti abbonato, se vuoi solo provare;</li>
<li>scegli i pacchetti di più mesi solo per le creator che segui davvero;</li>
<li>usa una carta prepagata o virtuale con un limite di spesa;</li>
<li>guarda prima le anteprime gratuite: su LATO SEGRETO trovi il lato pubblico e il lato segreto di creator come
{link('alessia-golosa')}, {link('greta-sala')} e {link('veronica')}.</li>
</ul>
<p>Per capire come funziona la piattaforma passo dopo passo, leggi <a href="/articoli/come-funziona-onlyfans">come funziona OnlyFans</a>.</p>
''',
    ['alessia-golosa', 'greta-sala', 'veronica', 'susi-milano'], 'greta-sala',
)

# ---------------------------------------------------------------- 5. safety
article(
    'onlyfans-e-sicuro',
    'OnlyFans è sicuro? Privacy, pagamenti e discrezione',
    'onlyfans è sicuro', ['onlyfans privacy', 'onlyfans anonimo', 'onlyfans truffe'],
    'OnlyFans è sicuro? Privacy, pagamenti e come evitare truffe | LATO SEGRETO',
    'OnlyFans è sicuro? Cosa vede la creator, come pagare in modo discreto, come restare anonimi e come riconoscere le truffe più comuni.',
    'Cosa vede la creator di te, come pagare con discrezione e come riconoscere account falsi: la guida alla sicurezza su OnlyFans.',
    f'''
<p>Prima di abbonarsi, molte persone si chiedono se OnlyFans sia sicuro e quanto resti privato. In breve: la piattaforma
in sé è affidabile, ma la sicurezza dipende anche da alcune scelte che fai tu.</p>

<h2>Cosa vede la creator di te</h2>
<p>La creator vede il tuo <strong>nome utente</strong> e i messaggi che le scrivi. Non vede i dati della tua carta. Se non
vuoi farti riconoscere, scegli un nome utente che non contenga il tuo nome reale.</p>

<h2>Restare anonimi</h2>
<ul>
<li>usa un nome utente neutro e un’immagine del profilo non personale;</li>
<li>registrati con un indirizzo email dedicato;</li>
<li>attiva l’autenticazione a due fattori nelle impostazioni dell’account.</li>
</ul>

<h2>Pagamenti discreti</h2>
<p>Si paga con carta di credito o di debito. La voce del pagamento compare sull’estratto conto come qualsiasi acquisto
online. Se preferisci più discrezione o vuoi un limite di spesa, una <strong>carta virtuale o prepagata</strong> è la
soluzione più semplice.</p>

<h2>Le truffe più comuni</h2>
<ul>
<li><strong>Account falsi</strong> che copiano foto di creator reali e chiedono soldi in chat;</li>
<li><strong>richieste di pagamento fuori piattaforma</strong> – bonifici, carte regalo, criptovalute: una creator seria non le chiede;</li>
<li><strong>siti di “leak”</strong> che promettono contenuti gratis ma nascondono malware o phishing
(vedi <a href="/articoli/onlyfans-gratis">OnlyFans gratis: cosa evitare</a>);</li>
<li><strong>link accorciati o siti intermedi</strong> che imitano la pagina di accesso di OnlyFans per rubare la password.</li>
</ul>

<h2>Come riconoscere il profilo giusto</h2>
<p>Il link ufficiale ha sempre la forma <strong>onlyfans.com/nomeutente</strong>. Prima di inserire la password controlla
l’indirizzo nel browser. Su LATO SEGRETO ogni creator ha il link diretto al proprio profilo ufficiale: puoi guardare il suo
lato pubblico e il suo lato segreto e poi continuare con un clic, senza passaggi intermedi. Scopri ad esempio
{link('aurora-bianchini')}, {link('lara-destro')} o {link('chiara-marino')}.</p>

<h2>In sintesi</h2>
<p>OnlyFans è sicuro se usi link ufficiali, paghi solo all’interno della piattaforma e proteggi il tuo account. Il resto
– quanto spendere e chi seguire – lo decidi tu. Per i dettagli sui costi leggi
<a href="/articoli/quanto-costa-onlyfans">quanto costa OnlyFans</a>.</p>
''',
    ['aurora-bianchini', 'lara-destro', 'chiara-marino', 'aurora-caruso'], 'lara-destro',
)

# ---------------------------------------------------------------- 6-8. expand thin existing articles
article(
    'fitness-e-sensualita-creator-sportive',
    'Fitness e sensualità: le creator sportive italiane',
    'creator sportive', ['modelle sportive', 'onlyfans fitness italiane', 'ragazze sportive onlyfans'],
    'Creator sportive italiane: fitness, energia e stile | LATO SEGRETO',
    'Le creator sportive italiane di LATO SEGRETO: allenamento, disciplina e sensualità. Scopri i profili e il loro lato segreto.',
    'Allenamento, disciplina e sicurezza di sé: perché le creator sportive sono tra le più seguite, e quali profili scoprire.',
    f'''
<p>Le creator sportive uniscono due cose che online funzionano sempre: l’energia di chi si allena con costanza e una
sicurezza di sé che si vede in ogni scatto. Non si tratta solo di fisico, ma di uno stile di vita.</p>

<h2>Perché le creator sportive piacciono così tanto</h2>
<p>Chi segue una creator sportiva cerca spesso autenticità: allenamenti veri, routine, motivazione, e quel momento in cui
la disciplina lascia spazio a un lato più personale. È proprio questo contrasto – forza in pubblico, sensualità nel lato
segreto – a rendere questi profili così riconoscibili.</p>

<h2>Cosa aspettarsi dai loro profili</h2>
<ul>
<li>contenuti legati ad allenamento, palestra e outdoor;</li>
<li>uno stile naturale, spesso con abbigliamento sportivo;</li>
<li>un rapporto diretto con chi le segue, fatto di consigli e motivazione;</li>
<li>un lato segreto più intimo, che si scopre solo andando oltre.</li>
</ul>

<h2>Le creator sportive da scoprire</h2>
<p>Su LATO SEGRETO trovi profili molto diversi tra loro: {link('daiana-rossi')} e {link('greta-sala')} uniscono sport ed
eleganza, {link('chiara-marino')} e {link('veronica')} hanno uno stile luminoso, mentre {link('ambra-giallo-2')},
{link('ambra-celeste')} e {link('susi-milano')} portano energia e tatuaggi. Li trovi tutti nella categoria
<a href="/categorie/sportive">creator sportive</a>.</p>

<h2>Prima di abbonarti</h2>
<p>Guarda il lato pubblico e il lato segreto di ogni profilo per capire quale stile ti convince di più. Se è la prima volta
su OnlyFans, leggi <a href="/articoli/come-funziona-onlyfans">come funziona OnlyFans</a> e
<a href="/articoli/quanto-costa-onlyfans">quanto costa</a>.</p>
''',
    ['daiana-rossi', 'greta-sala', 'chiara-marino', 'veronica'], 'daiana-rossi',
)

article(
    'guida-profili-tatuati-stile-carattere',
    'Creator tatuate italiane: stile, carattere e lato segreto',
    'creator tatuate', ['modelle tatuate', 'ragazze tatuate onlyfans', 'onlyfans tatuate italiane'],
    'Creator tatuate italiane: stile alternativo e carattere | LATO SEGRETO',
    'Le creator tatuate italiane di LATO SEGRETO: tatuaggi, stile alternativo e personalità forte. Scopri i profili e il loro lato segreto.',
    'Ogni tatuaggio racconta qualcosa. Ecco perché le creator tatuate hanno un fascino tutto loro, e quali profili scoprire.',
    f'''
<p>I tatuaggi non sono solo un dettaglio estetico: raccontano gusti, esperienze e carattere. Per questo le creator tatuate
hanno un pubblico molto fedele, che cerca uno stile deciso e una personalità che non passa inosservata.</p>

<h2>Il fascino dello stile alternativo</h2>
<p>Le creator tatuate si distinguono per un’estetica riconoscibile: linee, simboli, colori o black work che diventano parte
dell’identità. Spesso il loro stile mescola elementi alternativi, eleganza e un pizzico di provocazione. Il risultato è un
profilo che si ricorda, anche dopo uno sguardo veloce.</p>

<h2>Personalità prima di tutto</h2>
<p>Dietro ogni tatuaggio c’è una scelta. Chi segue queste creator apprezza proprio questo: la sicurezza di chi ha deciso
di mostrarsi così com’è. Nel lato segreto questa personalità diventa ancora più diretta.</p>

<h2>Le creator tatuate da scoprire</h2>
<p>Tra i profili più seguiti trovi {link('vanessa-bella')}, tatuatrice dal carattere magnetico, {link('chiara-lamora')} e
{link('zaira')} con il loro fascino scuro, {link('alessia-golosa')} e {link('morena')} che uniscono tatuaggi ed eleganza,
e {link('aurora-caruso')}, che porta i tatuaggi anche nel mondo cosplay. Tutti i profili sono nella categoria
<a href="/categorie/tatuate">creator tatuate</a>.</p>

<h2>Come scegliere</h2>
<p>Guarda il lato pubblico per capire lo stile e il lato segreto per capire l’atmosfera. Poi decidi con calma: se non
conosci ancora la piattaforma, leggi <a href="/articoli/come-funziona-onlyfans">come funziona OnlyFans</a> e
<a href="/articoli/onlyfans-e-sicuro">OnlyFans è sicuro?</a>.</p>
''',
    ['vanessa-bella', 'chiara-lamora', 'zaira', 'alessia-golosa'], 'chiara-lamora',
)

article(
    'come-nasce-esperienza-lato-segreto',
    'Come nasce l’esperienza LATO SEGRETO',
    'lato segreto', ['creator italiane', 'esperienza premium creator', 'directory creator italiane'],
    'Come nasce LATO SEGRETO: il lato che non hai ancora visto',
    'LATO SEGRETO è la directory delle creator italiane con un lato pubblico e un lato segreto. Ecco come funziona e perché è diversa.',
    'Un lato pubblico, un lato segreto e un solo clic per continuare: ecco l’idea dietro LATO SEGRETO.',
    f'''
<p>LATO SEGRETO nasce da un’idea semplice: ognuna ha un lato che non hai ancora visto. Le creator italiane hanno stili e
personalità molto diversi, ma online si perdono tra mille profili, social e link poco chiari. Volevamo uno spazio curato,
dove conoscerle davvero prima di decidere.</p>

<h2>Lato pubblico e lato segreto</h2>
<p>Ogni profilo ha due facce. Il <strong>lato pubblico</strong> racconta chi è la creator: il suo stile, la sua frase, le sue
foto e i suoi video. Il <strong>lato segreto</strong> si apre solo se lo scegli tu, con un’atmosfera diversa e un’anteprima
più personale. È un modo per conoscere una creator con calma, senza pressioni.</p>

<h2>Solo creator reali e maggiorenni</h2>
<p>Tutte le creator presenti sono maggiorenni e i contenuti sono scelti da loro. Ogni pulsante “Continua con me” porta al
profilo ufficiale, senza siti intermedi.</p>

<h2>Trovare chi ti somiglia</h2>
<p>Puoi esplorare per stile – <a href="/categorie/more">more</a>, <a href="/categorie/bionde">bionde</a>,
<a href="/categorie/tatuate">tatuate</a>, <a href="/categorie/eleganti">eleganti</a>,
<a href="/categorie/sportive">sportive</a>, <a href="/categorie/cosplay">cosplay</a> – oppure lasciarti sorprendere con il
pulsante “Sorprendimi”. Nella sezione “In movimento” della home trovi i video più recenti.</p>

<h2>Una rivista per orientarsi</h2>
<p>Nella rivista spieghiamo in modo semplice come funziona OnlyFans, quanto costa, come proteggere la propria privacy e come
riconoscere i profili ufficiali. Inizia dalla <a href="/articoli/onlyfans-italiane-guida">guida alle creator italiane</a>.</p>
''',
    ['zaira', 'alessia-golosa', 'aurora-bianchini', 'valeria-trapani'], 'zaira',
)

# ---------------------------------------------------------------- category texts
CATEGORIES = {
    'more': {
        'seo_title': 'Creator more italiane su OnlyFans | LATO SEGRETO',
        'meta_description': 'Le creator more italiane di LATO SEGRETO: sguardi intensi e fascino mediterraneo. Scopri il lato pubblico e il lato segreto di ogni profilo.',
        'testo_seo': '''
<h2>Creator more italiane: il fascino mediterraneo</h2>
<p>Capelli scuri, sguardi intensi e un fascino che sa di Mediterraneo: le creator more sono la categoria più ampia di LATO
SEGRETO. Ogni profilo ha il suo stile – dal più elegante al più alternativo – ma tutte condividono una presenza forte, che
si nota al primo sguardo.</p>
<p>Su questa pagina trovi tutte le creator more con un lato pubblico, per conoscerle, e un lato segreto, per vedere qualcosa
in più prima di passare al profilo ufficiale. Se ti piace uno stile più deciso, guarda anche le
<a href="/categorie/tatuate">creator tatuate</a>; per un’atmosfera più raffinata, le <a href="/categorie/eleganti">eleganti</a>.</p>
<p>Prima volta su OnlyFans? Leggi <a href="/articoli/come-funziona-onlyfans">come funziona</a> e
<a href="/articoli/quanto-costa-onlyfans">quanto costa</a>.</p>''',
    },
    'bionde': {
        'seo_title': 'Creator bionde italiane su OnlyFans | LATO SEGRETO',
        'meta_description': 'Le creator bionde italiane di LATO SEGRETO: luce, dolcezza e personalità. Scopri il lato pubblico e il lato segreto di ogni profilo.',
        'testo_seo': '''
<h2>Creator bionde italiane: luce e personalità</h2>
<p>Le creator bionde hanno un’immagine immediata, luminosa e solare. Ma dietro l’estetica c’è molto di più: identità, cura
dei dettagli e un modo di comunicare che le rende riconoscibili. Su LATO SEGRETO trovi bionde dallo stile elegante,
sportivo o alternativo.</p>
<p>Ogni profilo ti mostra prima il lato pubblico e poi, se vuoi, il lato segreto – un’anteprima scelta dalla creator stessa
prima di continuare sul suo profilo ufficiale. Approfondisci nella nostra guida
<a href="/articoli/bionde-italiane-da-seguire-stile-personalita-e-presenza-online">bionde italiane da seguire</a>.</p>''',
    },
    'tatuate': {
        'seo_title': 'Creator tatuate italiane su OnlyFans | LATO SEGRETO',
        'meta_description': 'Le creator tatuate italiane di LATO SEGRETO: stile alternativo, carattere e lato segreto. Scopri tutti i profili.',
        'testo_seo': '''
<h2>Creator tatuate italiane: stile e carattere</h2>
<p>Ogni tatuaggio racconta qualcosa. Le creator tatuate di LATO SEGRETO hanno uno stile deciso e una personalità forte, che
si ritrova nei loro contenuti: dal black work ai colori, dall’alternativo all’elegante.</p>
<p>Guarda il lato pubblico di ogni creator per capire il suo stile, poi apri il lato segreto per un’anteprima più personale.
Vuoi saperne di più? Leggi la nostra <a href="/articoli/guida-profili-tatuati-stile-carattere">guida alle creator tatuate</a>.</p>''',
    },
    'eleganti': {
        'seo_title': 'Creator eleganti italiane su OnlyFans | LATO SEGRETO',
        'meta_description': 'Le creator eleganti italiane di LATO SEGRETO: fashion, classe e atmosfera. Scopri il lato pubblico e il lato segreto di ogni profilo.',
        'testo_seo': '''
<h2>Creator eleganti: classe senza tempo</h2>
<p>Luce morbida, abiti curati e un’atmosfera raffinata: le creator eleganti puntano sullo stile più che sull’eccesso. Sono
perfette per chi apprezza il fascino che si costruisce con calma, un dettaglio alla volta.</p>
<p>Su LATO SEGRETO ogni creator elegante ha un lato pubblico, dove mostra il suo stile, e un lato segreto, dove l’eleganza
lascia spazio a qualcosa di più personale. Esplora anche le <a href="/categorie/bionde">bionde</a> e le
<a href="/categorie/more">more</a>.</p>''',
    },
    'sportive': {
        'seo_title': 'Creator sportive italiane su OnlyFans | LATO SEGRETO',
        'meta_description': 'Le creator sportive italiane di LATO SEGRETO: fitness, energia e disciplina. Scopri il lato pubblico e il lato segreto di ogni profilo.',
        'testo_seo': '''
<h2>Creator sportive italiane: energia e disciplina</h2>
<p>Allenamento, costanza e sicurezza di sé: le creator sportive uniscono la forza di chi si allena ogni giorno a un lato più
personale, che si scopre solo andando oltre.</p>
<p>Su questa pagina trovi tutte le creator sportive di LATO SEGRETO. Per capire cosa aspettarti, leggi
<a href="/articoli/fitness-e-sensualita-creator-sportive">fitness e sensualità: le creator sportive</a>.</p>''',
    },
    'cosplay': {
        'seo_title': 'Creator cosplay italiane su OnlyFans | LATO SEGRETO',
        'meta_description': 'Le creator cosplay italiane di LATO SEGRETO: personaggi, fantasia e creatività. Scopri il lato pubblico e il lato segreto.',
        'testo_seo': '''
<h2>Creator cosplay italiane: fantasia e trasformazione</h2>
<p>Costumi, personaggi e tanta creatività: le creator cosplay trasformano ogni contenuto in una piccola storia. È il mondo
giusto per chi ama anime, videogiochi e fantasia, ma anche la personalità di chi interpreta il personaggio.</p>
<p>Scopri come il personaggio incontra la persona nella nostra guida
<a href="/articoli/cosplay-creator-italiane-personalita">cosplay e creator italiane</a>.</p>''',
    },
    # no creators yet: keep the page out of Google until there is content
    'latine': {'indicizzabile': False},
}

out = {'articles': ARTICLES, 'categories': CATEGORIES}
(HERE / 'seo-inhalte.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf8')
import re
for a in ARTICLES:
    words = len(re.sub(r'<[^>]+>', ' ', a['contenuto']).split())
    print(f"{'ersetzt' if a['id'] else 'neu    '}  {words:>4} Wörter  /articoli/{a['slug']}")
print(f'{len(CATEGORIES)} Kategorien mit SEO-Daten')
