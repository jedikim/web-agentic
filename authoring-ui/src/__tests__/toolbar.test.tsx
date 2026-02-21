import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Toolbar } from '../components/Toolbar.tsx';
import { useRecipeStore } from '../store/recipeStore.ts';

// Mock the file-related utils to avoid DOM API issues in jsdom
vi.mock('../utils/importRecipe.ts', () => ({
  importFromFiles: vi.fn().mockResolvedValue({}),
}));

vi.mock('../utils/exportRecipe.ts', () => ({
  exportRecipeZip: vi.fn().mockResolvedValue(undefined),
}));

describe('Toolbar', () => {
  beforeEach(() => {
    useRecipeStore.getState().resetToDefault();
  });

  it('renders all step type buttons', () => {
    render(<Toolbar />);
    expect(screen.getByText('+ GOTO')).toBeInTheDocument();
    expect(screen.getByText('+ ACTION')).toBeInTheDocument();
    expect(screen.getByText('+ CHECK')).toBeInTheDocument();
    expect(screen.getByText('+ EXTRACT')).toBeInTheDocument();
    expect(screen.getByText('+ WAIT')).toBeInTheDocument();
  });

  it('renders recipe management buttons', () => {
    render(<Toolbar />);
    expect(screen.getByText('New Recipe')).toBeInTheDocument();
    expect(screen.getByText('Import...')).toBeInTheDocument();
    expect(screen.getByText('Export ZIP')).toBeInTheDocument();
  });

  it('clicking a step button adds a step to the store', () => {
    render(<Toolbar />);
    const initialCount = useRecipeStore.getState().workflow.steps.length;
    fireEvent.click(screen.getByText('+ GOTO'));
    expect(useRecipeStore.getState().workflow.steps.length).toBe(initialCount + 1);
    const newStep = useRecipeStore.getState().workflow.steps[initialCount];
    expect(newStep.op).toBe('goto');
  });

  it('clicking different step types adds correct ops', () => {
    render(<Toolbar />);
    fireEvent.click(screen.getByText('+ ACTION'));
    fireEvent.click(screen.getByText('+ WAIT'));

    const steps = useRecipeStore.getState().workflow.steps;
    expect(steps[steps.length - 2].op).toBe('act_cached');
    expect(steps[steps.length - 1].op).toBe('wait');
  });

  it('New Recipe button resets to default', () => {
    useRecipeStore.getState().addStep({ id: 'extra', op: 'wait' });
    expect(useRecipeStore.getState().workflow.steps.length).toBe(2);

    render(<Toolbar />);
    fireEvent.click(screen.getByText('New Recipe'));
    expect(useRecipeStore.getState().workflow.steps.length).toBe(1);
  });
});
