import type { CaptureSegment, SourceApp } from '../types/contracts';
import { extractConversationId } from './conversation-id';

export interface StructuredMessage {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  text: string;
  segments: CaptureSegment[];
}

export interface PlatformAdapter {
  sourceApp: SourceApp;
  label: string;
  color: string;
  detectChatTitle(): string;
  detectPlatform(): SourceApp;
  extractMessages(root: Element | Document): StructuredMessage[];
  getChatID(): string;
  getConversationLinks(): string[];
  interceptAPIResponse?(url: string, payload: unknown): unknown | null;
}

interface AdapterConfig {
  sourceApp: SourceApp;
  label: string;
  color: string;
  userSelectors: string[];
  assistantSelectors: string[];
  linkSelectors: string[];
  titleStrip: RegExp;
}

function queryAll(root: Element | Document, selectors: string[]): HTMLElement[] {
  for (const selector of selectors) {
    const hits = Array.from(root.querySelectorAll(selector)) as HTMLElement[];
    if (hits.length) return hits;
  }
  return [];
}

function textOf(el: HTMLElement): string {
  return (el.innerText || el.textContent || '').trim();
}

function languageOf(code: Element): string | undefined {
  const cls = Array.from(code.classList).find(c => c.startsWith('language-'));
  return cls?.replace(/^language-/, '') || code.getAttribute('data-language') || undefined;
}

function tableToMarkdown(table: HTMLTableElement): string {
  const rows = Array.from(table.querySelectorAll('tr')).map(tr =>
    Array.from(tr.children).map(cell => (cell.textContent || '').replace(/\s+/g, ' ').trim()),
  ).filter(row => row.some(Boolean));
  if (!rows.length) return '';
  const [head, ...body] = rows;
  const sep = head.map(() => '---');
  return [head, sep, ...body]
    .map(row => `| ${row.map(cell => cell.replace(/\|/g, '\\|')).join(' | ')} |`)
    .join('\n');
}

function segmentFromSpecial(el: Element, role: 'user' | 'assistant' | 'tool'): CaptureSegment | null {
  const tag = el.tagName.toLowerCase();
  if (tag === 'pre') {
    const code = el.querySelector('code') ?? el;
    return {
      kind: 'code',
      content: (code.textContent || '').trim(),
      language: languageOf(code),
      role,
    };
  }
  if (tag === 'table') {
    return { kind: 'table', content: tableToMarkdown(el as HTMLTableElement), role };
  }
  if (/^h[1-6]$/.test(tag)) {
    return {
      kind: 'markdown',
      content: `${'#'.repeat(Number(tag[1]))} ${(el.textContent || '').trim()}`,
      role,
      metadata: { heading_level: Number(tag[1]) },
    };
  }
  if (tag === 'img') {
    const img = el as HTMLImageElement;
    return {
      kind: 'image_ref',
      content: img.alt || img.title || img.currentSrc || img.src || 'image',
      role,
      metadata: { src: img.currentSrc || img.src || '', alt: img.alt || '' },
    };
  }
  if (
    el.matches('.math-inline,.math-display,.katex,[data-latex],[class*="math"]')
  ) {
    return {
      kind: 'math',
      content: (el.getAttribute('data-latex') || el.textContent || '').trim(),
      role,
    };
  }
  if (
    el.matches('[data-testid*="tool" i],[class*="tool" i],[data-tool-name]')
  ) {
    return {
      kind: role === 'tool' ? 'tool_result' : 'tool_call',
      content: (el.textContent || '').trim(),
      role: 'tool',
      metadata: { tool_name: el.getAttribute('data-tool-name') || undefined },
    };
  }
  return null;
}

function extractSegments(el: HTMLElement, role: 'user' | 'assistant' | 'tool'): CaptureSegment[] {
  const segments: CaptureSegment[] = [];
  const seenSpecial = new Set<Element>();

  el.querySelectorAll('pre,table,h1,h2,h3,h4,h5,h6,img,.math-inline,.math-display,.katex,[data-latex],[data-testid*="tool" i],[class*="tool" i],[data-tool-name]')
    .forEach(node => {
      if (Array.from(seenSpecial).some(parent => parent.contains(node))) return;
      const seg = segmentFromSpecial(node, role);
      if (seg && seg.content) {
        segments.push(seg);
        seenSpecial.add(node);
      }
    });

  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('pre,table,h1,h2,h3,h4,h5,h6,img,.math-inline,.math-display,.katex,[data-latex],[data-testid*="tool" i],[class*="tool" i],[data-tool-name]')
    .forEach(node => node.remove());
  const plain = (clone.innerText || clone.textContent || '').trim();
  if (plain) segments.unshift({ kind: 'text', content: plain, role });
  if (!segments.length) {
    const fallback = textOf(el);
    if (fallback) segments.push({ kind: 'text', content: fallback, role });
  }
  return segments;
}

function fingerprint(role: string, index: number, text: string): string {
  return `${role}:${index}:${text.slice(0, 120)}`;
}

