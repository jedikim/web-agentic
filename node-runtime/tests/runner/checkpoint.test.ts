import { describe, it, expect, vi } from 'vitest';
import {
  DefaultCheckpointHandler,
  AutoApproveCheckpointHandler,
} from '../../src/runner/checkpoint.js';

describe('DefaultCheckpointHandler', () => {
  it('defaults to NOT_GO when no handler provided', async () => {
    const handler = new DefaultCheckpointHandler();
    const result = await handler.requestApproval('Proceed?');
    expect(result).toBe('NOT_GO');
  });

  it('delegates to custom handler', async () => {
    const customHandler = vi.fn().mockResolvedValue('GO');
    const handler = new DefaultCheckpointHandler(customHandler);

    const screenshot = Buffer.from('png');
    const result = await handler.requestApproval('Proceed?', screenshot);
    expect(result).toBe('GO');
    expect(customHandler).toHaveBeenCalledWith('Proceed?', screenshot);
  });

  it('passes message and screenshot to handler', async () => {
    const customHandler = vi.fn().mockResolvedValue('NOT_GO');
    const handler = new DefaultCheckpointHandler(customHandler);

    await handler.requestApproval('Review this step', Buffer.from('image'));
    expect(customHandler).toHaveBeenCalledWith('Review this step', Buffer.from('image'));
  });
});

describe('AutoApproveCheckpointHandler', () => {
  it('always returns GO', async () => {
    const handler = new AutoApproveCheckpointHandler();
    expect(await handler.requestApproval('Anything')).toBe('GO');
    expect(await handler.requestApproval('Critical step', Buffer.from('img'))).toBe('GO');
  });
});
