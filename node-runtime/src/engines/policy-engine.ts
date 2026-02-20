import type { Policy, PolicyCondition } from '../types/index.js';

function evaluateCondition(candidate: Record<string, unknown>, condition: PolicyCondition): boolean {
  const fieldValue = candidate[condition.field];

  switch (condition.op) {
    case '==':
      return fieldValue === condition.value;
    case '!=':
      return fieldValue !== condition.value;
    case '<':
      return (fieldValue as number) < (condition.value as number);
    case '<=':
      return (fieldValue as number) <= (condition.value as number);
    case '>':
      return (fieldValue as number) > (condition.value as number);
    case '>=':
      return (fieldValue as number) >= (condition.value as number);
    case 'in':
      return Array.isArray(condition.value) && condition.value.includes(fieldValue);
    case 'not_in':
      return Array.isArray(condition.value) && !condition.value.includes(fieldValue);
    case 'contains':
      return typeof fieldValue === 'string' && fieldValue.includes(String(condition.value));
    default:
      return false;
  }
}

function applyHardFilters(
  candidates: Record<string, unknown>[],
  hard: PolicyCondition[],
): Record<string, unknown>[] {
  return candidates.filter((candidate) =>
    hard.every((condition) => evaluateCondition(candidate, condition)),
  );
}

function scoreCandidate(candidate: Record<string, unknown>, policy: Policy): number {
  let total = 0;
  for (const rule of policy.score) {
    if (evaluateCondition(candidate, rule.when)) {
      total += rule.add;
    }
  }
  return total;
}

function parseTieBreak(tb: string): { field: string; order: 'asc' | 'desc' } {
  if (tb.endsWith('_asc')) return { field: tb.slice(0, -4), order: 'asc' };
  if (tb.endsWith('_desc')) return { field: tb.slice(0, -5), order: 'desc' };
  return { field: tb, order: 'asc' };
}

function applyTieBreak(
  candidates: { candidate: Record<string, unknown>; score: number }[],
  tieBreak: string[],
): { candidate: Record<string, unknown>; score: number }[] {
  return [...candidates].sort((a, b) => {
    // Primary sort by score (descending for argmax context)
    if (a.score !== b.score) return 0; // Scores are equal at this point (this is tie-breaking)

    for (const tb of tieBreak) {
      const { field, order } = parseTieBreak(tb);
      const aVal = a.candidate[field];
      const bVal = b.candidate[field];

      if (aVal === bVal) continue;

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return order === 'asc' ? aVal - bVal : bVal - aVal;
      }

      if (typeof aVal === 'string' && typeof bVal === 'string') {
        const cmp = aVal.localeCompare(bVal);
        return order === 'asc' ? cmp : -cmp;
      }
    }
    return 0;
  });
}

export function evaluatePolicy(
  candidates: Record<string, unknown>[],
  policy: Policy,
): Record<string, unknown> | null {
  if (candidates.length === 0) return null;

  // Step 1: Apply hard filters
  const filtered = applyHardFilters(candidates, policy.hard);
  if (filtered.length === 0) return null;

  // Step 2: Score remaining candidates
  const scored = filtered.map((candidate) => ({
    candidate,
    score: scoreCandidate(candidate, policy),
  }));

  // Step 3: Sort by score based on pick strategy
  if (policy.pick === 'argmax') {
    scored.sort((a, b) => b.score - a.score);
  } else if (policy.pick === 'argmin') {
    scored.sort((a, b) => a.score - b.score);
  }
  // 'first' keeps original order

  // Step 4: Among tied top scores, apply tie-break
  if (policy.pick !== 'first' && scored.length > 1) {
    const topScore = scored[0].score;
    const tied = scored.filter((s) => s.score === topScore);
    if (tied.length > 1 && policy.tie_break.length > 0) {
      const broken = applyTieBreak(tied, policy.tie_break);
      return broken[0].candidate;
    }
  }

  return scored[0].candidate;
}
