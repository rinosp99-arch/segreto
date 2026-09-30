// Library of selectable ambient tracks for the Secret Side.
// "Velluto Nero" (user-uploaded) is the default; the others are ready-made atmospheres.
export const TRACKS = [
  { id: 'velluto-nero', label: 'Velluto Nero', m4a: '/audio/velluto-nero.m4a', mp3: '/audio/velluto-nero.mp3' },
  { id: 'sensuale', label: 'Sensuale', mp3: '/audio/amb_sensuale.mp3' },
  { id: 'notturno', label: 'Notturno', mp3: '/audio/amb_notturno.mp3' },
  { id: 'lusso', label: 'Lusso', mp3: '/audio/amb_lusso.mp3' },
  { id: 'intimo', label: 'Intimo', mp3: '/audio/amb_intimo.mp3' },
  { id: 'intenso', label: 'Intenso', mp3: '/audio/amb_intenso.mp3' },
];

export const trackById = (id) => TRACKS.find((t) => t.id === id) || TRACKS[0];

// Resolve the {m4a, mp3} sources from a model's regia.audio config.
export const urlsForAudioCfg = (audio) => {
  const a = audio || {};
  if (a.custom_url) return { m4a: a.custom_url, mp3: a.custom_url };
  const t = trackById(a.traccia || 'velluto-nero');
  return { m4a: t.m4a || t.mp3, mp3: t.mp3 || t.m4a };
};
