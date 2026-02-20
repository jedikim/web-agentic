export interface Fingerprint {
  mustText?: string[];
  mustSelectors?: string[];
  urlContains?: string;
}

export type FingerprintsMap = Record<string, Fingerprint>;
