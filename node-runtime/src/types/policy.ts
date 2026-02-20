export interface PolicyCondition {
  field: string;
  op: '==' | '!=' | '<' | '<=' | '>' | '>=' | 'in' | 'not_in' | 'contains';
  value: unknown;
}

export interface PolicyScoreRule {
  when: PolicyCondition;
  add: number;
}

export interface Policy {
  hard: PolicyCondition[];
  score: PolicyScoreRule[];
  tie_break: string[];
  pick: 'argmax' | 'argmin' | 'first';
}

export type PoliciesMap = Record<string, Policy>;
