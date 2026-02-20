import { describe, it, expect } from 'vitest';
import { ActionRefSchema, ActionEntrySchema, ActionsMapSchema } from '../../src/schemas/action.schema.js';

describe('ActionRefSchema', () => {
  it('validates a correct action ref', () => {
    const valid = {
      selector: '/html/body/button[1]',
      description: 'Login button',
      method: 'click',
    };
    expect(ActionRefSchema.parse(valid)).toEqual(valid);
  });

  it('validates with arguments', () => {
    const valid = {
      selector: '#email',
      description: 'Email input',
      method: 'fill',
      arguments: ['user@example.com'],
    };
    expect(ActionRefSchema.parse(valid)).toEqual(valid);
  });

  it('rejects missing selector', () => {
    expect(() => ActionRefSchema.parse({ description: 'x', method: 'click' })).toThrow();
  });

  it('rejects missing description', () => {
    expect(() => ActionRefSchema.parse({ selector: 'x', method: 'click' })).toThrow();
  });

  it('rejects missing method', () => {
    expect(() => ActionRefSchema.parse({ selector: 'x', description: 'x' })).toThrow();
  });
});

describe('ActionEntrySchema', () => {
  it('validates a correct action entry', () => {
    const valid = {
      instruction: 'find the login button',
      preferred: {
        selector: '/html/body/button[1]',
        description: 'Login button',
        method: 'click',
      },
      observedAt: '2026-02-20T23:00:00Z',
    };
    expect(ActionEntrySchema.parse(valid)).toEqual(valid);
  });

  it('rejects missing instruction', () => {
    expect(() => ActionEntrySchema.parse({
      preferred: { selector: 'x', description: 'x', method: 'click' },
      observedAt: '2026-02-20T23:00:00Z',
    })).toThrow();
  });

  it('rejects missing observedAt', () => {
    expect(() => ActionEntrySchema.parse({
      instruction: 'x',
      preferred: { selector: 'x', description: 'x', method: 'click' },
    })).toThrow();
  });
});

describe('ActionsMapSchema', () => {
  it('validates a correct actions map', () => {
    const valid = {
      'login.submit': {
        instruction: 'find the login button',
        preferred: {
          selector: '/html/body/button[1]',
          description: 'Login button',
          method: 'click',
        },
        observedAt: '2026-02-20T23:00:00Z',
      },
    };
    expect(ActionsMapSchema.parse(valid)).toEqual(valid);
  });

  it('validates empty map', () => {
    expect(ActionsMapSchema.parse({})).toEqual({});
  });

  it('rejects invalid entry in map', () => {
    expect(() => ActionsMapSchema.parse({ key: { instruction: 'x' } })).toThrow();
  });
});
