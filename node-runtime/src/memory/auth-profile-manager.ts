import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import type { Workflow } from '../types/index.js';

export interface AuthCookie {
  name: string;
  value: string;
  domain?: string;
  path?: string;
  expires?: number;
}

export interface AuthProfile {
  id: string;
  domain: string;
  cookies?: (AuthCookie | Record<string, string>)[];
  localStorage?: Record<string, string>;
  sessionStorage?: Record<string, string>;
  savedAt: string;
  createdAt?: string;
  expiresAt?: string;
  lastUsedAt?: string;
  lastVerifiedAt?: string;
}

/**
 * Minimal Page interface for auth operations.
 * Compatible with Playwright/Stagehand Page.
 */
export interface Page {
  url(): string;
  goto(url: string): Promise<unknown>;
  title(): Promise<string>;
  content(): Promise<string>;
  evaluate<T>(fn: string | ((...args: unknown[]) => T), ...args: unknown[]): Promise<T>;
}

/** Indicators that a page is showing a login/auth wall */
const LOGIN_INDICATORS = [
  'login', 'sign in', 'sign-in', 'signin', 'log in', 'log-in',
  'authenticate', 'password', 'unauthorized', '401', '403',
];

/**
 * Manage browser auth state (cookies/storage) profiles.
 * Stores profiles as JSON files for session reuse across runs.
 * Supports expiry detection, session refresh, multi-profile rotation, and verification.
 */
export class AuthProfileManager {
  private activeProfiles = new Map<string, AuthProfile>();

  constructor(private profilesDir: string) {}

  /**
   * Load a saved auth profile by ID.
   */
  async load(profileId: string): Promise<AuthProfile | null> {
    const filePath = join(this.profilesDir, `${profileId}.json`);
    try {
      const data = await readFile(filePath, 'utf-8');
      return JSON.parse(data) as AuthProfile;
    } catch {
      return null;
    }
  }

  /**
   * Save an auth profile.
   */
  async save(profile: AuthProfile): Promise<void> {
    await mkdir(this.profilesDir, { recursive: true });
    const filePath = join(this.profilesDir, `${profile.id}.json`);
    const now = new Date().toISOString();
    const toSave: AuthProfile = {
      ...profile,
      savedAt: now,
      createdAt: profile.createdAt ?? now,
      lastUsedAt: profile.lastUsedAt ?? now,
    };
    await writeFile(filePath, JSON.stringify(toSave, null, 2), 'utf-8');
  }

  /**
   * Delete an auth profile.
   */
  async delete(profileId: string): Promise<boolean> {
    const filePath = join(this.profilesDir, `${profileId}.json`);
    try {
      const { unlink } = await import('node:fs/promises');
      await unlink(filePath);
      this.activeProfiles.delete(profileId);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * List all stored profile IDs.
   */
  async list(): Promise<string[]> {
    try {
      const { readdir } = await import('node:fs/promises');
      const files = await readdir(this.profilesDir);
      return files
        .filter((f) => f.endsWith('.json'))
        .map((f) => f.replace('.json', ''));
    } catch {
      return [];
    }
  }

  /**
   * Detect if a session has expired.
   * Checks cookie expiry timestamps, login page redirects, and auth error indicators.
   */
  async detectExpiry(page: Page, profile: AuthProfile): Promise<boolean> {
    // Check explicit expiresAt timestamp
    if (profile.expiresAt) {
      const expiryTime = new Date(profile.expiresAt).getTime();
      if (Date.now() > expiryTime) {
        return true;
      }
    }

    // Check cookie expiry timestamps
    if (profile.cookies) {
      const now = Date.now() / 1000;
      for (const cookie of profile.cookies) {
        if ('expires' in cookie && typeof cookie.expires === 'number' && cookie.expires > 0) {
          if (cookie.expires < now) {
            return true;
          }
        }
      }
    }

    // Check page for login/auth indicators
    const pageUrl = page.url().toLowerCase();
    const pageTitle = (await page.title()).toLowerCase();

    for (const indicator of LOGIN_INDICATORS) {
      if (pageUrl.includes(indicator) || pageTitle.includes(indicator)) {
        return true;
      }
    }

    return false;
  }

  /**
   * Refresh an expired session by re-running a login workflow.
   * Returns a new AuthProfile with updated session state.
   * The caller is responsible for actually executing the workflow steps against the page.
   * This method captures the resulting auth state after the workflow is assumed to have run.
   */
  async refreshSession(
    page: Page,
    profile: AuthProfile,
    _loginWorkflow: Workflow,
  ): Promise<AuthProfile> {
    // Capture new session state from the page after login workflow execution
    const newCookies = await page.evaluate<AuthCookie[]>(
      'JSON.parse(JSON.stringify(document.cookie.split("; ").map(c => { const [name, ...rest] = c.split("="); return { name, value: rest.join("=") }; })))',
    );

    const newLocalStorage = await page.evaluate<Record<string, string>>(
      'JSON.parse(JSON.stringify(Object.fromEntries(Object.entries(localStorage))))',
    );

    const newSessionStorage = await page.evaluate<Record<string, string>>(
      'JSON.parse(JSON.stringify(Object.fromEntries(Object.entries(sessionStorage))))',
    );

    const now = new Date().toISOString();
    const refreshed: AuthProfile = {
      ...profile,
      cookies: newCookies.length > 0 ? newCookies : profile.cookies,
      localStorage: Object.keys(newLocalStorage).length > 0 ? newLocalStorage : profile.localStorage,
      sessionStorage: Object.keys(newSessionStorage).length > 0 ? newSessionStorage : profile.sessionStorage,
      savedAt: now,
      lastUsedAt: now,
      lastVerifiedAt: now,
    };

    await this.save(refreshed);
    this.activeProfiles.set(refreshed.domain, refreshed);
    return refreshed;
  }

  /**
   * Rotate to the next available non-expired profile for a domain.
   * Skips profiles that have a past expiresAt timestamp.
   */
  async rotateProfile(domain: string): Promise<AuthProfile | null> {
    const allIds = await this.list();
    const currentActive = this.activeProfiles.get(domain);
    const now = Date.now();

    for (const id of allIds) {
      // Skip the currently active profile
      if (currentActive && id === currentActive.id) {
        continue;
      }

      const profile = await this.load(id);
      if (!profile || profile.domain !== domain) {
        continue;
      }

      // Skip expired profiles
      if (profile.expiresAt && new Date(profile.expiresAt).getTime() < now) {
        continue;
      }

      this.activeProfiles.set(domain, profile);
      return profile;
    }

    return null;
  }

  /**
   * Get the currently active profile for a domain.
   */
  getActiveProfile(domain: string): AuthProfile | null {
    return this.activeProfiles.get(domain) ?? null;
  }

  /**
   * Set a profile as the active profile for its domain.
   */
  setActiveProfile(profile: AuthProfile): void {
    this.activeProfiles.set(profile.domain, profile);
  }

  /**
   * Verify that a profile's session is still valid by checking the page state.
   * Returns true if the page does not show login/auth indicators.
   */
  async verifyProfile(page: Page, profile: AuthProfile): Promise<boolean> {
    const expired = await this.detectExpiry(page, profile);
    if (expired) {
      return false;
    }

    // Update lastVerifiedAt on successful verification
    const now = new Date().toISOString();
    const verified: AuthProfile = {
      ...profile,
      lastVerifiedAt: now,
      lastUsedAt: now,
    };
    await this.save(verified);
    this.activeProfiles.set(profile.domain, verified);
    return true;
  }
}
