import type { CaptureCandidate, SourceApp } from '../types/contracts';
import { extractConversationId } from './conversation-id';
import { buildAiCandidate, buildBulkCapture } from './capture';

/**
 * Parses intercepted AI platform API responses into CaptureCandidates.
 */
export async function parseApiPayload(
  platform: SourceApp,
  url: string,
  payload: unknown,
): Promise<CaptureCandidate | null> {
  const conversationId = extractConversationId(window.location.href, platform) || extractConversationId(url, platform);

  switch (platform) {
    case 'gemini':
      return parseGeminiBatchExecute(payload as any[], url, conversationId);
    case 'chatgpt':
      return parseChatGptConversation(payload, url, conversationId);
    case 'claude':
      return parseClaudeConversation(payload, url, conversationId);
    case 'perplexity':
    case 'grok':
      return null;
    default:
      return null;
  }
}

export async function parseApiSessionPayload(
  platform: SourceApp,
  url: string,
  payload: unknown,
): Promise<CaptureCandidate | null> {
  const conversationId = extractConversationId(window.location.href, platform) || extractConversationId(url, platform);
  if (!conversationId) return null;

  switch (platform) {
    case 'gemini':
      return parseGeminiSession(payload, conversationId);
    case 'chatgpt':
      return parseChatGptSession(payload, conversationId);
    case 'claude':
      return parseClaudeSession(payload, conversationId);
    case 'perplexity':
      return parseGenericRoleSession(payload, conversationId, 'perplexity', 'Perplexity conversation');
    case 'grok':
      return parseGenericRoleSession(payload, conversationId, 'grok', 'Grok conversation');
    default:
      return null;
  }
}

/**
 * Parses intercepted AI platform API responses into CaptureCandidates.
 */
async function parseGeminiBatchExecute(
  payload: any[],
  url: string,
  conversationId: string | null,
): Promise<CaptureCandidate | null> {
  try {
    let responseStr = '';
    if (Array.isArray(payload) && payload.length > 0) {
      const inner = Array.isArray(payload[0]) ? payload[0] : payload;
      if (inner.length >= 3 && typeof inner[2] === 'string') {
        responseStr = inner[2];
      }
    }

    if (!responseStr) {
      throw new Error('Gemini parser: Could not locate batch_execute_response string');
    }

    const innerJson = JSON.parse(responseStr);
    let assistantText = extractLongestString(innerJson);

    if (!assistantText || assistantText.length < 10) {
      throw new Error('Gemini parser: Extracted text too short or empty');
    }

    return await buildAiCandidate({
      sourceApp: 'gemini',
      userText: document.title || 'Gemini Conversation',
      assistantText: assistantText,
      conversationId: conversationId ?? undefined,
    });
  } catch (err) {
    window.dispatchEvent(new CustomEvent('shail-api-parse-failed', {
      detail: { platform: 'gemini', error: (err as Error).message }
    }));
    return null;
  }
}

/**
 * Parses ChatGPT conversations.
 * Core Target Path: /backend-api/conversation/*
 * Precise Key Path: message.content.parts[0]
 */
async function parseChatGptConversation(
  payload: any,
  url: string,
  conversationId: string | null,
): Promise<CaptureCandidate | null> {
  try {
    let assistantText = '';

    if (Array.isArray(payload)) {
      // It's an SSE stream of chunks. Iterate backwards to find the last complete text.
      for (let i = payload.length - 1; i >= 0; i--) {
        const chunk = payload[i];
        if (chunk?.message?.content?.parts && Array.isArray(chunk.message.content.parts)) {
          const part = chunk.message.content.parts[0];
          if (typeof part === 'string' && part) {
            assistantText = part;
            break;
          }
        }
      }
    } else if (payload && typeof payload === 'object') {
      if (payload.message?.content?.parts && Array.isArray(payload.message.content.parts)) {
        const part = payload.message.content.parts[0];
        if (typeof part === 'string') {
          assistantText = part;
        }
      }
      else if (payload.mapping && payload.current_node) {
        const nodes = payload.mapping;
        let currId = payload.current_node;
        const assistantTexts: string[] = [];
        while (currId && nodes[currId]) {
          const node = nodes[currId];
          if (node.message && (node.message.author?.role === 'assistant' || node.message.role === 'assistant')) {
            const part = node.message.content?.parts?.[0];
            if (typeof part === 'string' && part) {
              assistantTexts.unshift(part);
            }
          }
          currId = node.parent;
        }
        if (assistantTexts.length > 0) {
          assistantText = assistantTexts[assistantTexts.length - 1];
        }
      }
    }

    if (!assistantText) {
      console.warn('[SHAIL] ChatGPT strict path failed, falling back to recursive parsing.');
      assistantText = extractLongestString(payload);
    }

    if (!assistantText || assistantText.length < 10) {
      throw new Error('ChatGPT parser: Extracted text too short or empty');
    }

    const parsedId = conversationId || payload?.conversation_id || undefined;

    return await buildAiCandidate({
      sourceApp: 'chatgpt',
      userText: document.title || 'ChatGPT Conversation',
      assistantText: assistantText,
      conversationId: parsedId,
    });
  } catch (err) {
    window.dispatchEvent(new CustomEvent('shail-api-parse-failed', {
      detail: { platform: 'chatgpt', error: (err as Error).message }
    }));
    return null;
  }
}

