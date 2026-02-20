import { describe, it, expect } from 'vitest';
import { classifyError } from '../../src/exception/classifier.js';

describe('classifyError', () => {
  describe('TargetNotFound', () => {
    it('classifies timeout errors with selector context', () => {
      const error = new Error('Timeout 30000ms exceeded waiting for selector "#submit"');
      expect(classifyError(error, { selector: '#submit' })).toBe('TargetNotFound');
    });

    it('classifies locator timeout errors', () => {
      const error = new Error('Timeout waiting for locator("button.login")');
      expect(classifyError(error, { selector: 'button.login' })).toBe('TargetNotFound');
    });

    it('classifies element not found errors', () => {
      const error = new Error('No element found for selector: .missing-button');
      expect(classifyError(error, { selector: '.missing-button' })).toBe('TargetNotFound');
    });

    it('classifies strict mode violation', () => {
      const error = new Error('strict mode violation: locator resolved to 3 elements');
      expect(classifyError(error)).toBe('TargetNotFound');
    });
  });

  describe('NotActionable', () => {
    it('classifies not clickable errors', () => {
      const error = new Error('Element is not clickable at point (100, 200)');
      expect(classifyError(error)).toBe('NotActionable');
    });

    it('classifies element not visible errors', () => {
      const error = new Error('Element is not visible');
      expect(classifyError(error)).toBe('NotActionable');
    });

    it('classifies intercepted click errors', () => {
      const error = new Error('Element click intercepted by another element');
      expect(classifyError(error)).toBe('NotActionable');
    });

    it('classifies pointer-events none errors', () => {
      const error = new Error('Element has pointer-events: none');
      expect(classifyError(error)).toBe('NotActionable');
    });
  });

  describe('ExpectationFailed', () => {
    it('classifies assertion failures', () => {
      const error = new Error('Assertion failed: expected URL to contain /dashboard');
      expect(classifyError(error)).toBe('ExpectationFailed');
    });

    it('classifies url mismatch', () => {
      const error = new Error('url does not contain expected path');
      expect(classifyError(error)).toBe('ExpectationFailed');
    });
  });

  describe('ExtractionEmpty', () => {
    it('classifies empty extraction results', () => {
      const error = new Error('Extraction empty: no data found');
      expect(classifyError(error)).toBe('ExtractionEmpty');
    });

    it('classifies extract returned null', () => {
      const error = new Error('extract returned null for schema');
      expect(classifyError(error)).toBe('ExtractionEmpty');
    });
  });

  describe('CanvasDetected', () => {
    it('classifies canvas element detection', () => {
      const error = new Error('Target is a canvas element, cannot interact normally');
      expect(classifyError(error)).toBe('CanvasDetected');
    });

    it('classifies webgl context errors', () => {
      const error = new Error('WebGL rendering context detected');
      expect(classifyError(error)).toBe('CanvasDetected');
    });
  });

  describe('CaptchaOr2FA', () => {
    it('classifies captcha detection', () => {
      const error = new Error('Captcha detected on page');
      expect(classifyError(error)).toBe('CaptchaOr2FA');
    });

    it('classifies recaptcha', () => {
      const error = new Error('reCAPTCHA challenge appeared');
      expect(classifyError(error)).toBe('CaptchaOr2FA');
    });

    it('classifies 2FA', () => {
      const error = new Error('Two-factor authentication required');
      expect(classifyError(error)).toBe('CaptchaOr2FA');
    });

    it('classifies verification code requests', () => {
      const error = new Error('Please enter verification code');
      expect(classifyError(error)).toBe('CaptchaOr2FA');
    });
  });

  describe('AuthoringServiceTimeout', () => {
    it('classifies authoring service timeout', () => {
      const error = new Error('Authoring service request timed out');
      expect(classifyError(error)).toBe('AuthoringServiceTimeout');
    });

    it('classifies authoring timeout from context message', () => {
      const error = new Error('Request timeout');
      expect(classifyError(error, { message: 'authoring service call timed out' })).toBe('AuthoringServiceTimeout');
    });
  });

  describe('defaults', () => {
    it('defaults to TargetNotFound when selector context is present', () => {
      const error = new Error('Some unknown error');
      expect(classifyError(error, { selector: '#btn' })).toBe('TargetNotFound');
    });

    it('defaults to ExpectationFailed when no selector context', () => {
      const error = new Error('Some completely unknown error');
      expect(classifyError(error)).toBe('ExpectationFailed');
    });

    it('handles string errors', () => {
      expect(classifyError('Timeout waiting for selector', { selector: '#x' })).toBe('TargetNotFound');
    });

    it('handles non-error objects', () => {
      expect(classifyError({ code: 'UNKNOWN' })).toBe('ExpectationFailed');
    });
  });
});
