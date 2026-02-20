import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { AuthProfileManager } from '../../src/memory/auth-profile-manager.js';
import type { AuthProfile, Page } from '../../src/memory/auth-profile-manager.js';
import { rm, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { randomUUID } from 'node:crypto';

describe('AuthProfileManager', () => {
  let profilesDir: string;
  let manager: AuthProfileManager;

  const sampleProfile: AuthProfile = {
    id: 'user1-example',
    domain: 'example.com',
    cookies: [{ name: 'session', value: 'abc123' }],
    localStorage: { token: 'jwt-token-here' },
    savedAt: '2026-02-21T10:00:00Z',
  };

  beforeEach(async () => {
    profilesDir = join(tmpdir(), `auth-profile-test-${randomUUID()}`);
    await mkdir(profilesDir, { recursive: true });
    manager = new AuthProfileManager(profilesDir);
  });

  afterEach(async () => {
    await rm(profilesDir, { recursive: true, force: true });
  });

  describe('save and load', () => {
    it('saves and loads a profile', async () => {
      await manager.save(sampleProfile);
      const loaded = await manager.load('user1-example');
      expect(loaded).not.toBeNull();
      expect(loaded!.id).toBe('user1-example');
      expect(loaded!.domain).toBe('example.com');
      expect(loaded!.cookies).toEqual(sampleProfile.cookies);
      expect(loaded!.localStorage).toEqual(sampleProfile.localStorage);
    });

    it('returns null for non-existent profile', async () => {
      const loaded = await manager.load('nonexistent');
      expect(loaded).toBeNull();
    });

    it('overwrites existing profile on save', async () => {
      await manager.save(sampleProfile);
      const updated = { ...sampleProfile, localStorage: { token: 'new-token' } };
      await manager.save(updated);

      const loaded = await manager.load('user1-example');
      expect(loaded!.localStorage).toEqual({ token: 'new-token' });
    });
  });

  describe('delete', () => {
    it('deletes an existing profile', async () => {
      await manager.save(sampleProfile);
      const deleted = await manager.delete('user1-example');
      expect(deleted).toBe(true);

      const loaded = await manager.load('user1-example');
      expect(loaded).toBeNull();
    });

    it('returns false when deleting non-existent profile', async () => {
      const deleted = await manager.delete('nonexistent');
      expect(deleted).toBe(false);
    });
  });

  describe('list', () => {
    it('lists all profile IDs', async () => {
      await manager.save(sampleProfile);
      await manager.save({ ...sampleProfile, id: 'user2-example' });

      const ids = await manager.list();
      expect(ids.sort()).toEqual(['user1-example', 'user2-example']);
    });

    it('returns empty array when no profiles exist', async () => {
      const ids = await manager.list();
      expect(ids).toEqual([]);
    });
  });

  // --- New tests for enhanced functionality ---

  describe('detectExpiry', () => {
    function mockPage(overrides: Partial<Page> = {}): Page {
      return {
        url: () => 'https://example.com/dashboard',
        goto: vi.fn().mockResolvedValue(undefined),
        title: vi.fn().mockResolvedValue('Dashboard'),
        content: vi.fn().mockResolvedValue('<html></html>'),
        evaluate: vi.fn().mockResolvedValue(undefined),
        ...overrides,
      };
    }

    it('returns true when profile has past expiresAt', async () => {
      const expired: AuthProfile = {
        ...sampleProfile,
        expiresAt: '2020-01-01T00:00:00Z',
      };
      const page = mockPage();
      expect(await manager.detectExpiry(page, expired)).toBe(true);
    });

    it('returns false when profile has future expiresAt', async () => {
      const valid: AuthProfile = {
        ...sampleProfile,
        expiresAt: '2099-01-01T00:00:00Z',
      };
      const page = mockPage();
      expect(await manager.detectExpiry(page, valid)).toBe(false);
    });

    it('returns true when cookies have expired timestamps', async () => {
      const expiredCookies: AuthProfile = {
        ...sampleProfile,
        cookies: [{ name: 'session', value: 'abc', expires: 1 }], // epoch second 1 = way in the past
      };
      const page = mockPage();
      expect(await manager.detectExpiry(page, expiredCookies)).toBe(true);
    });

    it('returns true when page URL contains login indicator', async () => {
      const page = mockPage({ url: () => 'https://example.com/login?redirect=/dashboard' });
      expect(await manager.detectExpiry(page, sampleProfile)).toBe(true);
    });

    it('returns true when page title contains login indicator', async () => {
      const page = mockPage({ title: vi.fn().mockResolvedValue('Sign In - Example') });
      expect(await manager.detectExpiry(page, sampleProfile)).toBe(true);
    });

    it('returns false for a valid non-expired session', async () => {
      const page = mockPage();
      expect(await manager.detectExpiry(page, sampleProfile)).toBe(false);
    });
  });

  describe('refreshSession', () => {
    it('captures new session state from page', async () => {
      const mockEval = vi.fn()
        .mockResolvedValueOnce([{ name: 'newsession', value: 'xyz789' }]) // cookies
        .mockResolvedValueOnce({ newtoken: 'refreshed-jwt' }) // localStorage
        .mockResolvedValueOnce({}); // sessionStorage

      const page: Page = {
        url: () => 'https://example.com/dashboard',
        goto: vi.fn().mockResolvedValue(undefined),
        title: vi.fn().mockResolvedValue('Dashboard'),
        content: vi.fn().mockResolvedValue('<html></html>'),
        evaluate: mockEval,
      };

      const loginWorkflow = { id: 'login', steps: [] };
      const refreshed = await manager.refreshSession(page, sampleProfile, loginWorkflow);

      expect(refreshed.cookies).toEqual([{ name: 'newsession', value: 'xyz789' }]);
      expect(refreshed.localStorage).toEqual({ newtoken: 'refreshed-jwt' });
      expect(refreshed.lastVerifiedAt).toBeDefined();
      expect(refreshed.lastUsedAt).toBeDefined();
    });

    it('keeps original data when page returns empty state', async () => {
      const mockEval = vi.fn()
        .mockResolvedValueOnce([]) // empty cookies
        .mockResolvedValueOnce({}) // empty localStorage
        .mockResolvedValueOnce({}); // empty sessionStorage

      const page: Page = {
        url: () => 'https://example.com/dashboard',
        goto: vi.fn().mockResolvedValue(undefined),
        title: vi.fn().mockResolvedValue('Dashboard'),
        content: vi.fn().mockResolvedValue('<html></html>'),
        evaluate: mockEval,
      };

      const loginWorkflow = { id: 'login', steps: [] };
      const refreshed = await manager.refreshSession(page, sampleProfile, loginWorkflow);

      expect(refreshed.cookies).toEqual(sampleProfile.cookies);
      expect(refreshed.localStorage).toEqual(sampleProfile.localStorage);
    });
  });

  describe('rotateProfile', () => {
    it('returns next non-expired profile for domain', async () => {
      const profile1: AuthProfile = { ...sampleProfile, id: 'p1', domain: 'example.com', savedAt: '' };
      const profile2: AuthProfile = { ...sampleProfile, id: 'p2', domain: 'example.com', savedAt: '' };

      await manager.save(profile1);
      await manager.save(profile2);

      // Set p1 as active so rotation skips it
      manager.setActiveProfile(profile1);

      const rotated = await manager.rotateProfile('example.com');
      expect(rotated).not.toBeNull();
      expect(rotated!.id).toBe('p2');
    });

    it('skips expired profiles', async () => {
      const expired: AuthProfile = {
        ...sampleProfile,
        id: 'expired-p',
        domain: 'example.com',
        expiresAt: '2020-01-01T00:00:00Z',
        savedAt: '',
      };
      const valid: AuthProfile = {
        ...sampleProfile,
        id: 'valid-p',
        domain: 'example.com',
        savedAt: '',
      };

      await manager.save(expired);
      await manager.save(valid);

      const rotated = await manager.rotateProfile('example.com');
      expect(rotated).not.toBeNull();
      expect(rotated!.id).toBe('valid-p');
    });

    it('returns null when no profiles available for domain', async () => {
      const otherDomain: AuthProfile = {
        ...sampleProfile,
        id: 'other',
        domain: 'other.com',
        savedAt: '',
      };
      await manager.save(otherDomain);

      const rotated = await manager.rotateProfile('example.com');
      expect(rotated).toBeNull();
    });

    it('returns null when all profiles for domain are expired', async () => {
      const expired: AuthProfile = {
        ...sampleProfile,
        id: 'exp1',
        domain: 'example.com',
        expiresAt: '2020-01-01T00:00:00Z',
        savedAt: '',
      };
      await manager.save(expired);

      const rotated = await manager.rotateProfile('example.com');
      expect(rotated).toBeNull();
    });
  });

  describe('getActiveProfile', () => {
    it('returns null when no active profile set', () => {
      expect(manager.getActiveProfile('example.com')).toBeNull();
    });

    it('returns active profile after setting it', () => {
      manager.setActiveProfile(sampleProfile);
      const active = manager.getActiveProfile('example.com');
      expect(active).not.toBeNull();
      expect(active!.id).toBe('user1-example');
    });
  });

  describe('verifyProfile', () => {
    it('returns true for valid session and updates lastVerifiedAt', async () => {
      const page: Page = {
        url: () => 'https://example.com/dashboard',
        goto: vi.fn().mockResolvedValue(undefined),
        title: vi.fn().mockResolvedValue('Dashboard'),
        content: vi.fn().mockResolvedValue('<html></html>'),
        evaluate: vi.fn().mockResolvedValue(undefined),
      };

      await manager.save(sampleProfile);
      const result = await manager.verifyProfile(page, sampleProfile);
      expect(result).toBe(true);

      // Check the profile was updated with lastVerifiedAt
      const loaded = await manager.load(sampleProfile.id);
      expect(loaded!.lastVerifiedAt).toBeDefined();
    });

    it('returns false for expired session', async () => {
      const page: Page = {
        url: () => 'https://example.com/login',
        goto: vi.fn().mockResolvedValue(undefined),
        title: vi.fn().mockResolvedValue('Login'),
        content: vi.fn().mockResolvedValue('<html></html>'),
        evaluate: vi.fn().mockResolvedValue(undefined),
      };

      const result = await manager.verifyProfile(page, sampleProfile);
      expect(result).toBe(false);
    });
  });

  describe('save populates timestamps', () => {
    it('sets createdAt and lastUsedAt on first save', async () => {
      await manager.save(sampleProfile);
      const loaded = await manager.load(sampleProfile.id);
      expect(loaded!.createdAt).toBeDefined();
      expect(loaded!.lastUsedAt).toBeDefined();
    });

    it('preserves existing createdAt on subsequent saves', async () => {
      const withCreated: AuthProfile = {
        ...sampleProfile,
        createdAt: '2025-01-01T00:00:00Z',
      };
      await manager.save(withCreated);
      const loaded = await manager.load(sampleProfile.id);
      expect(loaded!.createdAt).toBe('2025-01-01T00:00:00Z');
    });
  });
});
