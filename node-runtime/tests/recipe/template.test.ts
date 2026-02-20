import { describe, it, expect } from 'vitest';
import { interpolate, interpolateStep } from '../../src/recipe/template.js';
import type { WorkflowStep } from '../../src/types/index.js';

describe('interpolate', () => {
  it('replaces single variable', () => {
    expect(interpolate('https://{{vars.domain}}/login', { domain: 'example.com' }))
      .toBe('https://example.com/login');
  });

  it('replaces multiple variables', () => {
    expect(interpolate('{{vars.greeting}} {{vars.name}}!', { greeting: 'Hello', name: 'World' }))
      .toBe('Hello World!');
  });

  it('replaces missing variable with empty string', () => {
    expect(interpolate('{{vars.missing}}', {})).toBe('');
  });

  it('leaves non-variable patterns unchanged', () => {
    expect(interpolate('no variables here', { key: 'value' })).toBe('no variables here');
  });

  it('converts non-string values to string', () => {
    expect(interpolate('price: {{vars.price}}', { price: 42 })).toBe('price: 42');
  });
});

describe('interpolateStep', () => {
  it('interpolates step args', () => {
    const step: WorkflowStep = {
      id: 'open',
      op: 'goto',
      args: { url: 'https://{{vars.domain}}/{{vars.path}}' },
    };

    const result = interpolateStep(step, { domain: 'example.com', path: 'login' });
    expect(result.args?.url).toBe('https://example.com/login');
  });

  it('returns step unchanged if no args', () => {
    const step: WorkflowStep = { id: 'check', op: 'checkpoint' };
    const result = interpolateStep(step, { key: 'val' });
    expect(result).toEqual(step);
  });

  it('interpolates nested args', () => {
    const step: WorkflowStep = {
      id: 'act',
      op: 'act_template',
      args: {
        data: {
          name: '{{vars.name}}',
          nested: { value: '{{vars.val}}' },
        },
      },
    };

    const result = interpolateStep(step, { name: 'Alice', val: '42' });
    expect((result.args?.data as Record<string, unknown>).name).toBe('Alice');
    expect(((result.args?.data as Record<string, unknown>).nested as Record<string, unknown>).value).toBe('42');
  });

  it('interpolates arrays in args', () => {
    const step: WorkflowStep = {
      id: 'act',
      op: 'act_cached',
      args: { items: ['{{vars.a}}', '{{vars.b}}'] },
    };

    const result = interpolateStep(step, { a: 'x', b: 'y' });
    expect(result.args?.items).toEqual(['x', 'y']);
  });

  it('does not mutate original step', () => {
    const step: WorkflowStep = {
      id: 'open',
      op: 'goto',
      args: { url: '{{vars.url}}' },
    };

    interpolateStep(step, { url: 'https://example.com' });
    expect(step.args?.url).toBe('{{vars.url}}');
  });
});
