import { describe, it, expect } from 'vitest';
import { SelectorEntrySchema, SelectorsMapSchema } from '../../src/schemas/selector.schema.js';

describe('SelectorEntrySchema', () => {
  it('validates a correct selector entry', () => {
    const valid = {
      primary: '[data-testid="login-btn"]',
      fallbacks: ['button[type="submit"]', '#login-button'],
      strategy: 'testid',
    };
    expect(SelectorEntrySchema.parse(valid)).toEqual(valid);
  });

  it('validates with empty fallbacks', () => {
    const valid = { primary: '#btn', fallbacks: [], strategy: 'css' };
    expect(SelectorEntrySchema.parse(valid)).toEqual(valid);
  });

  it('rejects invalid strategy', () => {
    expect(() => SelectorEntrySchema.parse({
      primary: '#btn',
      fallbacks: [],
      strategy: 'invalid',
    })).toThrow();
  });

  it('rejects missing primary', () => {
    expect(() => SelectorEntrySchema.parse({ fallbacks: [], strategy: 'css' })).toThrow();
  });

  it('rejects missing fallbacks', () => {
    expect(() => SelectorEntrySchema.parse({ primary: '#btn', strategy: 'css' })).toThrow();
  });

  it('validates all strategy types', () => {
    for (const strategy of ['testid', 'role', 'css', 'xpath']) {
      const valid = { primary: '#btn', fallbacks: [], strategy };
      expect(SelectorEntrySchema.parse(valid)).toEqual(valid);
    }
  });
});

describe('SelectorsMapSchema', () => {
  it('validates a correct selectors map', () => {
    const valid = {
      'login.submit': {
        primary: '[data-testid="login-btn"]',
        fallbacks: ['button[type="submit"]'],
        strategy: 'testid',
      },
    };
    expect(SelectorsMapSchema.parse(valid)).toEqual(valid);
  });

  it('validates empty map', () => {
    expect(SelectorsMapSchema.parse({})).toEqual({});
  });
});
