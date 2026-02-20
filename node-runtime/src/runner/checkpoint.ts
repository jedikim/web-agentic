export type CheckpointDecision = 'GO' | 'NOT_GO';

export interface CheckpointHandler {
  requestApproval(message: string, screenshot?: Buffer): Promise<CheckpointDecision>;
}

export class DefaultCheckpointHandler implements CheckpointHandler {
  private handler: (message: string, screenshot?: Buffer) => Promise<CheckpointDecision>;

  constructor(handler?: (message: string, screenshot?: Buffer) => Promise<CheckpointDecision>) {
    this.handler = handler ?? (async () => 'NOT_GO');
  }

  async requestApproval(message: string, screenshot?: Buffer): Promise<CheckpointDecision> {
    return this.handler(message, screenshot);
  }
}

export class AutoApproveCheckpointHandler implements CheckpointHandler {
  async requestApproval(_message: string, _screenshot?: Buffer): Promise<CheckpointDecision> {
    return 'GO';
  }
}
