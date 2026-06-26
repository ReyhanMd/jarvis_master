/**
 * api-interceptor.ts — main-world script that monkey-patches window.fetch
 * and XMLHttpRequest to intercept AI platform API responses.
 *
 * This script runs in the page's main world (not the extension's isolated
 * content script world). It can see the page's real `fetch` and XHR
 * objects. Intercepted responses are forwarded to the content script world
 * via a CustomEvent ('shail-api-intercept').
 *
 * IMPORTANT: This script is purely observational. It NEVER blocks, delays,
 * or modifies any request or response. It clones response bodies so the
 * original consumer is unaffected.
 */

/** Platform → URL patterns that we care about. */
const INTERCEPT_PATTERNS: Record<string, RegExp[]> = {
  chatgpt: [
    /backend-api\/conversations/i,
    /backend-api\/conversation\//i,
  ],
  claude: [
    /api\/organizations\/[^/]+\/chat_conversations/i,
  ],
  gemini: [
    /batchexecute/i,
  ],
  perplexity: [
    /api\/v2\/search\//i,
    /api\/search\//i,
  ],
  grok: [
    /api\/rpc/i,
    /rest\/api\//i,
  ],
};

/** Detect which platform we're on based on hostname. */
function detectPlatform(): string | null {
  const host = location.hostname;
  if (host.includes('chat.openai.com') || host.includes('chatgpt.com')) return 'chatgpt';
  if (host.includes('claude.ai')) return 'claude';
  if (host.includes('gemini.google.com')) return 'gemini';
  if (host.includes('perplexity.ai')) return 'perplexity';
  if (host.includes('grok.com') || host.includes('x.ai')) return 'grok';
  return null;
}

/** Check if a URL matches any intercept pattern for the current platform. */
function matchesPattern(url: string, platform: string): boolean {
  const patterns = INTERCEPT_PATTERNS[platform];
  if (!patterns) return false;
  return patterns.some(p => p.test(url));
}

/** Post an intercepted payload to content-script world via CustomEvent. */
function emitIntercept(platform: string, url: string, payload: unknown): void {
  try {
    window.dispatchEvent(new CustomEvent('shail-api-intercept', {
      detail: { platform, url, payload, timestamp: Date.now() },
    }));
  } catch {
    // Silently drop if event dispatch fails (page teardown, etc.)
  }
}

/**
 * Try to parse a response body as JSON or Server-Sent Events (SSE). Returns null on failure.
 * Handles streaming responses by reading the clone to completion and parsing `data: {...}` lines.
 */
async function tryParseJson(response: Response): Promise<unknown | null> {
  try {
    const clone = response.clone();
    const text = await clone.text();
    if (!text || text.length < 2) return null;
    
    // Try standard JSON first
    try {
      return JSON.parse(text);
    } catch {
      // If it fails, check if it looks like SSE stream (data: {...})
      if (text.includes('data: {') || text.includes('data: [')) {
        const lines = text.split('\n');
        const jsonChunks: any[] = [];
        for (const line of lines) {
          if (line.startsWith('data: ') && line !== 'data: [DONE]') {
            try {
              jsonChunks.push(JSON.parse(line.slice(6)));
            } catch {}
          }
        }
        if (jsonChunks.length > 0) return jsonChunks;
      }
      return null;
    }
  } catch {
    return null;
  }
}

/** Install the fetch interceptor. */
function patchFetch(platform: string): void {
  const origFetch = window.fetch;

  window.fetch = async function (...args: Parameters<typeof fetch>): Promise<Response> {
    const response = await origFetch.apply(this, args);

    // Determine the URL from the first argument
    let url = '';
    if (typeof args[0] === 'string') {
      url = args[0];
    } else if (args[0] instanceof Request) {
      url = args[0].url;
    } else if (args[0] instanceof URL) {
      url = args[0].toString();
    }

    if (url && matchesPattern(url, platform)) {
      // Parse asynchronously — don't block the caller
      tryParseJson(response).then(json => {
        if (json !== null) {
          emitIntercept(platform, url, json);
        }
      }).catch(() => {
        // Silently drop parse errors
      });
    }

    return response;
  };
}

/** Install the XHR interceptor. */
function patchXHR(platform: string): void {
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (
    method: string,
    url: string | URL,
    ...rest: any[]
  ) {
    (this as any).__shail_url = typeof url === 'string' ? url : url.toString();
    return origOpen.apply(this, [method, url, ...rest] as any);
  };

  XMLHttpRequest.prototype.send = function (...args: any[]) {
    const xhrUrl = (this as any).__shail_url as string | undefined;

    if (xhrUrl && matchesPattern(xhrUrl, platform)) {
      this.addEventListener('load', function () {
        try {
          if (this.responseType === '' || this.responseType === 'text') {
            const text = this.responseText;
            if (text && text.length >= 2) {
              const json = JSON.parse(text);
              emitIntercept(platform, xhrUrl, json);
            }
          }
        } catch {
          // Silently drop — non-JSON or parse error
        }
      });
    }

    return origSend.apply(this, args.slice(0, 1) as [Document | XMLHttpRequestBodyInit | null | undefined]);
  };
}

/**
 * Bootstrap: detect platform, patch fetch + XHR if applicable.
 * This function is called once when the script is injected into the page.
 */
export function installApiInterceptor(): void {
  const platform = detectPlatform();
  if (!platform) return;

  try {
    patchFetch(platform);
  } catch {
    // fetch patch failed — CSP or frozen prototype
  }

  try {
    patchXHR(platform);
  } catch {
    // XHR patch failed — CSP or frozen prototype
  }
}
