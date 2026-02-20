import { describe, it, expect, beforeEach } from 'vitest';
import { BlockRegistry } from '../../src/blocks/block-registry.js';
import type { WorkflowBlock } from '../../src/blocks/block-types.js';

describe('BlockRegistry', () => {
  let registry: BlockRegistry;

  const testBlock: WorkflowBlock = {
    id: 'test:hello',
    type: 'action',
    name: 'Test Block',
    description: 'A test block for unit testing',
    parameters: [
      { name: 'target', type: 'string', required: true, description: 'Target element' },
      { name: 'value', type: 'string', required: false, default: 'default-val', description: 'Value' },
      { name: 'count', type: 'number', required: false, default: 3 },
    ],
    steps: [
      {
        id: 'step-{{param.target}}',
        op: 'act_cached',
        targetKey: '{{param.target}}',
        args: { value: '{{param.value}}', count: '{{param.count}}' },
      },
    ],
  };

  beforeEach(() => {
    registry = new BlockRegistry();
  });

  describe('register', () => {
    it('registers a block', () => {
      registry.register(testBlock);
      expect(registry.get('test:hello')).toBeDefined();
    });

    it('throws on duplicate registration', () => {
      registry.register(testBlock);
      expect(() => registry.register(testBlock)).toThrow('already registered');
    });
  });

  describe('get', () => {
    it('returns registered block by ID', () => {
      registry.register(testBlock);
      const block = registry.get('test:hello');
      expect(block).toBeDefined();
      expect(block!.name).toBe('Test Block');
    });

    it('returns undefined for unknown ID', () => {
      expect(registry.get('nonexistent')).toBeUndefined();
    });
  });

  describe('getByType', () => {
    it('returns blocks filtered by type', () => {
      registry.register(testBlock);
      const navBlock: WorkflowBlock = {
        ...testBlock,
        id: 'test:nav',
        type: 'navigation',
        name: 'Nav Block',
      };
      registry.register(navBlock);

      const actions = registry.getByType('action');
      expect(actions).toHaveLength(1);
      expect(actions[0].id).toBe('test:hello');

      const navs = registry.getByType('navigation');
      expect(navs).toHaveLength(1);
      expect(navs[0].id).toBe('test:nav');
    });

    it('returns empty array for unknown type', () => {
      registry.register(testBlock);
      expect(registry.getByType('unknown')).toEqual([]);
    });
  });

  describe('list', () => {
    it('returns all registered blocks', () => {
      registry.register(testBlock);
      const another: WorkflowBlock = { ...testBlock, id: 'test:another' };
      registry.register(another);

      const all = registry.list();
      expect(all).toHaveLength(2);
    });

    it('returns empty array when no blocks registered', () => {
      expect(registry.list()).toEqual([]);
    });
  });

  describe('expandBlock', () => {
    it('expands step templates with provided params', () => {
      registry.register(testBlock);
      const steps = registry.expandBlock('test:hello', { target: 'submit-btn', value: 'Hello' });

      expect(steps).toHaveLength(1);
      expect(steps[0].id).toBe('step-submit-btn');
      expect(steps[0].targetKey).toBe('submit-btn');
      expect(steps[0].args!.value).toBe('Hello');
    });

    it('applies default values for missing optional params', () => {
      registry.register(testBlock);
      const steps = registry.expandBlock('test:hello', { target: 'my-target' });

      expect(steps[0].args!.value).toBe('default-val');
      expect(steps[0].args!.count).toBe('3');
    });

    it('throws for missing required parameter', () => {
      registry.register(testBlock);
      expect(() => registry.expandBlock('test:hello', {})).toThrow('Required parameter "target"');
    });

    it('throws for unknown block ID', () => {
      expect(() => registry.expandBlock('nonexistent', {})).toThrow('not found');
    });

    it('interpolates expect values', () => {
      const blockWithExpect: WorkflowBlock = {
        ...testBlock,
        id: 'test:expect',
        steps: [
          {
            id: 'validate',
            op: 'checkpoint',
            expect: [{ kind: 'text_contains', value: '{{param.target}}' }],
          },
        ],
      };
      registry.register(blockWithExpect);
      const steps = registry.expandBlock('test:expect', { target: 'success-text' });

      expect(steps[0].expect![0].value).toBe('success-text');
    });
  });

  describe('registerBuiltins', () => {
    it('registers all 4 builtin blocks', () => {
      registry.registerBuiltins();
      const all = registry.list();
      expect(all).toHaveLength(4);

      expect(registry.get('builtin:navigation')).toBeDefined();
      expect(registry.get('builtin:action')).toBeDefined();
      expect(registry.get('builtin:extract')).toBeDefined();
      expect(registry.get('builtin:validation')).toBeDefined();
    });

    it('does not duplicate on multiple calls', () => {
      registry.registerBuiltins();
      registry.registerBuiltins();
      expect(registry.list()).toHaveLength(4);
    });

    it('does not overwrite manually registered block with same ID', () => {
      const custom: WorkflowBlock = {
        id: 'builtin:navigation',
        type: 'navigation',
        name: 'Custom Nav',
        description: 'Custom override',
        parameters: [],
        steps: [],
      };
      registry.register(custom);
      registry.registerBuiltins();

      const nav = registry.get('builtin:navigation');
      expect(nav!.name).toBe('Custom Nav');
    });
  });
});
