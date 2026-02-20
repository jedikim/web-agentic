export interface TokenBudget {
  maxLlmCallsPerRun: number;
  maxPromptChars: number;
  maxDomSnippetChars: number;
  maxScreenshotPerFailure: number;
  maxScreenshotPerCheckpoint: number;
  maxAuthoringServiceCallsPerRun: number;
  authoringServiceTimeoutMs: number;
}

export type DowngradeAction = 'trim_dom' | 'drop_history' | 'observe_scope_narrow' | 'require_human_checkpoint';

export interface BudgetConfig {
  budget: TokenBudget;
  downgradeOrder: DowngradeAction[];
}

export interface BudgetUsage {
  llmCalls: number;
  authoringCalls: number;
  promptChars: number;
  screenshots: number;
}
