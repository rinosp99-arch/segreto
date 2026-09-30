import { createContext, useContext } from 'react';

export const ThemeCtx = createContext({ homeMode: 'public', setHomeMode: () => {} });
export const useTheme = () => useContext(ThemeCtx);
