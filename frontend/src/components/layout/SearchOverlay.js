import { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, X } from 'lucide-react';
import { getModels, mediaUrl } from '@/lib/api';

export default function SearchOverlay({ open, onClose }) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 60); else { setQ(''); setResults([]); } }, [open]);

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(async () => {
      if (!q.trim()) { setResults([]); return; }
      setLoading(true);
      try { const d = await getModels({ q: q.trim(), limit: 8 }); setResults(d.items || []); }
      finally { setLoading(false); }
    }, 220);
    return () => clearTimeout(t);
  }, [q, open]);

  const go = (slug) => { onClose(); navigate(`/modelle/${slug}`); };

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[80] p-4 sm:p-8" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          style={{ background: 'rgba(0,0,0,0.8)' }} onClick={onClose}>
          <motion.div onClick={(e) => e.stopPropagation()}
            initial={{ y: -16, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -16, opacity: 0 }}
            className="max-w-xl mx-auto glass rounded-2xl card-elev-2 overflow-hidden">
            <div className="flex items-center gap-3 px-4 py-3.5 border-b border-border/60">
              <Search className="h-5 w-5 text-muted-foreground" />
              <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)}
                data-testid="model-search-input" placeholder="Cerca una modella…"
                className="flex-1 bg-transparent outline-none text-base placeholder:text-muted-foreground" />
              <button onClick={onClose} className="h-8 w-8 flex items-center justify-center rounded-full hover:bg-muted/50"><X className="h-4 w-4" /></button>
            </div>
            <div className="max-h-[60vh] overflow-auto p-2">
              {loading && <div className="p-4 text-sm text-muted-foreground">Ricerca in corso…</div>}
              {!loading && q && results.length === 0 && (
                <div className="p-6 text-center text-sm text-muted-foreground" data-testid="search-empty">Nessuna modella trovata. Prova un altro nome.</div>
              )}
              {results.map((m) => (
                <button key={m.slug} onClick={() => go(m.slug)} data-testid="search-result"
                  className="w-full flex items-center gap-3 p-2 rounded-xl hover:bg-muted/50 transition-colors text-left">
                  <img src={mediaUrl(m.foto_card)} alt={m.nome_artistico} className="h-12 w-12 rounded-lg object-cover" style={{ objectPosition: 'center 20%' }} />
                  <div>
                    <div className="font-serif text-lg leading-none">{m.nome_artistico}</div>
                    <div className="text-xs text-muted-foreground">{m.frase}</div>
                  </div>
                </button>
              ))}
              {!q && <div className="p-6 text-center text-sm text-muted-foreground">Digita il nome, l'alias o un tag di una creator.</div>}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
