import type { WorkflowBlock } from '../block-types.js';

/**
 * Validation block: Run multiple expectations and optionally screenshot on failure.
 */
export const validationBlock: WorkflowBlock = {
  id: 'builtin:validation',
  type: 'validation',
  name: 'Validate Expectations',
  description: 'Validate multiple expectations against the current page state, with optional screenshot on failure.',
  parameters: [
    {
      name: 'expectations',
      type: 'string',
      required: true,
      description: 'JSON-encoded array of Expectation objects to validate',
    },
    {
      name: 'screenshotOnFail',
      type: 'boolean',
      required: false,
      default: true,
      description: 'Whether to take a screenshot when validation fails',
    },
  ],
  steps: [
    {
      id: 'validate-expectations',
      op: 'checkpoint',
      args: {
        expectations: '{{param.expectations}}',
        screenshotOnFail: '{{param.screenshotOnFail}}',
      },
    },
  ],
};
