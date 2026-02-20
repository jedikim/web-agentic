import { describe, it, expect } from 'vitest';
import { PatchOpSchema, PatchPayloadSchema } from '../../src/schemas/patch.schema.js';

describe('PatchOpSchema', () => {
  it('validates an actions.replace op', () => {
    const valid = {
      op: 'actions.replace',
      key: 'login.submit',
      value: {
        selector: '/html/body/button[2]',
        description: 'Sign in button',
        method: 'click',
        arguments: [],
      },
    };
    expect(PatchOpSchema.parse(valid)).toEqual(valid);
  });

  it('validates an actions.add op', () => {
    const valid = {
      op: 'actions.add',
      key: 'logout.btn',
      value: {
        selector: '#logout',
        description: 'Logout button',
        method: 'click',
      },
    };
    expect(PatchOpSchema.parse(valid)).toEqual(valid);
  });

  it('validates a workflow.update_expect op', () => {
    const valid = {
      op: 'workflow.update_expect',
      step: 'login',
      value: [{ kind: 'url_contains', value: '/home' }],
    };
    expect(PatchOpSchema.parse(valid)).toEqual(valid);
  });

  it('validates all op types', () => {
    for (const op of ['actions.replace', 'actions.add', 'selectors.add', 'selectors.replace', 'workflow.update_expect', 'policies.update']) {
      const valid = { op, value: {} };
      expect(PatchOpSchema.parse(valid)).toEqual(valid);
    }
  });

  it('rejects invalid op', () => {
    expect(() => PatchOpSchema.parse({ op: 'workflow.delete', value: {} })).toThrow();
  });

  it('rejects missing op', () => {
    expect(() => PatchOpSchema.parse({ value: {} })).toThrow();
  });
});

describe('PatchPayloadSchema', () => {
  it('validates a correct patch payload', () => {
    const valid = {
      patch: [
        {
          op: 'actions.replace',
          key: 'login.submit',
          value: { selector: '#btn', description: 'btn', method: 'click' },
        },
        {
          op: 'workflow.update_expect',
          step: 'login',
          value: [{ kind: 'url_contains', value: '/home' }],
        },
      ],
      reason: 'Login redirect changed',
    };
    expect(PatchPayloadSchema.parse(valid)).toEqual(valid);
  });

  it('validates empty patch array', () => {
    const valid = { patch: [], reason: 'no changes needed' };
    expect(PatchPayloadSchema.parse(valid)).toEqual(valid);
  });

  it('rejects missing reason', () => {
    expect(() => PatchPayloadSchema.parse({ patch: [] })).toThrow();
  });

  it('rejects missing patch', () => {
    expect(() => PatchPayloadSchema.parse({ reason: 'x' })).toThrow();
  });

  it('rejects invalid op in patch array', () => {
    expect(() => PatchPayloadSchema.parse({
      patch: [{ op: 'invalid', value: {} }],
      reason: 'x',
    })).toThrow();
  });
});
