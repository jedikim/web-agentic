export interface SelectorEntry {
  primary: string;
  fallbacks: string[];
  strategy: 'testid' | 'role' | 'css' | 'xpath';
}

export type SelectorsMap = Record<string, SelectorEntry>;
