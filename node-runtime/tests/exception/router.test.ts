import { describe, it, expect } from 'vitest';
import { routeError } from '../../src/exception/router.js';
import type { RecoveryAction } from '../../src/exception/router.js';

describe('routeError', () => {
  it('routes TargetNotFound with observe refresh and selector fallback', () => {
    const actions = routeError('TargetNotFound');
    expect(actions).toContain('retry');
    expect(actions).toContain('observe_refresh');
    expect(actions).toContain('selector_fallback');
    expect(actions).toContain('healing_memory');
    expect(actions).toContain('authoring_patch');
    expect(actions).toContain('checkpoint');
    // retry should come first
    expect(actions[0]).toBe('retry');
  });

  it('routes NotActionable with retry first', () => {
    const actions = routeError('NotActionable');
    expect(actions[0]).toBe('retry');
    expect(actions).toContain('selector_fallback');
    expect(actions).toContain('observe_refresh');
    expect(actions).toContain('authoring_patch');
    expect(actions).toContain('checkpoint');
  });

  it('routes ExpectationFailed with retry then observe and patch', () => {
    const actions = routeError('ExpectationFailed');
    expect(actions[0]).toBe('retry');
    expect(actions).toContain('observe_refresh');
    expect(actions).toContain('authoring_patch');
    expect(actions).toContain('checkpoint');
    // Should NOT include selector_fallback for expectation failures
    expect(actions).not.toContain('selector_fallback');
  });

  it('routes ExtractionEmpty with scope readjustment path', () => {
    const actions = routeError('ExtractionEmpty');
    expect(actions).toContain('retry');
    expect(actions).toContain('observe_refresh');
    expect(actions).toContain('selector_fallback');
    expect(actions).toContain('authoring_patch');
  });

  it('routes CanvasDetected through canvas chain: network_parse -> cv_coordinate -> canvas_llm_fallback', () => {
    const actions = routeError('CanvasDetected');
    expect(actions).not.toContain('retry');
    expect(actions).toContain('network_parse');
    expect(actions).toContain('cv_coordinate');
    expect(actions).toContain('canvas_llm_fallback');
    expect(actions).toContain('checkpoint');
    // Order: network_parse (free) -> cv_coordinate (cheap) -> canvas_llm_fallback (expensive)
    const npIdx = actions.indexOf('network_parse');
    const cvIdx = actions.indexOf('cv_coordinate');
    const llmIdx = actions.indexOf('canvas_llm_fallback');
    expect(npIdx).toBeLessThan(cvIdx);
    expect(cvIdx).toBeLessThan(llmIdx);
  });

  it('routes CaptchaOr2FA directly to checkpoint and abort only', () => {
    const actions = routeError('CaptchaOr2FA');
    expect(actions).toEqual(['checkpoint', 'abort']);
  });

  it('routes AuthoringServiceTimeout to checkpoint and abort', () => {
    const actions = routeError('AuthoringServiceTimeout');
    expect(actions).toEqual(['checkpoint', 'abort']);
  });

  it('returns actions in priority order for TargetNotFound', () => {
    const actions = routeError('TargetNotFound');
    const retryIdx = actions.indexOf('retry');
    const observeIdx = actions.indexOf('observe_refresh');
    const selectorIdx = actions.indexOf('selector_fallback');
    const healingIdx = actions.indexOf('healing_memory');
    const patchIdx = actions.indexOf('authoring_patch');
    const checkpointIdx = actions.indexOf('checkpoint');

    expect(retryIdx).toBeLessThan(observeIdx);
    expect(observeIdx).toBeLessThan(selectorIdx);
    expect(selectorIdx).toBeLessThan(healingIdx);
    expect(healingIdx).toBeLessThan(patchIdx);
    expect(patchIdx).toBeLessThan(checkpointIdx);
  });

  it('all routes end with checkpoint or abort', () => {
    const errorTypes = [
      'TargetNotFound',
      'NotActionable',
      'ExpectationFailed',
      'ExtractionEmpty',
      'CanvasDetected',
      'CaptchaOr2FA',
      'AuthoringServiceTimeout',
    ] as const;

    for (const errorType of errorTypes) {
      const actions = routeError(errorType);
      const last = actions[actions.length - 1];
      expect(
        last === 'checkpoint' || last === 'abort',
        `${errorType} should end with checkpoint or abort, got ${last}`
      ).toBe(true);
    }
  });
});
