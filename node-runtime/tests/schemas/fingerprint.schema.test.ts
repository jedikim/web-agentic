import { describe, it, expect } from 'vitest';
import { FingerprintSchema, FingerprintsMapSchema } from '../../src/schemas/fingerprint.schema.js';

describe('FingerprintSchema', () => {
  it('validates a full fingerprint', () => {
    const valid = {
      mustText: ['Login', 'Welcome'],
      mustSelectors: ['#login-form', '.header'],
      urlContains: '/auth',
    };
    expect(FingerprintSchema.parse(valid)).toEqual(valid);
  });

  it('validates with all optional fields omitted', () => {
    const valid = {};
    expect(FingerprintSchema.parse(valid)).toEqual(valid);
  });

  it('validates with partial fields', () => {
    const valid = { mustText: ['Dashboard'] };
    expect(FingerprintSchema.parse(valid)).toEqual(valid);
  });

  it('rejects non-array mustText', () => {
    expect(() => FingerprintSchema.parse({ mustText: 'Login' })).toThrow();
  });

  it('rejects non-string urlContains', () => {
    expect(() => FingerprintSchema.parse({ urlContains: 123 })).toThrow();
  });

  it('rejects non-string items in mustSelectors', () => {
    expect(() => FingerprintSchema.parse({ mustSelectors: [123] })).toThrow();
  });
});

describe('FingerprintsMapSchema', () => {
  it('validates a correct fingerprints map', () => {
    const valid = {
      login_page: { mustText: ['Sign in'], urlContains: '/login' },
      dashboard: { mustSelectors: ['#main-content'] },
    };
    expect(FingerprintsMapSchema.parse(valid)).toEqual(valid);
  });

  it('validates empty map', () => {
    expect(FingerprintsMapSchema.parse({})).toEqual({});
  });
});
