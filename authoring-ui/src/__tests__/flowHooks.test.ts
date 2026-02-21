import { describe, it, expect } from 'vitest';
import { stepsToNodes, stepsToEdges } from '../hooks/useRecipeToFlow.ts';
import { nodesToStepOrder } from '../hooks/useFlowToRecipe.ts';
import type { WorkflowStep } from '../validation/schemas.ts';
import type { Node } from '@xyflow/react';

const sampleSteps: WorkflowStep[] = [
  { id: 'step-1', op: 'goto', args: { url: 'https://example.com' } },
  { id: 'step-2', op: 'act_cached', targetKey: 'click_btn' },
  { id: 'step-3', op: 'checkpoint', args: { message: 'Verify page' } },
  { id: 'step-4', op: 'extract', args: { scope: '.content' } },
  { id: 'step-5', op: 'wait', args: { ms: 2000 } },
];

describe('stepsToNodes', () => {
  it('converts steps to nodes with correct positions', () => {
    const nodes = stepsToNodes(sampleSteps, new Set());
    expect(nodes).toHaveLength(5);
    expect(nodes[0].id).toBe('step-1');
    expect(nodes[0].type).toBe('goto');
    expect(nodes[0].position).toEqual({ x: 0, y: 100 });
    expect(nodes[1].position).toEqual({ x: 280, y: 100 });
    expect(nodes[4].position).toEqual({ x: 1120, y: 100 });
  });

  it('sets node data with step reference', () => {
    const nodes = stepsToNodes(sampleSteps, new Set());
    expect(nodes[0].data.step).toBe(sampleSteps[0]);
    expect(nodes[0].data.hasError).toBe(false);
  });

  it('marks nodes with errors', () => {
    const errorIds = new Set(['step-2', 'step-4']);
    const nodes = stepsToNodes(sampleSteps, errorIds);
    expect(nodes[0].data.hasError).toBe(false);
    expect(nodes[1].data.hasError).toBe(true);
    expect(nodes[2].data.hasError).toBe(false);
    expect(nodes[3].data.hasError).toBe(true);
  });

  it('returns empty array for empty steps', () => {
    const nodes = stepsToNodes([], new Set());
    expect(nodes).toHaveLength(0);
  });

  it('assigns correct type based on op', () => {
    const nodes = stepsToNodes(sampleSteps, new Set());
    expect(nodes[0].type).toBe('goto');
    expect(nodes[1].type).toBe('act_cached');
    expect(nodes[2].type).toBe('checkpoint');
    expect(nodes[3].type).toBe('extract');
    expect(nodes[4].type).toBe('wait');
  });
});

describe('stepsToEdges', () => {
  it('creates edges between consecutive steps', () => {
    const edges = stepsToEdges(sampleSteps);
    expect(edges).toHaveLength(4);
    expect(edges[0].source).toBe('step-1');
    expect(edges[0].target).toBe('step-2');
    expect(edges[3].source).toBe('step-4');
    expect(edges[3].target).toBe('step-5');
  });

  it('uses smoothstep edge type', () => {
    const edges = stepsToEdges(sampleSteps);
    for (const edge of edges) {
      expect(edge.type).toBe('smoothstep');
    }
  });

  it('returns empty array for single step', () => {
    const edges = stepsToEdges([sampleSteps[0]]);
    expect(edges).toHaveLength(0);
  });

  it('returns empty array for empty steps', () => {
    const edges = stepsToEdges([]);
    expect(edges).toHaveLength(0);
  });
});

describe('nodesToStepOrder', () => {
  it('sorts nodes by x-position to determine order', () => {
    const nodes: Node[] = [
      { id: 'step-3', position: { x: 560, y: 100 }, data: {} },
      { id: 'step-1', position: { x: 0, y: 100 }, data: {} },
      { id: 'step-2', position: { x: 280, y: 100 }, data: {} },
    ];
    expect(nodesToStepOrder(nodes)).toEqual(['step-1', 'step-2', 'step-3']);
  });

  it('returns empty array for empty nodes', () => {
    expect(nodesToStepOrder([])).toEqual([]);
  });

  it('handles single node', () => {
    const nodes: Node[] = [
      { id: 'step-1', position: { x: 0, y: 100 }, data: {} },
    ];
    expect(nodesToStepOrder(nodes)).toEqual(['step-1']);
  });
});
