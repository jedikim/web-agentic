import { describe, it, expect } from 'vitest';
import { PolicyConditionSchema, PolicyScoreRuleSchema, PolicySchema, PoliciesMapSchema } from '../../src/schemas/policy.schema.js';

describe('PolicyConditionSchema', () => {
  it('validates a correct condition', () => {
    const valid = { field: 'available', op: '==', value: true };
    expect(PolicyConditionSchema.parse(valid)).toEqual(valid);
  });

  it('validates all operator types', () => {
    for (const op of ['==', '!=', '<', '<=', '>', '>=', 'in', 'not_in', 'contains']) {
      const valid = { field: 'x', op, value: 'y' };
      expect(PolicyConditionSchema.parse(valid)).toEqual(valid);
    }
  });

  it('rejects invalid operator', () => {
    expect(() => PolicyConditionSchema.parse({ field: 'x', op: 'like', value: 'y' })).toThrow();
  });

  it('rejects missing field', () => {
    expect(() => PolicyConditionSchema.parse({ op: '==', value: true })).toThrow();
  });
});

describe('PolicyScoreRuleSchema', () => {
  it('validates a correct score rule', () => {
    const valid = {
      when: { field: 'zone', op: '==', value: 'front' },
      add: 30,
    };
    expect(PolicyScoreRuleSchema.parse(valid)).toEqual(valid);
  });

  it('rejects non-number add', () => {
    expect(() => PolicyScoreRuleSchema.parse({
      when: { field: 'x', op: '==', value: 'y' },
      add: 'thirty',
    })).toThrow();
  });
});

describe('PolicySchema', () => {
  it('validates a correct policy', () => {
    const valid = {
      hard: [{ field: 'available', op: '==', value: true }],
      score: [{ when: { field: 'zone', op: '==', value: 'front' }, add: 30 }],
      tie_break: ['price_asc', 'label_asc'],
      pick: 'argmax',
    };
    expect(PolicySchema.parse(valid)).toEqual(valid);
  });

  it('validates all pick types', () => {
    for (const pick of ['argmax', 'argmin', 'first']) {
      const valid = { hard: [], score: [], tie_break: [], pick };
      expect(PolicySchema.parse(valid)).toEqual(valid);
    }
  });

  it('rejects invalid pick', () => {
    expect(() => PolicySchema.parse({
      hard: [], score: [], tie_break: [], pick: 'random',
    })).toThrow();
  });

  it('rejects missing hard', () => {
    expect(() => PolicySchema.parse({ score: [], tie_break: [], pick: 'argmax' })).toThrow();
  });

  it('rejects missing score', () => {
    expect(() => PolicySchema.parse({ hard: [], tie_break: [], pick: 'argmax' })).toThrow();
  });
});

describe('PoliciesMapSchema', () => {
  it('validates a correct policies map', () => {
    const valid = {
      seat_policy_v1: {
        hard: [{ field: 'available', op: '==', value: true }],
        score: [],
        tie_break: ['price_asc'],
        pick: 'argmax',
      },
    };
    expect(PoliciesMapSchema.parse(valid)).toEqual(valid);
  });

  it('validates empty map', () => {
    expect(PoliciesMapSchema.parse({})).toEqual({});
  });
});
