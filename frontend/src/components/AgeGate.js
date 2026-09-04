import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { isAgeConfirmed, confirmAge } from '@/lib/session';
import { ShieldCheck } from 'lucide-react';

export default function AgeGate() {
  const [open, setOpen] = useState(!isAgeConfirmed());
  if (!open) return null;

  const accept = () => { confirmAge(); setOpen(false); };
  const exit = () => { window.location.href = 'https://www.google.com'; };

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[100] flex items-center justify-center p-5"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        style={{ background: 'radial-gradient(120% 90% at 50% 10%, rgba(20,15,10,0.9), rgba(0,0,0,0.97))' }}
        data-testid="age-gate"
      >
        <motion.div
          initial={{ y: 24, opacity: 0, scale: 0.98 }} animate={{ y: 0, opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }}
          className="glass rounded-2xl max-w-md w-full p-8 text-center card-elev-2"
        >
          <div className="flex justify-center mb-5">
            <div className="h-14 w-14 rounded-full flex items-center justify-center" style={{ background: 'hsl(var(--primary) / 0.14)', border: '1px solid hsl(var(--primary) / 0.4)' }}>
              <ShieldCheck className="h-7 w-7" style={{ color: 'hsl(var(--primary))' }} />
            </div>
          </div>
          <div className="caps-label gold-text mb-3">Accesso riservato</div>
          <h1 className="text-3xl mb-3 leading-tight">LATO SEGRETO</h1>
          <p className="text-muted-foreground text-sm leading-relaxed mb-7">
            Questo spazio è riservato a un pubblico adulto. Proseguendo dichiari di avere almeno 18 anni
            e di voler visualizzare contenuti destinati a maggiorenni.
          </p>
          <div className="space-y-3">
            <button onClick={accept} data-testid="age-gate-confirm-button"
              className="btn-gold w-full rounded-xl py-3.5 text-sm">
              Ho almeno 18 anni
            </button>
            <button onClick={exit} data-testid="age-gate-exit-button"
              className="w-full rounded-xl py-3 text-sm text-muted-foreground hover:text-foreground transition-colors">
              Esci
            </button>
          </div>
          <p className="text-[11px] text-muted-foreground/70 mt-6">
            Tutte le creator presenti sono maggiorenni. Continuando accetti i nostri termini.
          </p>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
