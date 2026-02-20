import type { WorkflowBlock } from '../block-types.js';

/**
 * Action block: Perform an action with retry and fallback support.
 */
export const actionBlock: WorkflowBlock = {
  id: 'builtin:action',
  type: 'action',
  name: 'Perform Action with Retry',
  description: 'Execute a cached action on a target, with configurable retry and fallback on failure.',
  parameters: [
    {
      name: 'targetKey',
      type: 'string',
      required: true,
      description: 'The target key for the action (maps to actions.json)',
    },
    {
      name: 'method',
      type: 'string',
      required: false,
      default: 'click',
      description: 'Action method: click, fill, or type',
    },
    {
      name: 'value',
      type: 'string',
      required: false,
      default: '',
      description: 'Value to use for fill/type actions',
    },
    {
      name: 'maxRetries',
      type: 'number',
      required: false,
      default: 2,
      description: 'Maximum number of retries on failure',
    },
  ],
  steps: [
    {
      id: 'action-exec',
      op: 'act_cached',
      targetKey: '{{param.targetKey}}',
      args: {
        method: '{{param.method}}',
        value: '{{param.value}}',
        maxRetries: '{{param.maxRetries}}',
      },
      onFail: 'fallback',
    },
    {
      id: 'action-fallback',
      op: 'act_template',
      targetKey: '{{param.targetKey}}',
      args: {
        method: '{{param.method}}',
        value: '{{param.value}}',
      },
      onFail: 'abort',
    },
  ],
};
