export interface ActionRef {
  selector: string;
  description: string;
  method: 'click' | 'fill' | 'type' | 'press' | string;
  arguments?: string[];
}

export interface ActionEntry {
  instruction: string;
  preferred: ActionRef;
  observedAt: string;
}

export type ActionsMap = Record<string, ActionEntry>;
