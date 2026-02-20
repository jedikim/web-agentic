import { describe, it, expect } from 'vitest';
import { WorkflowSchema, WorkflowStepSchema, ExpectationSchema } from '../../src/schemas/workflow.schema.js';

describe('ExpectationSchema', () => {
  it('validates a correct expectation', () => {
    const valid = { kind: 'url_contains', value: '/dashboard' };
    expect(ExpectationSchema.parse(valid)).toEqual(valid);
  });

  it('rejects invalid kind', () => {
    expect(() => ExpectationSchema.parse({ kind: 'invalid', value: 'x' })).toThrow();
  });

  it('rejects missing value', () => {
    expect(() => ExpectationSchema.parse({ kind: 'url_contains' })).toThrow();
  });
});

describe('WorkflowStepSchema', () => {
  it('validates a minimal step', () => {
    const valid = { id: 'open', op: 'goto' };
    expect(WorkflowStepSchema.parse(valid)).toEqual(valid);
  });

  it('validates a step with all optional fields', () => {
    const valid = {
      id: 'login',
      op: 'act_cached',
      targetKey: 'login.submit',
      args: { timeout: 5000 },
      expect: [{ kind: 'url_contains', value: '/dashboard' }],
      onFail: 'retry',
    };
    expect(WorkflowStepSchema.parse(valid)).toEqual(valid);
  });

  it('rejects invalid op', () => {
    expect(() => WorkflowStepSchema.parse({ id: 's', op: 'invalid' })).toThrow();
  });

  it('rejects missing id', () => {
    expect(() => WorkflowStepSchema.parse({ op: 'goto' })).toThrow();
  });

  it('rejects invalid onFail', () => {
    expect(() => WorkflowStepSchema.parse({ id: 's', op: 'goto', onFail: 'explode' })).toThrow();
  });
});

describe('WorkflowSchema', () => {
  it('validates a correct workflow', () => {
    const valid = {
      id: 'booking_flow',
      steps: [
        { id: 'open', op: 'goto', args: { url: 'https://example.com' } },
        { id: 'login', op: 'act_cached', targetKey: 'login.submit', expect: [{ kind: 'url_contains', value: '/dashboard' }] },
      ],
    };
    expect(WorkflowSchema.parse(valid)).toEqual(valid);
  });

  it('validates workflow with optional fields', () => {
    const valid = {
      id: 'flow',
      version: 'v001',
      vars: { url: 'https://example.com' },
      steps: [{ id: 'open', op: 'goto' }],
    };
    expect(WorkflowSchema.parse(valid)).toEqual(valid);
  });

  it('rejects workflow with no steps', () => {
    expect(() => WorkflowSchema.parse({ id: 'empty', steps: [] })).toThrow();
  });

  it('rejects workflow with missing id', () => {
    expect(() => WorkflowSchema.parse({ steps: [{ id: 's', op: 'goto' }] })).toThrow();
  });

  it('rejects invalid op in steps', () => {
    expect(() => WorkflowSchema.parse({ id: 'x', steps: [{ id: 's', op: 'invalid' }] })).toThrow();
  });
});
