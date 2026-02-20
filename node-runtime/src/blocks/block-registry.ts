import type { WorkflowStep } from '../types/index.js';
import type { WorkflowBlock } from './block-types.js';
import { navigationBlock } from './builtins/navigation.block.js';
import { actionBlock } from './builtins/action.block.js';
import { extractBlock } from './builtins/extract.block.js';
import { validationBlock } from './builtins/validation.block.js';

/**
 * Registry for reusable workflow blocks.
 * Blocks are parameterized step templates that can be expanded
 * into concrete WorkflowStep arrays with {{param.xxx}} interpolation.
 */
export class BlockRegistry {
  private blocks = new Map<string, WorkflowBlock>();

  /**
   * Register a workflow block. Throws if a block with the same ID already exists.
   */
  register(block: WorkflowBlock): void {
    if (this.blocks.has(block.id)) {
      throw new Error(`Block "${block.id}" is already registered`);
    }
    this.blocks.set(block.id, block);
  }

  /**
   * Get a block by ID.
   */
  get(id: string): WorkflowBlock | undefined {
    return this.blocks.get(id);
  }

  /**
   * Get all blocks of a given type.
   */
  getByType(type: string): WorkflowBlock[] {
    return Array.from(this.blocks.values()).filter((b) => b.type === type);
  }

  /**
   * List all registered blocks.
   */
  list(): WorkflowBlock[] {
    return Array.from(this.blocks.values());
  }

  /**
   * Expand a block into concrete WorkflowStep[] by replacing {{param.xxx}} placeholders.
   * Validates that all required parameters are provided and applies defaults.
   */
  expandBlock(blockId: string, params: Record<string, unknown>): WorkflowStep[] {
    const block = this.blocks.get(blockId);
    if (!block) {
      throw new Error(`Block "${blockId}" not found`);
    }

    const resolved = resolveParams(block, params);
    return block.steps.map((step) => interpolateStep(step, resolved));
  }

  /**
   * Register all builtin blocks (navigation, action, extract, validation).
   */
  registerBuiltins(): void {
    const builtins = [navigationBlock, actionBlock, extractBlock, validationBlock];
    for (const block of builtins) {
      if (!this.blocks.has(block.id)) {
        this.blocks.set(block.id, block);
      }
    }
  }
}

/**
 * Resolve parameters against block definition: validate required, apply defaults.
 */
function resolveParams(
  block: WorkflowBlock,
  params: Record<string, unknown>,
): Record<string, unknown> {
  const resolved: Record<string, unknown> = { ...params };

  for (const param of block.parameters) {
    if (resolved[param.name] === undefined) {
      if (param.required) {
        throw new Error(
          `Required parameter "${param.name}" missing for block "${block.id}"`,
        );
      }
      if (param.default !== undefined) {
        resolved[param.name] = param.default;
      }
    }
  }

  return resolved;
}

/**
 * Replace {{param.xxx}} placeholders in a string with resolved values.
 */
function interpolateString(template: string, params: Record<string, unknown>): string {
  return template.replace(/\{\{param\.(\w+)\}\}/g, (_, key) => {
    const val = params[key];
    return val !== undefined ? String(val) : '';
  });
}

/**
 * Recursively interpolate all string values in a value tree.
 */
function interpolateValue(value: unknown, params: Record<string, unknown>): unknown {
  if (typeof value === 'string') {
    return interpolateString(value, params);
  }
  if (Array.isArray(value)) {
    return value.map((item) => interpolateValue(item, params));
  }
  if (value !== null && typeof value === 'object') {
    const result: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      result[k] = interpolateValue(v, params);
    }
    return result;
  }
  return value;
}

/**
 * Interpolate param placeholders in a WorkflowStep's fields.
 */
function interpolateStep(
  step: WorkflowStep,
  params: Record<string, unknown>,
): WorkflowStep {
  const result: WorkflowStep = {
    ...step,
    id: interpolateString(step.id, params),
  };

  if (step.targetKey) {
    result.targetKey = interpolateString(step.targetKey, params);
  }

  if (step.args) {
    result.args = interpolateValue(step.args, params) as Record<string, unknown>;
  }

  if (step.expect) {
    result.expect = step.expect.map((e) => ({
      ...e,
      value: interpolateString(e.value, params),
    }));
  }

  return result;
}
