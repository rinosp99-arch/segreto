import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { getConsent, setConsent } from '@/lib/session';
import { Link } from 'react-router-dom';

export default function CookieBanner() {
  const [visible, setVisible] = useState(!getConsent());
  if (!visible) return null;
  const choose = (v) => { setConsent(v); setVisible(false); };
  return (
    <AnimatePresence>
      <motion.div
        initial={{ y: 80, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 80, opacity: 0 }}
        transition={{ duration: 0.4, ease: [0.2, 0.8, 0.2, 1] }}
        className="fixed bottom-3 left-3 right-3 md:left-auto md:right-4 md:max-w-md z-[90]"
        data-testid="cookie-banner"
      >
        <div className="glass rounded-2xl p-4 card-elev-2">
          <div className="caps-label gold-text mb-1">Preferenze cookie</div>
          <p className="text-xs text-muted-foreground leading-relaxed mb-3">
            Usiamo cookie tecnici e di misurazione per migliorare l'esperienza. Puoi accettare o rifiutare quelli non essenziali.{' '}
            <Link to="/cookie" className="underline hover:text-foreground">Dettagli</Link>
          </p>
          <div className="flex gap-2">
            <button onClick={() => choose('accept')} data-testid="cookie-accept-button"
              className="btn-gold flex-1 rounded-lg py-2 text-xs">Accetta</button>
            <button onClick={() => choose('reject')} data-testid="cookie-reject-button"
              className="flex-1 rounded-lg py-2 text-xs border border-border text-muted-foreground hover:text-foreground transition-colors">Rifiuta</button>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
