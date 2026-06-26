import type { SvgChartPayload, ChartSeries } from '../../types/contracts';

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

function readEmbeddedConfig(svg: SVGElement): unknown | null {
  const script = svg.querySelector('script[type="application/json"]');
  if (!script?.textContent) return null;
  try {
    return JSON.parse(script.textContent);
  } catch {
    return null;
  }
}

function nearestTitle(svg: SVGElement): string | undefined {
  const titleEl = svg.querySelector('title');
  if (titleEl?.textContent?.trim()) return titleEl.textContent.trim();
  const aria = svg.getAttribute('aria-label');
  if (aria?.trim()) return aria.trim();
  let prev: Element | null = svg.previousElementSibling;
  while (prev) {
    if (/^H[1-6]$/.test(prev.tagName)) return prev.textContent?.trim() || undefined;
    prev = prev.previousElementSibling;
  }
  return undefined;
}

function detectChartType(svg: SVGElement): string | undefined {
  if (svg.querySelector('rect[height]')) return 'bar';
  if (svg.querySelector('path[d]')) return 'line_or_area';
  if (svg.querySelector('circle[cx]')) return 'scatter_or_pie';
  return undefined;
}

export function extractSvgCharts(root: ParentNode = document): SvgChartPayload[] {
  const svgs = Array.from(root.querySelectorAll<SVGElement>('svg'));
  const out: SvgChartPayload[] = [];
  for (const svg of svgs) {
    const rect = (svg as unknown as SVGGraphicsElement).getBoundingClientRect?.();
    if (!rect || rect.width < 120 || rect.height < 80) continue;
    const texts = Array.from(svg.querySelectorAll('text'))
      .map(t => (t.textContent || '').trim())
      .filter(Boolean);
    if (texts.length < 3) continue;
    const config = readEmbeddedConfig(svg) as Record<string, unknown> | null;
    let series: ChartSeries[] = [];
    if (config && Array.isArray((config as { series?: unknown[] }).series)) {
      series = ((config as { series: unknown[] }).series as Array<Record<string, unknown>>).map(s => ({
        name: typeof s.name === 'string' ? s.name : undefined,
        values: Array.isArray(s.data) ? (s.data as (number | string)[]) : undefined,
      }));
    }
    const legend = Array.from(svg.querySelectorAll('[class*="legend" i] text'))
      .map(n => (n.textContent || '').trim())
      .filter(Boolean);
    const axisX = Array.from(svg.querySelectorAll('[class*="x" i][class*="axis" i] text'))
      .map(n => (n.textContent || '').trim())
      .filter(Boolean);
    const axisY = Array.from(svg.querySelectorAll('[class*="y" i][class*="axis" i] text'))
      .map(n => (n.textContent || '').trim())
      .filter(Boolean);
    out.push({
      title: nearestTitle(svg),
      chart_type: detectChartType(svg),
      x_axis: axisX.join(', ') || undefined,
      y_axis: axisY.join(', ') || undefined,
      legend: legend.length ? legend : undefined,
      series: series.length ? series : undefined,
      source_locator: cssPath(svg),
      capture_confidence: series.length ? 'complete' : 'partial',
    });
  }
  return out;
}
