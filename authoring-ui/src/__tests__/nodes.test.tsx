import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ReactFlowProvider } from '@xyflow/react';
import { GotoNode } from '../nodes/GotoNode.tsx';
import { ActCachedNode } from '../nodes/ActCachedNode.tsx';
import { CheckpointNode } from '../nodes/CheckpointNode.tsx';
import { ExtractNode } from '../nodes/ExtractNode.tsx';
import { WaitNode } from '../nodes/WaitNode.tsx';
import type { NodeProps, Node } from '@xyflow/react';

// Mock ResizeObserver needed by React Flow handles
vi.stubGlobal('ResizeObserver', vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
})));

function makeProps<T extends Record<string, unknown>>(data: T): NodeProps<Node<T>> {
  return {
    id: 'test-node',
    data,
    type: 'goto',
    selected: false,
    isConnectable: true,
    zIndex: 0,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    dragging: false,
    deletable: true,
    selectable: true,
    parentId: undefined,
    dragHandle: undefined,
    sourcePosition: undefined,
    targetPosition: undefined,
    width: 200,
    height: 60,
  } as unknown as NodeProps<Node<T>>;
}

function renderWithProvider(ui: React.ReactElement) {
  return render(<ReactFlowProvider>{ui}</ReactFlowProvider>);
}

describe('GotoNode', () => {
  it('renders with URL', () => {
    const props = makeProps({
      step: { id: 's1', op: 'goto' as const, args: { url: 'https://example.com' } },
      hasError: false,
    });
    renderWithProvider(<GotoNode {...props} />);
    expect(screen.getByText('GOTO')).toBeInTheDocument();
    expect(screen.getByText('https://example.com')).toBeInTheDocument();
  });

  it('renders without URL', () => {
    const props = makeProps({
      step: { id: 's1', op: 'goto' as const, args: null },
      hasError: false,
    });
    renderWithProvider(<GotoNode {...props} />);
    expect(screen.getByText('(no url)')).toBeInTheDocument();
  });
});

describe('ActCachedNode', () => {
  it('renders with targetKey', () => {
    const props = makeProps({
      step: { id: 's1', op: 'act_cached' as const, targetKey: 'click_login' },
      hasError: false,
    });
    renderWithProvider(<ActCachedNode {...props} />);
    expect(screen.getByText('ACTION')).toBeInTheDocument();
    expect(screen.getByText('click_login')).toBeInTheDocument();
  });
});

describe('CheckpointNode', () => {
  it('renders with message', () => {
    const props = makeProps({
      step: { id: 's1', op: 'checkpoint' as const, args: { message: 'Check page loaded' } },
      hasError: false,
    });
    renderWithProvider(<CheckpointNode {...props} />);
    expect(screen.getByText('CHECK')).toBeInTheDocument();
    expect(screen.getByText('Check page loaded')).toBeInTheDocument();
  });
});

describe('ExtractNode', () => {
  it('renders with scope', () => {
    const props = makeProps({
      step: { id: 's1', op: 'extract' as const, args: { scope: '.main' } },
      hasError: false,
    });
    renderWithProvider(<ExtractNode {...props} />);
    expect(screen.getByText('EXTRACT')).toBeInTheDocument();
    expect(screen.getByText('.main')).toBeInTheDocument();
  });

  it('renders full page when no scope', () => {
    const props = makeProps({
      step: { id: 's1', op: 'extract' as const, args: null },
      hasError: false,
    });
    renderWithProvider(<ExtractNode {...props} />);
    expect(screen.getByText('full page')).toBeInTheDocument();
  });
});

describe('WaitNode', () => {
  it('renders with duration', () => {
    const props = makeProps({
      step: { id: 's1', op: 'wait' as const, args: { ms: 3000 } },
      hasError: false,
    });
    renderWithProvider(<WaitNode {...props} />);
    expect(screen.getByText('WAIT')).toBeInTheDocument();
    expect(screen.getByText('3000ms')).toBeInTheDocument();
  });
});
