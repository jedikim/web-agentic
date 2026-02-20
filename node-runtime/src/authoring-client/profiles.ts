import { HttpClient } from './http-client.js';

/**
 * GET /profiles/:id wrapper.
 * Blueprint section 3.2, endpoint #4.
 */
export async function getProfile(
  client: HttpClient,
  profileId: string,
  requestId: string,
): Promise<unknown> {
  const response = await client.get<unknown>(
    `/profiles/${encodeURIComponent(profileId)}`,
    requestId,
  );

  return response.data;
}
