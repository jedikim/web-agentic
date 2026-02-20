import type { WorkflowBlock } from '../block-types.js';

/**
 * Navigation block: Navigate to URL, optionally wait for selector and check fingerprint.
 */
export const navigationBlock: WorkflowBlock = {
  id: 'builtin:navigation',
  type: 'navigation',
  name: 'Navigate to URL',
  description: 'Navigate to a URL, optionally wait for a selector and verify page fingerprint.',
  parameters: [
    {
      name: 'url',
      type: 'url',
      required: true,
      description: 'The URL to navigate to',
    },
    {
      name: 'waitFor',
      type: 'selector',
      required: false,
      description: 'CSS selector to wait for after navigation',
    },
    {
      name: 'fingerprint',
      type: 'string',
      required: false,
      description: 'Expected page fingerprint text to verify correct page',
    },
  ],
  steps: [
    {
      id: 'nav-goto',
      op: 'goto',
      args: { url: '{{param.url}}' },
    },
    {
      id: 'nav-wait',
      op: 'wait',
      args: { selector: '{{param.waitFor}}' },
    },
    {
      id: 'nav-fingerprint',
      op: 'extract',
      args: { fingerprint: '{{param.fingerprint}}' },
      expect: [
        { kind: 'text_contains', value: '{{param.fingerprint}}' },
      ],
    },
  ],
};
