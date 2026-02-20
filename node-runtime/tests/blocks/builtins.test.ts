import { describe, it, expect } from 'vitest';
import { BlockRegistry } from '../../src/blocks/block-registry.js';
import { navigationBlock } from '../../src/blocks/builtins/navigation.block.js';
import { actionBlock } from '../../src/blocks/builtins/action.block.js';
import { extractBlock } from '../../src/blocks/builtins/extract.block.js';
import { validationBlock } from '../../src/blocks/builtins/validation.block.js';

describe('Builtin Blocks', () => {
  describe('navigation block', () => {
    it('has correct metadata', () => {
      expect(navigationBlock.id).toBe('builtin:navigation');
      expect(navigationBlock.type).toBe('navigation');
      expect(navigationBlock.parameters.find((p) => p.name === 'url')?.required).toBe(true);
      expect(navigationBlock.parameters.find((p) => p.name === 'waitFor')?.required).toBe(false);
      expect(navigationBlock.parameters.find((p) => p.name === 'fingerprint')?.required).toBe(false);
    });

    it('has goto step with url placeholder', () => {
      expect(navigationBlock.steps[0].op).toBe('goto');
      expect(navigationBlock.steps[0].args!.url).toBe('{{param.url}}');
    });

    it('expands with URL parameter', () => {
      const registry = new BlockRegistry();
      registry.register(navigationBlock);
      const steps = registry.expandBlock('builtin:navigation', {
        url: 'https://example.com/login',
        waitFor: '#main',
        fingerprint: 'Dashboard',
      });

      expect(steps[0].args!.url).toBe('https://example.com/login');
      expect(steps[1].args!.selector).toBe('#main');
      expect(steps[2].expect![0].value).toBe('Dashboard');
    });

    it('throws when url is missing', () => {
      const registry = new BlockRegistry();
      registry.register(navigationBlock);
      expect(() => registry.expandBlock('builtin:navigation', {})).toThrow('Required parameter "url"');
    });
  });

  describe('action block', () => {
    it('has correct metadata', () => {
      expect(actionBlock.id).toBe('builtin:action');
      expect(actionBlock.type).toBe('action');
      expect(actionBlock.parameters.find((p) => p.name === 'targetKey')?.required).toBe(true);
      expect(actionBlock.parameters.find((p) => p.name === 'method')?.default).toBe('click');
      expect(actionBlock.parameters.find((p) => p.name === 'maxRetries')?.default).toBe(2);
    });

    it('has act_cached step with fallback', () => {
      expect(actionBlock.steps[0].op).toBe('act_cached');
      expect(actionBlock.steps[0].onFail).toBe('fallback');
      expect(actionBlock.steps[1].op).toBe('act_template');
      expect(actionBlock.steps[1].onFail).toBe('abort');
    });

    it('expands with targetKey and defaults', () => {
      const registry = new BlockRegistry();
      registry.register(actionBlock);
      const steps = registry.expandBlock('builtin:action', { targetKey: 'submit-button' });

      expect(steps[0].targetKey).toBe('submit-button');
      expect(steps[0].args!.method).toBe('click');
      expect(steps[0].args!.value).toBe('');
      expect(steps[0].args!.maxRetries).toBe('2');
    });

    it('expands with custom method and value', () => {
      const registry = new BlockRegistry();
      registry.register(actionBlock);
      const steps = registry.expandBlock('builtin:action', {
        targetKey: 'email-input',
        method: 'fill',
        value: 'test@example.com',
        maxRetries: 3,
      });

      expect(steps[0].args!.method).toBe('fill');
      expect(steps[0].args!.value).toBe('test@example.com');
      expect(steps[0].args!.maxRetries).toBe('3');
    });
  });

  describe('extract block', () => {
    it('has correct metadata', () => {
      expect(extractBlock.id).toBe('builtin:extract');
      expect(extractBlock.type).toBe('extract');
      expect(extractBlock.parameters.find((p) => p.name === 'targetKey')?.required).toBe(true);
      expect(extractBlock.parameters.find((p) => p.name === 'schema')?.required).toBe(true);
      expect(extractBlock.parameters.find((p) => p.name === 'into')?.required).toBe(true);
      expect(extractBlock.parameters.find((p) => p.name === 'scope')?.required).toBe(false);
    });

    it('has extract step', () => {
      expect(extractBlock.steps[0].op).toBe('extract');
    });

    it('expands with schema and scope', () => {
      const registry = new BlockRegistry();
      registry.register(extractBlock);
      const steps = registry.expandBlock('builtin:extract', {
        targetKey: 'product-list',
        schema: '{"type":"array","items":{"type":"object"}}',
        scope: '.product-grid',
        into: 'products',
      });

      expect(steps[0].targetKey).toBe('product-list');
      expect(steps[0].args!.schema).toBe('{"type":"array","items":{"type":"object"}}');
      expect(steps[0].args!.scope).toBe('.product-grid');
      expect(steps[0].args!.into).toBe('products');
    });

    it('throws when required params are missing', () => {
      const registry = new BlockRegistry();
      registry.register(extractBlock);
      expect(() => registry.expandBlock('builtin:extract', { targetKey: 'x' })).toThrow(
        'Required parameter "schema"',
      );
    });
  });

  describe('validation block', () => {
    it('has correct metadata', () => {
      expect(validationBlock.id).toBe('builtin:validation');
      expect(validationBlock.type).toBe('validation');
      expect(validationBlock.parameters.find((p) => p.name === 'expectations')?.required).toBe(true);
      expect(validationBlock.parameters.find((p) => p.name === 'screenshotOnFail')?.default).toBe(true);
    });

    it('has checkpoint step', () => {
      expect(validationBlock.steps[0].op).toBe('checkpoint');
    });

    it('expands with expectations', () => {
      const registry = new BlockRegistry();
      registry.register(validationBlock);
      const expectations = JSON.stringify([
        { kind: 'url_contains', value: '/dashboard' },
        { kind: 'selector_visible', value: '#welcome' },
      ]);
      const steps = registry.expandBlock('builtin:validation', { expectations });

      expect(steps[0].args!.expectations).toBe(expectations);
      expect(steps[0].args!.screenshotOnFail).toBe('true');
    });

    it('allows disabling screenshotOnFail', () => {
      const registry = new BlockRegistry();
      registry.register(validationBlock);
      const steps = registry.expandBlock('builtin:validation', {
        expectations: '[]',
        screenshotOnFail: false,
      });

      expect(steps[0].args!.screenshotOnFail).toBe('false');
    });
  });
});
