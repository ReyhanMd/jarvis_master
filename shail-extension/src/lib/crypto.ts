/**
 * Returns a hex SHA-256 digest of the given string.
 * Used by content scripts to build a stable customId for deduplication:
 *   customId = sha256(url + toDateString())
 */
export async function sha256(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(hashBuffer))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}