/**
 * Parses Claude conversations.
 * Core Target Path: /api/organizations/{org}/chat_conversations/{id}
 * Precise Key Path: chat_messages[].text
 */
async function parseClaudeConversation(
  payload: any,
  url: string,
  conversationId: string | null,
): Promise<CaptureCandidate | null> {
  try {
    let assistantText = '';

    if (payload && typeof payload === 'object') {
      if (Array.isArray(payload.chat_messages)) {
        const assistantMsgs = payload.chat_messages.filter(
          (m: any) => m.sender === 'assistant' || m.role === 'assistant'
        );
        if (assistantMsgs.length > 0) {
          const lastMsg = assistantMsgs[assistantMsgs.length - 1];
          if (typeof lastMsg.text === 'string') {
            assistantText = lastMsg.text;
          }
        }
      }
    }

    if (!assistantText) {
      console.warn('[SHAIL] Claude strict path failed, falling back to recursive parsing.');
      assistantText = extractLongestString(payload);
    }

    if (!assistantText || assistantText.length < 10) {
      throw new Error('Claude parser: Extracted text too short or empty');
    }

    const parsedId = conversationId || payload?.uuid || undefined;

    return await buildAiCandidate({
      sourceApp: 'claude',
      userText: document.title || 'Claude Conversation',
      assistantText: assistantText,
      conversationId: parsedId,
    });
  } catch (err) {
    window.dispatchEvent(new CustomEvent('shail-api-parse-failed', {
      detail: { platform: 'claude', error: (err as Error).message }
    }));
    return null;
  }
}

function pairTurns(messages: Array<{ role: string; text: string }>): Array<{ user: string; assistant: string }> {
  const turns: Array<{ user: string; assistant: string }> = [];
  let pendingUser = '';
  for (const message of messages) {
    const text = (message.text || '').trim();
    if (!text) continue;
    if (message.role === 'user') {
      pendingUser = text;
    } else if (message.role === 'assistant') {
      turns.push({ user: pendingUser, assistant: text });
      pendingUser = '';
    }
  }
  return turns;
}

function normalizeRole(value: unknown): 'user' | 'assistant' | '' {
  const role = String(value ?? '').toLowerCase();
  if (['user', 'human', 'query', 'prompt'].includes(role)) return 'user';
  if (['model', 'assistant', 'gemini', 'bard', 'ai', 'answer', 'grok'].includes(role)) return 'assistant';
  return '';
}

function textFromValue(value: unknown): string {
  if (typeof value === 'string') return value.trim();
  if (Array.isArray(value)) {
    return value
      .map(textFromValue)
      .filter(Boolean)
      .join('\n')
      .trim();
  }
  if (value && typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    for (const key of ['text', 'content', 'message', 'body', 'markdown']) {
      const text = textFromValue(obj[key]);
      if (text) return text;
    }
    const parts = textFromValue(obj.parts);
    if (parts) return parts;
  }
  return '';
}

function parseJsonLike(value: unknown): unknown[] {
  const parsed: unknown[] = [];
  const visit = (node: unknown) => {
    if (typeof node === 'string') {
      const text = node.trim();
      if ((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))) {
        try {
          const json = JSON.parse(text);
          parsed.push(json);
          visit(json);
        } catch {
          // Not JSON; ignore.
        }
      }
      return;
    }
    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }
    if (node && typeof node === 'object') {
      Object.values(node as Record<string, unknown>).forEach(visit);
    }
  };
  visit(value);
  return parsed;
}

function extractRoleMessages(root: unknown): Array<{ role: string; text: string; created?: string | number }> {
  const messages: Array<{ role: string; text: string; created?: string | number }> = [];
  const seen = new Set<string>();

  const add = (role: string, text: string, created?: string | number) => {
    const clean = text.trim();
    if (!role || clean.length < 2) return;
    const key = `${role}:${clean.slice(0, 180)}`;
    if (seen.has(key)) return;
    seen.add(key);
    messages.push({ role, text: clean, created });
  };

  const visit = (node: unknown) => {
    if (!node || typeof node !== 'object') return;

    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }

    const obj = node as Record<string, unknown>;
    const role = normalizeRole(obj.role ?? obj.sender ?? obj.author ?? obj.type);
    const text = textFromValue(obj.text ?? obj.content ?? obj.message ?? obj.parts);
    if (role && text) {
      add(role, text, obj.createTime as string | undefined || obj.created_at as string | undefined || obj.created as string | undefined || obj.timestamp as string | undefined);
    }

    Object.values(obj).forEach(visit);
  };

  visit(root);
  return messages;
}

