import type { DashboardCardPayload } from '../../types/contracts';

const NUMERIC_RE = /-?\$?\d{1,3}(?:[,\d]*)(?:\.\d+)?\s*[%kKmMbB]?/;
const DELTA_RE = /([+\-▲▼])\s*\$?\d[\d,\.]*\s*[%kKmMbB]?/;

function cssPath(el: Element): string {
  const parts: string[] = [];
  let cur: Element | null = el;
  while (cur && cur.nodeType === Node.ELEMENT_NODE && parts.length < 6) {
    let part = cur.tagName.toLowerCase();
    if (cur.id) {
      part += `#${cur.id}`;
      parts.unshift(part);
      break;
    }
    parts.unshift(part);
    cur = cur.parentElement;
  }
  return parts.join(' > ');
}

function parseValueNum(text: string): number | null {
  const match = text.match(NUMERIC_RE);
  if (!match) return null;
  const raw = match[0].replace(/[,$]/g, '').trim();
  const mult = raw.endsWith('k') || raw.endsWith('K') ? 1e3
    : raw.endsWith('m') || raw.endsWith('M') ? 1e6
    : raw.endsWith('b') || raw.endsWith('B') ? 1e9
    : 1;
  const stripped = raw.replace(/[%kKmMbB]$/, '');
  const num = Number(stripped);
  return Number.isFinite(num) ? num * mult : null;
}

function unitOf(text: string): string | undefined {
  if (text.includes('%')) return '%';
  if (text.includes('$')) return 'USD';
  const tail = text.match(/[kKmMbB]\b/);
  return tail?.[0]?.toUpperCase();
}

function nearestSection(el: Element): string | undefined {
  let cur: Element | null = el;
  while (cur) {
    const heading = cur.querySelector('h1,h2,h3,h4');
    if (heading?.textContent?.trim()) return heading.textContent.trim();
    cur = cur.parentElement;
    if (cur && cur.tagName === 'BODY') break;
  }
  return undefined;
}

export function extractDashboardCards(root: ParentNode = document): DashboardCardPayload[] {
  const candidates = Array.from(
    root.querySelectorAll<HTMLElement>('[role="figure"], [data-testid*="card"], [class*="card"], [class*="Card"], [class*="metric"], [class*="Metric"], [class*="stat"], [class*="Stat"]'),
  );
  const cards: DashboardCardPayload[] = [];
  for (const el of candidates) {
    const text = (el.innerText || '').trim();
    if (!text || text.length > 600) continue;
    if (!NUMERIC_RE.test(text)) continue;
    const lines = text.split('\n').map(s => s.trim()).filter(Boolean);
    if (lines.length < 2 || lines.length > 8) continue;
    const primary = lines.find(l => NUMERIC_RE.test(l));
    if (!primary) continue;
    const titleLine = lines.find(l => l !== primary && !DELTA_RE.test(l));
    const deltaLine = lines.find(l => DELTA_RE.test(l) && l !== primary);
    cards.push({
      section_title: nearestSection(el),
      card_title: titleLine,
      primary_value: primary,
      value_num: parseValueNum(primary),
      unit: unitOf(primary),
      delta_value: deltaLine,
      delta_unit: deltaLine ? unitOf(deltaLine) : undefined,
      time_window: lines.find(l => /\b(today|week|month|quarter|year|YTD|MTD|QTD|24h|7d|30d|90d)\b/i.test(l)),
      subtitle: lines.find(l => l !== titleLine && l !== primary && l !== deltaLine),
      source_locator: cssPath(el),
    });
  }
  return cards;
}
