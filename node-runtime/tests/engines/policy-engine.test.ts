import { describe, it, expect } from 'vitest';
import { evaluatePolicy } from '../../src/engines/policy-engine.js';
import type { Policy } from '../../src/types/index.js';

describe('evaluatePolicy', () => {
  const seatPolicy: Policy = {
    hard: [{ field: 'available', op: '==', value: true }],
    score: [
      { when: { field: 'zone', op: '==', value: 'front' }, add: 30 },
      { when: { field: 'price', op: '<=', value: 100 }, add: 20 },
    ],
    tie_break: ['price_asc', 'label_asc'],
    pick: 'argmax',
  };

  it('returns null for empty candidates', () => {
    expect(evaluatePolicy([], seatPolicy)).toBeNull();
  });

  it('filters out candidates that fail hard conditions', () => {
    const candidates = [
      { id: 'A', available: false, zone: 'front', price: 50, label: 'A1' },
      { id: 'B', available: true, zone: 'back', price: 80, label: 'B1' },
    ];

    const result = evaluatePolicy(candidates, seatPolicy);
    expect(result?.id).toBe('B');
  });

  it('returns null when all candidates fail hard filter', () => {
    const candidates = [
      { id: 'A', available: false, zone: 'front', price: 50 },
      { id: 'B', available: false, zone: 'back', price: 80 },
    ];

    expect(evaluatePolicy(candidates, seatPolicy)).toBeNull();
  });

  it('picks highest scoring candidate (argmax)', () => {
    const candidates = [
      { id: 'A', available: true, zone: 'back', price: 50, label: 'A1' },   // score: 0 + 20 = 20
      { id: 'B', available: true, zone: 'front', price: 50, label: 'B1' },  // score: 30 + 20 = 50
      { id: 'C', available: true, zone: 'front', price: 150, label: 'C1' }, // score: 30 + 0 = 30
    ];

    const result = evaluatePolicy(candidates, seatPolicy);
    expect(result?.id).toBe('B');
  });

  it('applies tie-break when scores are equal', () => {
    const candidates = [
      { id: 'A', available: true, zone: 'front', price: 80, label: 'Z' },  // score: 30 + 20 = 50
      { id: 'B', available: true, zone: 'front', price: 60, label: 'A' },  // score: 30 + 20 = 50
    ];

    const result = evaluatePolicy(candidates, seatPolicy);
    // Both score 50, tie-break by price_asc: B (60) < A (80)
    expect(result?.id).toBe('B');
  });

  it('applies second tie-break when first is equal', () => {
    const candidates = [
      { id: 'A', available: true, zone: 'front', price: 60, label: 'Z' },
      { id: 'B', available: true, zone: 'front', price: 60, label: 'A' },
    ];

    const result = evaluatePolicy(candidates, seatPolicy);
    // Same score, same price -> label_asc: A < Z, so B wins
    expect(result?.id).toBe('B');
  });

  it('supports argmin pick strategy', () => {
    const policy: Policy = {
      hard: [],
      score: [{ when: { field: 'distance', op: '>', value: 0 }, add: 10 }],
      tie_break: [],
      pick: 'argmin',
    };

    const candidates = [
      { id: 'A', distance: 100 }, // score: 10
      { id: 'B', distance: 0 },   // score: 0
      { id: 'C', distance: 50 },  // score: 10
    ];

    const result = evaluatePolicy(candidates, policy);
    expect(result?.id).toBe('B');
  });

  it('supports first pick strategy (preserves order)', () => {
    const policy: Policy = {
      hard: [{ field: 'valid', op: '==', value: true }],
      score: [],
      tie_break: [],
      pick: 'first',
    };

    const candidates = [
      { id: 'A', valid: true },
      { id: 'B', valid: true },
      { id: 'C', valid: true },
    ];

    const result = evaluatePolicy(candidates, policy);
    expect(result?.id).toBe('A');
  });

  it('supports != operator', () => {
    const policy: Policy = {
      hard: [{ field: 'status', op: '!=', value: 'sold' }],
      score: [],
      tie_break: [],
      pick: 'first',
    };

    const candidates = [
      { id: 'A', status: 'sold' },
      { id: 'B', status: 'available' },
    ];

    const result = evaluatePolicy(candidates, policy);
    expect(result?.id).toBe('B');
  });

  it('supports comparison operators', () => {
    const policy: Policy = {
      hard: [
        { field: 'price', op: '>=', value: 10 },
        { field: 'price', op: '<', value: 100 },
      ],
      score: [],
      tie_break: [],
      pick: 'first',
    };

    const candidates = [
      { id: 'A', price: 5 },
      { id: 'B', price: 50 },
      { id: 'C', price: 150 },
    ];

    const result = evaluatePolicy(candidates, policy);
    expect(result?.id).toBe('B');
  });

  it('supports in operator', () => {
    const policy: Policy = {
      hard: [{ field: 'zone', op: 'in', value: ['front', 'middle'] }],
      score: [],
      tie_break: [],
      pick: 'first',
    };

    const candidates = [
      { id: 'A', zone: 'back' },
      { id: 'B', zone: 'middle' },
    ];

    const result = evaluatePolicy(candidates, policy);
    expect(result?.id).toBe('B');
  });

  it('supports not_in operator', () => {
    const policy: Policy = {
      hard: [{ field: 'zone', op: 'not_in', value: ['back'] }],
      score: [],
      tie_break: [],
      pick: 'first',
    };

    const candidates = [
      { id: 'A', zone: 'back' },
      { id: 'B', zone: 'front' },
    ];

    const result = evaluatePolicy(candidates, policy);
    expect(result?.id).toBe('B');
  });

  it('supports contains operator', () => {
    const policy: Policy = {
      hard: [{ field: 'name', op: 'contains', value: 'VIP' }],
      score: [],
      tie_break: [],
      pick: 'first',
    };

    const candidates = [
      { id: 'A', name: 'Regular seat' },
      { id: 'B', name: 'VIP seat' },
    ];

    const result = evaluatePolicy(candidates, policy);
    expect(result?.id).toBe('B');
  });

  it('handles complex real-world scenario', () => {
    const policy: Policy = {
      hard: [
        { field: 'available', op: '==', value: true },
        { field: 'price', op: '<=', value: 200 },
      ],
      score: [
        { when: { field: 'zone', op: '==', value: 'VIP' }, add: 50 },
        { when: { field: 'zone', op: '==', value: 'front' }, add: 30 },
        { when: { field: 'price', op: '<=', value: 100 }, add: 20 },
        { when: { field: 'rating', op: '>=', value: 4 }, add: 10 },
      ],
      tie_break: ['price_asc'],
      pick: 'argmax',
    };

    const candidates = [
      { id: 'S1', available: true, zone: 'VIP', price: 250, rating: 5 },    // Hard filtered (price > 200)
      { id: 'S2', available: true, zone: 'VIP', price: 180, rating: 5 },    // 50 + 0 + 10 = 60
      { id: 'S3', available: true, zone: 'front', price: 90, rating: 4 },   // 30 + 20 + 10 = 60
      { id: 'S4', available: true, zone: 'front', price: 80, rating: 3 },   // 30 + 20 + 0 = 50
      { id: 'S5', available: false, zone: 'VIP', price: 50, rating: 5 },    // Hard filtered (not available)
    ];

    const result = evaluatePolicy(candidates, policy);
    // S2 and S3 both score 60, tie-break by price_asc: S3 (90) < S2 (180)
    expect(result?.id).toBe('S3');
  });
});