function buildMessages(
  root: Element | Document,
  userSelectors: string[],
  assistantSelectors: string[],
): StructuredMessage[] {
  const messages: StructuredMessage[] = [];
  queryAll(root, userSelectors).forEach((el, index) => {
    const segments = extractSegments(el, 'user');
    const text = segments.map(s => s.content).join('\n\n').trim();
    if (text) messages.push({ id: fingerprint('user', index, text), role: 'user', text, segments });
  });
  queryAll(root, assistantSelectors).forEach((el, index) => {
    const segments = extractSegments(el, 'assistant');
    const text = segments.map(s => s.content).join('\n\n').trim();
    if (text) messages.push({ id: fingerprint('assistant', index, text), role: 'assistant', text, segments });
  });
  return messages;
}

function linksFor(selectors: string[]): string[] {
  const links = new Set<string>();
  for (const selector of selectors) {
    document.querySelectorAll(selector).forEach(node => {
      const href = (node as HTMLAnchorElement).href;
      if (href) links.add(href.split('#')[0].split('?')[0]);
    });
  }
  return Array.from(links);
}

function makeAdapter(config: AdapterConfig): PlatformAdapter {
  return {
    sourceApp: config.sourceApp,
    label: config.label,
    color: config.color,
    detectChatTitle: () => (document.title || `${config.label} conversation`).replace(config.titleStrip, '').trim(),
    detectPlatform: () => config.sourceApp,
    getChatID: () => extractConversationId(location.href, config.sourceApp) || location.href.split('#')[0].split('?')[0],
    getConversationLinks: () => linksFor(config.linkSelectors),
    extractMessages: root => buildMessages(root, config.userSelectors, config.assistantSelectors),
  };
}

export const PLATFORM_ADAPTERS: Record<SourceApp, PlatformAdapter> = {
  chatgpt: makeAdapter({
    sourceApp: 'chatgpt',
    label: 'ChatGPT',
    color: '#10a37f',
    userSelectors: ["[data-message-author-role='user']"],
    assistantSelectors: ["[data-message-author-role='assistant']"],
    linkSelectors: ['nav a[href*="/c/"]'],
    titleStrip: / - (ChatGPT|OpenAI).*$/,
  }),
  claude: makeAdapter({
    sourceApp: 'claude',
    label: 'Claude',
    color: '#d97706',
    userSelectors: ['[data-testid="user-message"]', '.human-turn p', '[class*="HumanMessage"]', '[class*="UserMessage"]'],
    assistantSelectors: ['.font-claude-message', '[data-testid="assistant-message"]', '.assistant-message', '[class*="AssistantMessage"]'],
    linkSelectors: ['nav a[href*="/chat/"]', '[data-testid="history-item"] a'],
    titleStrip: / - Claude.*$/,
  }),
  gemini: makeAdapter({
    sourceApp: 'gemini',
    label: 'Gemini',
    color: '#4285f4',
    userSelectors: ['.query-text', '.user-query-bubble-with-background', 'query-text', '[class*="QueryText"]'],
    assistantSelectors: ['model-response .markdown', 'model-response', '.model-response-text', '[class*="response-content"]', 'ms-text-chunk'],
    linkSelectors: ['nav a[href*="/app/"]', '.recent-conversations a', 'a[href*="/app/"]'],
    titleStrip: / - Gemini.*$/,
  }),
  perplexity: makeAdapter({
    sourceApp: 'perplexity',
    label: 'Perplexity',
    color: '#1fb8cd',
    userSelectors: ['[class*="QueryText"]', '.query-display', '[data-testid="query"]', 'h1.line-clamp-2'],
    assistantSelectors: ['[class*="prose"]', '.answer-content', '[data-testid="answer"]', '[class*="AnswerBody"]', '.col-span-8 .prose'],
    linkSelectors: ['nav a[href*="/search/"]', 'a[href*="/search/"]'],
    titleStrip: / - Perplexity.*$/,
  }),
  grok: makeAdapter({
    sourceApp: 'grok',
    label: 'Grok',
    color: '#ffffff',
    userSelectors: ['[data-testid="user-message"]', '.message-bubble.user', '[class*="UserMessage"]', '[class*="human-message"]'],
    assistantSelectors: ['[data-testid="message-content"]', '.message-bubble.ai', '[class*="AssistantMessage"]', '[class*="grok-response"]', '.prose'],
    linkSelectors: ['nav a[href*="/chat/"]', 'nav a[href*="/conversation/"]', 'a[href*="/chat/"]'],
    titleStrip: / - Grok.*$/,
  }),
  web: makeAdapter({
    sourceApp: 'web',
    label: 'Web',
    color: '#888888',
    userSelectors: [],
    assistantSelectors: [],
    linkSelectors: [],
    titleStrip: /$/,
  }),
};

export function detectPlatformAdapter(): PlatformAdapter | null {
  const host = location.hostname;
  if (host.includes('chat.openai.com') || host.includes('chatgpt.com')) return PLATFORM_ADAPTERS.chatgpt;
  if (host.includes('claude.ai')) return PLATFORM_ADAPTERS.claude;
  if (host.includes('gemini.google.com') || host.includes('bard.google.com')) return PLATFORM_ADAPTERS.gemini;
  if (host.includes('perplexity.ai')) return PLATFORM_ADAPTERS.perplexity;
  if (host.includes('grok.com') || host.includes('x.ai')) return PLATFORM_ADAPTERS.grok;
  return null;
}
