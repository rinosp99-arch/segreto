{
  "brand": {
    "name": "LATO SEGRETO",
    "tone": ["lusso", "editoriale", "cinematografico", "soft-sensual", "mai volgare", "mai neon"],
    "language": "it-IT",
    "core_concept": {
      "same_url_dual_identity": true,
      "modes": [
        {
          "id": "public",
          "label": "Lato Pubblico",
          "vibe": "elegante / fashion / raffinato"
        },
        {
          "id": "secret",
          "label": "Lato Segreto",
          "vibe": "notturno / velluto / vetro scuro / luce soffusa"
        }
      ],
      "trigger_element": "NON DOVRESTI PREMERLO",
      "transformation": {
        "duration_ms": "600–1200",
        "beats": [
          "pre-signal (40–80ms): micro-dim + audio-less ‘thump’ visivo (ombra che cala)",
          "blackout (150–250ms): overlay quasi nero + blocco input",
          "flash (40–90ms): breve schiarita champagne (non bianco puro)",
          "reveal (350–750ms): cambio palette + vignetta + grain + foto morph + indicator ‘LATO SEGRETO’"
        ],
        "reduced_motion": "Se prefers-reduced-motion: riduci a crossfade 200–300ms senza blackout/flash; niente blur animato."
      }
    }
  },

  "google_fonts": {
    "title_serif_display": {
      "family": "Cormorant Garamond",
      "weights": [400, 500, 600, 700],
      "usage": "Titoli, numeri hero, quote editoriali"
    },
    "ui_sans": {
      "family": "Manrope",
      "weights": [400, 500, 600, 700],
      "usage": "UI, body, label, tabelle, admin"
    },
    "import_note": "Caricare via Google Fonts (index.html) e impostare in Tailwind (fontFamily). Esattamente 2 famiglie."
  },

  "design_tokens": {
    "color_tokens_hsl": {
      "public": {
        "background": "220 10% 6%",
        "foreground": "38 28% 92%",
        "surface": "220 9% 9%",
        "surface_2": "220 8% 12%",
        "card": "220 9% 10%",
        "card_foreground": "38 28% 92%",
        "muted": "220 7% 16%",
        "muted_foreground": "38 10% 72%",
        "primary_gold": "42 45% 62%",
        "primary_foreground": "220 12% 8%",
        "accent_champagne": "38 30% 86%",
        "accent_foreground": "220 12% 8%",
        "border": "220 8% 18%",
        "ring": "42 45% 62%",
        "glass": {
          "bg": "220 10% 10%",
          "alpha": 0.55,
          "border": "42 30% 70%"
        },
        "state": {
          "success": "150 35% 42%",
          "warning": "38 70% 55%",
          "destructive": "0 55% 45%"
        },
        "charts": {
          "chart_1": "42 45% 62%",
          "chart_2": "38 30% 86%",
          "chart_3": "220 8% 55%",
          "chart_4": "150 25% 45%",
          "chart_5": "20 35% 55%"
        }
      },
      "secret": {
        "background": "240 12% 4%",
        "foreground": "38 28% 92%",
        "surface": "240 10% 7%",
        "surface_2": "240 10% 10%",
        "card": "240 10% 8%",
        "card_foreground": "38 28% 92%",
        "muted": "240 9% 14%",
        "muted_foreground": "38 10% 70%",
        "primary_gold": "40 55% 60%",
        "primary_foreground": "240 12% 6%",
        "accent_bordeaux": "350 45% 28%",
        "accent_wine": "355 55% 34%",
        "accent_violet_dark": "275 22% 18%",
        "border": "240 10% 16%",
        "ring": "40 55% 60%",
        "glass": {
          "bg": "240 12% 6%",
          "alpha": 0.62,
          "border": "40 35% 62%"
        },
        "effects": {
          "vignette": "radial-gradient(120% 90% at 50% 20%, rgba(0,0,0,0) 0%, rgba(0,0,0,0.55) 55%, rgba(0,0,0,0.85) 100%)",
          "soft_glow": "0 0 0 1px hsl(40 55% 60% / 0.18), 0 18px 60px rgba(0,0,0,0.55)",
          "grain": "Usare overlay PNG/SVG noise a bassa opacità (0.06–0.10)"
        },
        "charts": {
          "chart_1": "40 55% 60%",
          "chart_2": "350 45% 28%",
          "chart_3": "275 22% 18%",
          "chart_4": "38 30% 86%",
          "chart_5": "220 8% 55%"
        }
      }
    },

    "radius": {
      "xs": "6px",
      "sm": "10px",
      "md": "14px",
      "lg": "18px",
      "xl": "24px"
    },

    "spacing": {
      "container_px_mobile": "px-4",
      "container_px_desktop": "lg:px-10",
      "section_py": "py-10 sm:py-14 lg:py-18",
      "card_gap": "gap-3 sm:gap-4",
      "grid_gap": "gap-4 sm:gap-5"
    },

    "shadows": {
      "elev_1": "0 1px 0 rgba(255,255,255,0.04), 0 10px 30px rgba(0,0,0,0.35)",
      "elev_2": "0 1px 0 rgba(255,255,255,0.06), 0 18px 60px rgba(0,0,0,0.55)",
      "gold_edge": "0 0 0 1px hsl(var(--primary) / 0.22)"
    },

    "glass_blur": {
      "backdrop": "backdrop-blur-md",
      "bg_public": "bg-[hsl(var(--glass-bg)/0.55)]",
      "bg_secret": "bg-[hsl(var(--glass-bg)/0.62)]",
      "border": "border border-[hsl(var(--glass-border)/0.22)]"
    },

    "motion": {
      "easing": {
        "cinematic": "cubic-bezier(0.2, 0.8, 0.2, 1)",
        "snap": "cubic-bezier(0.2, 1, 0.2, 1)",
        "soft": "cubic-bezier(0.25, 0.1, 0.25, 1)"
      },
      "durations_ms": {
        "hover": 160,
        "press": 90,
        "panel": 240,
        "transform_total": "600–1200",
        "blackout": "150–250",
        "flash": "40–90",
        "reveal": "350–750"
      },
      "framer_motion_note_js": "Usare motion.div e AnimatePresence in .js. Rispettare prefers-reduced-motion con useReducedMotion()."
    }
  },

  "layout": {
    "grid": {
      "home_model_grid": {
        "mobile": "grid-cols-2",
        "tablet": "md:grid-cols-3",
        "desktop": "lg:grid-cols-4 xl:grid-cols-5",
        "notes": "Card ratio coerente (3:4). Spaziatura generosa."
      },
      "page_container": "max-w-6xl mx-auto",
      "mobile_first_viewport": "390x844"
    },
    "patterns": {
      "reading": "Allineamento a sinistra; evitare layout centrati globali.",
      "hero": "Split verticale su desktop (testo a sinistra, immagine a destra). Su mobile: immagine sopra, testo sotto.",
      "secret_side": "Più profondità: vignetta + glass scuro + accenti bordeaux su micro-elementi (badge, chip attivi)."
    }
  },

  "component_path": {
    "shadcn_primary": "/app/frontend/src/components/ui",
    "use_components": [
      "button.jsx",
      "card.jsx",
      "badge.jsx",
      "input.jsx",
      "dialog.jsx",
      "drawer.jsx",
      "sheet.jsx",
      "tabs.jsx",
      "toggle-group.jsx",
      "select.jsx",
      "command.jsx",
      "tooltip.jsx",
      "hover-card.jsx",
      "skeleton.jsx",
      "sonner.jsx",
      "table.jsx",
      "pagination.jsx",
      "separator.jsx",
      "scroll-area.jsx",
      "calendar.jsx",
      "alert-dialog.jsx"
    ],
    "charts": {
      "library": "recharts",
      "note": "Mappare colori a var(--chart-1..5) e usare Card + padding coerente."
    },
    "motion": {
      "library": "framer-motion",
      "note": "Animazioni solo su elementi chiave; rispettare reduced motion."
    }
  },

  "typography": {
    "font_usage": {
      "h1_h2_titles": "Cormorant Garamond",
      "ui_body": "Manrope"
    },
    "scale_tailwind": {
      "h1": "text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-[-0.02em]",
      "h2": "text-base md:text-lg font-medium text-muted-foreground",
      "h3": "text-xl sm:text-2xl font-semibold",
      "body": "text-sm sm:text-base leading-relaxed",
      "small": "text-xs sm:text-sm text-muted-foreground",
      "caps_label": "text-[11px] tracking-[0.18em] uppercase"
    },
    "italian_copy_tone": {
      "rules": [
        "Evitare slang esplicito.",
        "Usare lessico premium: ‘accesso’, ‘anteprima’, ‘collezione’, ‘privato’, ‘invito’.",
        "CTA brevi e sicure: ‘Sblocca’, ‘Entra’, ‘Richiedi accesso’."
      ]
    }
  },

  "components": {
    "age_gate_18_plus": {
      "type": "Dialog (desktop) + Drawer (mobile)",
      "copy_it": {
        "title": "Conferma età",
        "body": "Questo sito è riservato a maggiorenni (18+). Proseguendo confermi di avere almeno 18 anni.",
        "primary": "Ho 18+",
        "secondary": "Esci"
      },
      "ui": {
        "layout": "Card glass su sfondo scuro con vignetta leggera.",
        "details": "Checkbox ‘Ricordami’ (Switch) + link policy.",
        "data_testids": {
          "confirm": "age-gate-confirm-button",
          "exit": "age-gate-exit-button",
          "remember": "age-gate-remember-switch"
        }
      }
    },

    "header": {
      "type": "Sticky header glass",
      "structure": ["Logo LATO SEGRETO", "Ricerca", "Filtri", "CTA ‘SORPRENDIMI’"],
      "behavior": {
        "scroll": "Riduci altezza + aumenta blur dopo 24px scroll.",
        "mode_indicator": "Pill a destra: ‘Lato Pubblico’ / ‘Lato Segreto’ con micro-glow oro (solo secret)."
      },
      "data_testids": {
        "search": "header-search-input",
        "surprise": "header-surprise-button",
        "mode": "header-mode-indicator"
      }
    },

    "search": {
      "component": "Input + Command (per suggerimenti)",
      "placeholder_it": "Cerca creator, stile, città…",
      "micro_interactions": "Focus ring oro; suggerimenti con highlight champagne.",
      "data_testids": {
        "input": "model-search-input",
        "command": "model-search-suggestions"
      }
    },

    "filter_chips": {
      "component": "ToggleGroup (multiple)",
      "chips": ["Nuove", "Top", "Editoriale", "Discreto", "Notte"],
      "states": {
        "default": "bg-muted/40 text-muted-foreground border-border",
        "active_public": "bg-[hsl(var(--primary)/0.14)] text-foreground border-[hsl(var(--primary)/0.35)]",
        "active_secret": "bg-[hsl(var(--accent)/0.18)] text-foreground border-[hsl(var(--accent)/0.35)]"
      },
      "data_testids": {
        "group": "filters-toggle-group"
      }
    },

    "surprise": {
      "name": "SORPRENDIMI",
      "component": "Button (primary)",
      "behavior": "Seleziona un profilo casuale con transizione ‘page reveal’ (fade + slight slide).",
      "data_testids": {
        "button": "surprise-me-button"
      }
    },

    "model_card": {
      "component": "Card + AspectRatio + Badge + HoverCard",
      "ratio": "3/4",
      "public_style": {
        "image": "pulita, luce morbida",
        "overlay": "gradiente leggero dal basso (max 18% altezza card)",
        "meta": "nome + 1 riga descrittiva + badge ‘Premium’ oro"
      },
      "secret_style": {
        "image": "più scura, contrasto controllato",
        "overlay": "vignetta + grain + glass scuro",
        "meta": "badge ‘LATO SEGRETO’ + accento bordeaux su micro-dettagli"
      },
      "hover": {
        "motion": "lift 2px + shadow elev_2 + bordo oro sottile",
        "avoid": "niente zoom aggressivo"
      },
      "data_testids": {
        "card": "model-card",
        "open": "model-card-open"
      }
    },

    "non_dovresti_premerlo": {
      "component": "Button / Card interactive (custom)",
      "concept_options": [
        {
          "id": "sealed_button",
          "name": "Sigillo in ceralacca (minimal)",
          "look": "Pill scura con bordo oro + piccolo ‘sigillo’ bordeaux a sinistra (Badge circolare)",
          "copy": "NON DOVRESTI PREMERLO",
          "micro": "hover: glow oro 12% + rumore/grain leggero; press: scale 0.98"
        },
        {
          "id": "forbidden_switch",
          "name": "Interruttore ‘vietato’ (sofisticato)",
          "look": "Card glass con Switch centrale; label sopra in caps",
          "copy": "NON DOVRESTI PREMERLO",
          "micro": "toggle: blackout beat + reveal; switch thumb con highlight champagne"
        },
        {
          "id": "envelope_trigger",
          "name": "Busta/Invito (editoriale)",
          "look": "Card con icona (lucide: Mail) + bordo oro; sembra un invito",
          "copy": "Apri l’invito",
          "micro": "hover: bordo oro + ombra; click: breve flash champagne"
        }
      ],
      "data_testids": {
        "trigger": "secret-trigger-button"
      }
    },

    "transformation_choreography": {
      "implementation": {
        "state": "themeMode: 'public' | 'secret' (persist in localStorage opzionale)",
        "layers": [
          "Overlay blackout (fixed inset-0)",
          "Overlay flash (fixed inset-0)",
          "Vignette layer (solo secret)",
          "Grain layer (solo secret)"
        ],
        "photo_morph": "Crossfade tra due immagini (public/secret) con slight blur-in (solo se motion allowed).",
        "text_palette": "Swap CSS variables via class su html/body: .theme-public / .theme-secret"
      },
      "timings": {
        "blackout_ms": "150–250",
        "flash_ms": "40–90",
        "reveal_ms": "350–750"
      },
      "data_testids": {
        "blackout": "theme-blackout-overlay",
        "flash": "theme-flash-overlay",
        "indicator": "secret-mode-indicator"
      }
    },

    "secret_side_layout": {
      "structure": [
        "Hero immagine + indicator ‘LATO SEGRETO’",
        "Teaser-lock card (contenuto sfocato/mascherato)",
        "CTA sticky mobile ‘Sblocca accesso’",
        "Sezione ‘Messaggio tra 35s’ (busta)"
      ],
      "notes": "Più spazio verticale, meno elementi. Ogni blocco sembra una pagina di magazine notturno."
    },

    "teaser_lock_card": {
      "component": "Card + Skeleton + Button",
      "behavior": "Mostra anteprima sfocata (blur statico, non animato) + overlay ‘Contenuto riservato’.",
      "cta": "Sblocca per vedere",
      "data_testids": {
        "card": "teaser-lock-card",
        "cta": "teaser-lock-cta-button"
      }
    },

    "envelope_35s_message": {
      "component": "Card + Progress + Button",
      "copy_it": {
        "title": "Un messaggio sta arrivando",
        "body": "Aprilo tra 35 secondi. L’attesa fa parte dell’invito.",
        "button": "Apri quando pronto"
      },
      "behavior": "Progress countdown 35s; al termine abilita CTA. Nessun suono.",
      "data_testids": {
        "card": "envelope-message-card",
        "progress": "envelope-countdown-progress",
        "button": "envelope-open-button"
      }
    },

    "cta_variants": {
      "primary": {
        "style": "Oro caldo su fondo scuro; testo scuro; shadow elev_1",
        "label_examples": ["Sblocca accesso", "Entra", "Richiedi invito"],
        "data_testid": "primary-cta-button"
      },
      "secondary": {
        "style": "Glass scuro + bordo oro sottile; testo champagne",
        "label_examples": ["Vedi anteprima", "Salva", "Condividi"],
        "data_testid": "secondary-cta-button"
      },
      "ghost": {
        "style": "Trasparente; underline on hover; focus ring oro",
        "label_examples": ["Leggi di più", "Dettagli"],
        "data_testid": "ghost-cta-button"
      },
      "sticky_mobile": {
        "pattern": "Bar fissa bottom con blur + CTA primaria full-width",
        "height": "64px",
        "data_testid": "sticky-mobile-cta"
      }
    },

    "admin_shell": {
      "layout": "Sidebar (Sheet su mobile) + topbar + content",
      "nav_groups": ["Creator", "Contenuti", "Blog", "Funnel", "Impostazioni"],
      "style": "Stesso DNA luxury ma più neutro: meno vignetta, più leggibilità.",
      "data_testids": {
        "sidebar": "admin-sidebar",
        "nav": "admin-nav",
        "logout": "admin-logout-button"
      }
    },

    "analytics": {
      "kpi_cards": {
        "component": "Card",
        "layout": "grid grid-cols-2 lg:grid-cols-4 gap-4",
        "content": "Titolo caps + valore grande + delta badge + sparkline",
        "data_testid": "analytics-kpi-card"
      },
      "funnel": {
        "component": "Card + Recharts (Bar/Area)",
        "notes": "Usare colori chart_1..5; tooltip glass.",
        "data_testid": "analytics-funnel-chart"
      },
      "charts": {
        "types": ["Area (trend)", "Bar (funnel)", "Pie (mix canali)"],
        "data_testid": "analytics-chart"
      }
    },

    "skeletons": {
      "component": "Skeleton",
      "pattern": "Shimmer molto sottile (opacity 0.06–0.10) su surface.",
      "data_testid": "loading-skeleton"
    },

    "empty_states": {
      "copy_it": {
        "title": "Nessun risultato",
        "body": "Prova a cambiare filtri o cerca un altro nome.",
        "cta": "Azzera filtri"
      },
      "visual": "Icona lucide (SearchX) + micro-grain.",
      "data_testids": {
        "wrap": "empty-state",
        "cta": "empty-state-reset-filters"
      }
    },

    "not_found_404": {
      "copy_it": {
        "title": "Pagina non trovata",
        "body": "Forse era un invito destinato a qualcun altro.",
        "cta": "Torna alla home"
      },
      "data_testids": {
        "cta": "not-found-home-button"
      }
    },

    "cookie_banner": {
      "component": "Card (fixed bottom) + Buttons",
      "copy_it": {
        "title": "Preferenze cookie",
        "body": "Usiamo cookie per migliorare l’esperienza e misurare le performance.",
        "accept": "Accetta",
        "reject": "Rifiuta",
        "manage": "Gestisci"
      },
      "style": "Glass + bordo oro sottile; mai invadente.",
      "data_testids": {
        "banner": "cookie-banner",
        "accept": "cookie-accept-button",
        "reject": "cookie-reject-button",
        "manage": "cookie-manage-button"
      }
    }
  },

  "image_urls": {
    "model_portraits_public": [
      {
        "url": "https://images.unsplash.com/photo-1585362607599-2818603c75e4?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA2MTJ8MHwxfHNlYXJjaHw0fHxsdXh1cnklMjBmYXNoaW9yaWFsJTIwcG9ydHJhaXQlMjBsb3clMjBrZXklMjBsaWdodGluZ3xlbnwwfHx8YmxhY2t8MTc4ODQ4MzI2M3ww&ixlib=rb-4.1.0&q=85",
        "usage": "Hero/model page (Lato Pubblico)"
      },
      {
        "url": "https://images.unsplash.com/photo-1595065666634-4725aa7e8379?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA2MTJ8MHwxfHNlYXJjaHwzfHxsdXh1cnklMjBmYXNoaW9uJTIwZWRpdG9yaWFsJTIwcG9ydHJhaXQlMjBsb3clMjBrZXklMjBsaWdodGluZ3xlbnwwfHx8YmxhY2t8MTc4ODQ4MzI2M3ww&ixlib=rb-4.1.0&q=85",
        "usage": "Card grid (Lato Pubblico)"
      }
    ],
    "model_portraits_secret": [
      {
        "url": "https://images.pexels.com/photos/31507926/pexels-photo-31507926.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "usage": "Hero/model page (Lato Segreto)"
      },
      {
        "url": "https://images.pexels.com/photos/19342940/pexels-photo-19342940.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "usage": "Card grid (Lato Segreto)"
      }
    ],
    "textures_secret": [
      {
        "url": "https://images.unsplash.com/photo-1696937059544-d27af28d458d?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NTYxODl8MHwxfHNlYXJjaHwxfHxib3JkZWF1eCUyMHZlbHZldCUyMHRleHR1cmUlMjBkYXJrJTIwbHV4dXJ5JTIwYmFja2dyb3VuZHxlbnwwfHx8cmVkfDE3ODg0ODMyNjh8MA&ixlib=rb-4.1.0&q=85",
        "usage": "Overlay texture (velluto) per sezioni secret (decorativo, opacità 0.06–0.10)"
      },
      {
        "url": "https://images.unsplash.com/photo-1568535904307-f48b760a39f3?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NTYxODl8MHwxfHNlYXJjaHwyfHxib3JkZWF1eCUyMHZlbHZldCUyMHRleHR1cmUlMjBkYXJrJTIwbHV4dXJ5JTIwYmFja2dyb3VuZHxlbnwwfHx8cmVkfDE3ODQ4ODMyNjh8MA&ixlib=rb-4.1.0&q=85",
        "usage": "Background texture per teaser-lock (decorativo, non testo)"
      }
    ]
  },

  "instructions_to_main_agent": {
    "theme_implementation": [
      "Sostituire i token in /app/frontend/src/index.css: definire :root come theme-public e aggiungere .theme-secret con override (non usare .dark generico).",
      "Aggiungere class su <html> o <body>: theme-public / theme-secret.",
      "Non usare gradienti saturi; usare solo solid + overlay vignetta/grain. Gradiente consentito solo come overlay piccolo su immagini (<=18% altezza card).",
      "Implementare overlay grain come pseudo-elemento fixed con background-image (noise) e mix-blend-mode: overlay; opacity 0.06–0.10.",
      "Implementare ‘NON DOVRESTI PREMERLO’ con Framer Motion: sequenza blackout->flash->reveal; bloccare input durante blackout.",
      "Tutto il copy UI in italiano.",
      "Tutti gli elementi interattivi e info chiave devono avere data-testid (kebab-case)."
    ],
    "tailwind_class_snippets": {
      "page_bg_public": "bg-background text-foreground",
      "page_bg_secret": "bg-background text-foreground [background-image:var(--secret-vignette)]",
      "glass_card": "rounded-[var(--radius-md)] border border-border/60 bg-[hsl(var(--glass-bg)/0.55)] backdrop-blur-md shadow-[var(--shadow-elev-1)]",
      "gold_focus": "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-0",
      "model_card": "group relative overflow-hidden rounded-[var(--radius-lg)] border border-border/60 bg-card shadow-[var(--shadow-elev-1)]",
      "model_card_hover": "hover:shadow-[var(--shadow-elev-2)] hover:-translate-y-[2px] transition-[box-shadow,transform] duration-200"
    },
    "libraries": {
      "framer_motion": {
        "install": "npm i framer-motion",
        "usage": "import { motion, AnimatePresence, useReducedMotion } from 'framer-motion'"
      },
      "recharts": {
        "install": "npm i recharts",
        "usage": "Usare <ResponsiveContainer> e colori da CSS vars --chart-1..5"
      },
      "icons": {
        "use": "lucide-react",
        "avoid": "emoji"
      }
    }
  },

  "general_ui_ux_design_guidelines_appendix": "<General UI UX Design Guidelines>  \n    - You must **not** apply universal transition. Eg: `transition: all`. This results in breaking transforms. Always add transitions for specific interactive elements like button, input excluding transforms\n    - You must **not** center align the app container, ie do not add `.App { text-align: center; }` in the css file. This disrupts the human natural reading flow of text\n   - NEVER: use AI assistant Emoji characters like`🤖🧠💭💡🔮🎯📚🎭🎬🎪🎉🎊🎁🎀🎂🍰🎈🎨🎰💰💵💳🏦💎🪙💸🤑📊📈📉💹🔢🏆🥇 etc for icons. Always use **FontAwesome cdn** or **lucid-react** library already installed in the package.json\n\n **GRADIENT RESTRICTION RULE**\nNEVER use dark/saturated gradient combos (e.g., purple/pink) on any UI element.  Prohibited gradients: blue-500 to purple 600, purple 500 to pink-500, green-500 to blue-500, red to pink etc\nNEVER use dark gradients for logo, testimonial, footer etc\nNEVER let gradients cover more than 20% of the viewport.\nNEVER apply gradients to text-heavy content or reading areas.\nNEVER use gradients on small UI elements (<100px width).\nNEVER stack multiple gradient layers in the same viewport.\n\n**ENFORCEMENT RULE:**\n    • Id gradient area exceeds 20% of viewport OR affects readability, **THEN** use solid colors\n\n**How and where to use:**\n   • Section backgrounds (not content backgrounds)\n   • Hero section header content. Eg: dark to light to dark color\n   • Decorative overlays and accent elements only\n   • Hero section with 2-3 mild color\n   • Gradients creation can be done for any angle say horizontal, vertical or diagonal\n\n- For AI chat, voice application, **do not use purple color. Use color like light green, ocean blue, peach orange etc**\n\n</Font Guidelines>\n\n- Every interaction needs micro-animations - hover states, transitions, parallax effects, and entrance animations. Static = dead. \n   \n- Use 2-3x more spacing than feels comfortable. Cramped designs look cheap.\n\n- Subtle grain textures, noise overlays, custom cursors, selection states, and loading animations: separates good from extraordinary.\n   \n- Before generating UI, infer the visual style from the problem statement (palette, contrast, mood, motion) and immediately instantiate it by setting global design tokens (primary, secondary/accent, background, foreground, ring, state colors), rather than relying on any library defaults. Don't make the background dark as a default step, always understand problem first and define colors accordingly\n    Eg: - if it implies playful/energetic, choose a colorful scheme\n           - if it implies monochrome/minimal, choose a black–white/neutral scheme\n\n**Component Reuse:**\n\t- Prioritize using pre-existing components from src/components/ui when applicable\n\t- Create new components that match the style and conventions of existing components when needed\n\t- Examine existing components to understand the project's component patterns before creating new ones\n\n**IMPORTANT**: Do not use HTML based component like dropdown, calendar, toast etc. You **MUST** always use `/app/frontend/src/components/ui/ ` only as a primary components as these are modern and stylish component\n\n**Best Practices:**\n\t- Use Shadcn/UI as the primary component library for consistency and accessibility\n\t- Import path: ./components/[component-name]\n\n**Export Conventions:**\n\t- Components MUST use named exports (export const ComponentName = ...)\n\t- Pages MUST use default exports (export default function PageName() {...})\n\n**Toasts:**\n  - Use `sonner` for toasts\"\n  - Sonner component are located in `/app/src/components/ui/sonner.tsx`\n\nUse 2–4 color gradients, subtle textures/noise overlays, or CSS-based noise to avoid flat visuals.\n</General UI UX Design Guidelines>"
}
