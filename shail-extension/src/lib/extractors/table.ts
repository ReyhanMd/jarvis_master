import type { HtmlTablePayload } from '../../types/contracts';

const NUMERIC_RE = /^-?\$?\d{1,3}(?:[,\d]*)(?:\.\d+)?\s*[%kKmMbB]?$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}|\d{1,2}\/\d{1,2}\/\d{2,4}/;

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
    const parent: Element | null = cur.parentElement as Element | null;
    if (parent) {
      const tagName = cur.tagName;
      const siblings = Array.from(parent.children as unknown as Element[]);
      const same = siblings.filter(c => c.tagName === tagName);
      if (same.length > 1) part += `:nth-of-type(${same.indexOf(cur) + 1})`;
    }
    parts.unshift(part);
    cur = parent;
  }
  return parts.join(' > ');
}

function inferType(values: string[]): string {
  if (!values.length) return 'text';
  const numericHits = values.filter(v => NUMERIC_RE.test(v.trim())).length;
  if (numericHits / values.length >= 0.6) return 'numeric';
  const dateHits = values.filter(v => DATE_RE.test(v.trim())).length;
  if (dateHits / values.length >= 0.6) return 'date';
  return 'text';
}

function nearestTitle(table: HTMLTableElement): string | undefined {
  const caption = table.querySelector('caption');
  if (caption?.textContent?.trim()) return caption.textContent.trim();
  let prev = table.previousElementSibling;
  while (prev) {
    if (/^H[1-6]$/.test(prev.tagName)) return prev.textContent?.trim() || undefined;
    prev = prev.previousElementSibling;
  }
  const parentHeader = table.closest('section,article,div')?.querySelector('h1,h2,h3,h4');
  if (parentHeader?.textContent?.trim()) return parentHeader.textContent.trim();
  return undefined;
}

function rowCells(row: HTMLTableRowElement): string[] {
  return Array.from(row.cells).map(cell => (cell.textContent || '').trim());
}

export function extractHtmlTables(root: ParentNode = document): HtmlTablePayload[] {
  const tables = Array.from(root.querySelectorAll<HTMLTableElement>('table'));
  const out: HtmlTablePayload[] = [];
  for (const table of tables) {
    const allRows = Array.from(table.rows);
    if (allRows.length < 2) continue;
    const headerCells = allRows[0].cells;
    if (headerCells.length < 2) continue;
    const columns = rowCells(allRows[0]);
    const dataRows = allRows.slice(1).map(rowCells).filter(r => r.length === columns.length);
    if (!dataRows.length) continue;
    const columnTypes = columns.map((_, idx) =>
      inferType(dataRows.map(r => r[idx] || '')),
    );
    out.push({
      title: nearestTitle(table),
      columns,
      rows: dataRows,
      column_types: columnTypes,
      source_locator: cssPath(table),
      header_depth: 1,
    });
  }
  return out;
}
