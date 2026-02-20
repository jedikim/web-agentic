import type { WorkflowStep } from '../types/index.js';

export function interpolate(template: string, vars: Record<string, unknown>): string {
  return template.replace(/\{\{vars\.(\w+)\}\}/g, (_, key) => String(vars[key] ?? ''));
}

function interpolateValue(value: unknown, vars: Record<string, unknown>): unknown {
  if (typeof value === 'string') {
    return interpolate(value, vars);
  }
  if (Array.isArray(value)) {
    return value.map((item) => interpolateValue(item, vars));
  }
  if (value !== null && typeof value === 'object') {
    const result: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      result[k] = interpolateValue(v, vars);
    }
    return result;
  }
  return value;
}

export function interpolateStep(step: WorkflowStep, vars: Record<string, unknown>): WorkflowStep {
  if (!step.args) return step;

  return {
    ...step,
    args: interpolateValue(step.args, vars) as Record<string, unknown>,
  };
}
