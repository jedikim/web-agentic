export interface HttpClientOptions {
  baseUrl: string;
  apiKey?: string;
  defaultTimeoutMs?: number;
}

export interface RequestOptions {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  path: string;
  body?: unknown;
  timeoutMs?: number;
  requestId: string;
}

export interface HttpResponse<T> {
  ok: boolean;
  status: number;
  data: T;
  requestId: string;
}

export class HttpClientError extends Error {
  constructor(
    message: string,
    public status: number,
    public requestId: string,
  ) {
    super(message);
    this.name = 'HttpClientError';
  }
}

/**
 * Base HTTP client for communicating with the Python Authoring Service.
 * Uses native fetch() (Node 20+).
 * All requests include requestId for idempotency (Blueprint section 3.3).
 */
export class HttpClient {
  private baseUrl: string;
  private apiKey?: string;
  private defaultTimeoutMs: number;

  constructor(options: HttpClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
    this.apiKey = options.apiKey;
    this.defaultTimeoutMs = options.defaultTimeoutMs ?? 30000;
  }

  async request<T>(options: RequestOptions): Promise<HttpResponse<T>> {
    const { method, path, body, requestId } = options;
    const timeoutMs = options.timeoutMs ?? this.defaultTimeoutMs;
    const url = `${this.baseUrl}${path}`;

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Request-Id': requestId,
    };

    if (this.apiKey) {
      headers['Authorization'] = `Bearer ${this.apiKey}`;
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(url, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });

      const data = (await response.json()) as T;

      if (!response.ok) {
        throw new HttpClientError(
          `HTTP ${response.status}: ${response.statusText}`,
          response.status,
          requestId,
        );
      }

      return {
        ok: true,
        status: response.status,
        data,
        requestId,
      };
    } catch (error) {
      if (error instanceof HttpClientError) throw error;

      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new HttpClientError(
          `Request timed out after ${timeoutMs}ms`,
          0,
          requestId,
        );
      }

      throw new HttpClientError(
        error instanceof Error ? error.message : String(error),
        0,
        requestId,
      );
    } finally {
      clearTimeout(timeout);
    }
  }

  async get<T>(path: string, requestId: string, timeoutMs?: number): Promise<HttpResponse<T>> {
    return this.request<T>({ method: 'GET', path, requestId, timeoutMs });
  }

  async post<T>(path: string, body: unknown, requestId: string, timeoutMs?: number): Promise<HttpResponse<T>> {
    return this.request<T>({ method: 'POST', path, body, requestId, timeoutMs });
  }
}