function findGeminiMessagesPayload(payload: unknown): Array<{ role: string; text: string; created?: string | number }> {
  const candidates = [payload, ...parseJsonLike(payload)];
  let best: Array<{ role: string; text: string; created?: string | number }> = [];

  for (const candidate of candidates) {
    const data = candidate as Record<string, unknown>;
    if (data && typeof data === 'object' && Array.isArray(data.conversations)) {
      for (const conv of data.conversations as unknown[]) {
        const messages = extractRoleMessages((conv as Record<string, unknown>)?.messages);
        if (messages.length > best.length) best = messages;
      }
    }

    const direct = extractRoleMessages(candidate);
    if (direct.length > best.length) best = direct;
  }

  return best.sort((a, b) => String(a.created ?? '').localeCompare(String(b.created ?? '')));
}

async function parseGeminiSession(payload: any, conversationId: string): Promise<CaptureCandidate | null> {
  try {
    const messages = findGeminiMessagesPayload(payload);
    const turns = pairTurns(messages);
    if (!turns.length) return null;
    return buildBulkCapture({
      sourceApp: 'gemini',
      conversationId,
      turns,
      captureMode: 'retroactive',
      captureSource: 'api',
      title: document.title || 'Gemini conversation',
    });
  } catch {
    return null;
  }
}

async function parseGenericRoleSession(
  payload: any,
  conversationId: string,
  sourceApp: Extract<SourceApp, 'perplexity' | 'grok'>,
  fallbackTitle: string,
): Promise<CaptureCandidate | null> {
  try {
    const messages = extractRoleMessages(payload)
      .sort((a, b) => String(a.created ?? '').localeCompare(String(b.created ?? '')));
    const turns = pairTurns(messages);
    if (!turns.length) return null;
    return buildBulkCapture({
      sourceApp,
      conversationId,
      turns,
      captureMode: 'retroactive',
      captureSource: 'api',
      title: document.title || fallbackTitle,
    });
  } catch {
    return null;
  }
}

async function parseChatGptSession(payload: any, conversationId: string): Promise<CaptureCandidate | null> {
  try {
    if (!payload || typeof payload !== 'object' || !payload.mapping) return null;
    const nodes = Object.values(payload.mapping) as any[];
    const messages = nodes
      .map(node => node?.message)
      .filter(Boolean)
      .map(message => {
        const role = message.author?.role || message.role;
        const part = message.content?.parts?.find((p: unknown) => typeof p === 'string');
        return {
          role: role === 'assistant' ? 'assistant' : role === 'user' ? 'user' : '',
          text: typeof part === 'string' ? part : '',
          created: Number(message.create_time || 0),
        };
      })
      .filter(message => message.role && message.text)
      .sort((a, b) => a.created - b.created);
    const turns = pairTurns(messages);
    if (!turns.length) return null;
    return buildBulkCapture({
      sourceApp: 'chatgpt',
      conversationId,
      turns,
      captureMode: 'retroactive',
      captureSource: 'api',
      title: document.title || 'ChatGPT conversation',
    });
  } catch {
    return null;
  }
}

async function parseClaudeSession(payload: any, conversationId: string): Promise<CaptureCandidate | null> {
  try {
    if (!payload || typeof payload !== 'object' || !Array.isArray(payload.chat_messages)) return null;
    const messages = payload.chat_messages
      .map((message: any) => ({
        role: message.sender === 'assistant' || message.role === 'assistant' ? 'assistant'
          : message.sender === 'human' || message.sender === 'user' || message.role === 'user' ? 'user'
          : '',
        text: typeof message.text === 'string' ? message.text : '',
        created: String(message.created_at || message.updated_at || ''),
      }))
      .filter((message: { role: string; text: string }) => message.role && message.text)
      .sort((a: { created: string }, b: { created: string }) => a.created.localeCompare(b.created));
    const turns = pairTurns(messages);
    if (!turns.length) return null;
    return buildBulkCapture({
      sourceApp: 'claude',
      conversationId,
      turns,
      captureMode: 'retroactive',
      captureSource: 'api',
      title: document.title || 'Claude conversation',
    });
  } catch {
    return null;
  }
}

function extractLongestString(obj: any): string {
  let longest = '';
  
  function recurse(current: any) {
    if (typeof current === 'string') {
      if (current.length > longest.length) {
        longest = current;
      }
    } else if (Array.isArray(current)) {
      for (const item of current) {
        recurse(item);
      }
    } else if (current !== null && typeof current === 'object') {
      for (const key in current) {
        recurse(current[key]);
      }
    }
  }
  
  recurse(obj);
  return longest;
}
