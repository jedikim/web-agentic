import type { WorkflowBlock } from '../block-types.js';

/**
 * Extract block: Extract structured data with schema validation and scope narrowing.
 */
export const extractBlock: WorkflowBlock = {
  id: 'builtin:extract',
  type: 'extract',
  name: 'Extract Data with Schema',
  description: 'Extract structured data from the page using a schema, optionally scoped to a CSS selector, and store in a variable.',
  parameters: [
    {
      name: 'targetKey',
      type: 'string',
      required: true,
      description: 'Target key for extraction',
    },
    {
      name: 'schema',
      type: 'string',
      required: true,
      description: 'JSON schema describing the data to extract',
    },
    {
      name: 'scope',
      type: 'selector',
      required: false,
      description: 'CSS selector to narrow extraction scope',
    },
    {
      name: 'into',
      type: 'string',
      required: true,
      description: 'Variable name to store extracted data',
    },
  ],
  steps: [
    {
      id: 'extract-data',
      op: 'extract',
      targetKey: '{{param.targetKey}}',
      args: {
        schema: '{{param.schema}}',
        scope: '{{param.scope}}',
        into: '{{param.into}}',
      },
    },
  ],
};
