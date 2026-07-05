import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as d3 from 'd3';
import { api, AltitudePoint } from '../api';

interface ChartPoint {
  date: Date;
  bytes: number;
  mb: number;
  captures: number;
  deletes: number;
}

interface Props {
  daysBack?: number;
}

function formatMb(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb >= 10 ? `${Math.round(mb)} MB` : `${mb.toFixed(1)} MB`;
}

export function AltitudeChart({ daysBack = 7 }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [points, setPoints] = useState<ChartPoint[]>([]);
  const [wkChange, setWkChange] = useState<number>(0);
  const [totalBytes, setTotalBytes] = useState(0);
  const [totalCaptures, setTotalCaptures] = useState(0);
  const [totalDeletes, setTotalDeletes] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);

  const fetchData = async () => {
    setRefreshing(true);
    try {
      const r = await api.altitude(daysBack);
      const next = (r.points || []).map((p: AltitudePoint) => ({
        date: new Date(`${p.date}T00:00:00`),
        bytes: p.bytes,
        mb: p.bytes / (1024 * 1024),
        captures: p.captures,
        deletes: p.deletes || 0,
      }));

      setPoints(next);
      setWkChange(r.weekOverWeekPct || 0);
      setTotalBytes(r.totalBytes || 0);
      setTotalCaptures(r.totalCaptures || 0);
      setTotalDeletes(next.reduce((s, p) => s + p.deletes, 0));
      setLoadError(null);
    } catch (err) {
      setPoints([]);
      setTotalBytes(0);
      setTotalCaptures(0);
      setTotalDeletes(0);
      setWkChange(0);
      setLoadError((err as Error).message || 'Unable to load altitude data');
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
    const id = window.setInterval(fetchData, 15000);
    return () => window.clearInterval(id);
  }, [daysBack]);

  useEffect(() => {
    if (!svgRef.current || !wrapRef.current || points.length === 0) return;

    const wrap = wrapRef.current.getBoundingClientRect();
    const W = Math.max(320, wrap.width);
    const H = 220;
    const M = { top: 20, right: 16, bottom: 30, left: 48 };
    const innerW = W - M.left - M.right;
    const innerH = H - M.top - M.bottom;

    const svg = d3.select(svgRef.current);
    svg.attr('viewBox', `0 0 ${W} ${H}`).attr('width', '100%').attr('height', H);
    svg.selectAll('*').remove();

    const g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`);
    const x = d3.scaleTime()
      .domain([points[0].date, points[points.length - 1].date])
      .range([0, innerW]);

    const yMax = Math.max(0.25, d3.max(points, p => p.mb) ?? 0.25);
    const y = d3.scaleLinear().domain([0, yMax * 1.08]).nice(4).range([innerH, 0]);

    const defs = svg.append('defs');

    // Green gradient fill
    const grad = defs.append('linearGradient')
      .attr('id', 'altitude-grad')
      .attr('x1', '0').attr('y1', '0').attr('x2', '0').attr('y2', '1');
    grad.append('stop').attr('offset', '0%').attr('stop-color', '#34d399').attr('stop-opacity', 0.22);
    grad.append('stop').attr('offset', '65%').attr('stop-color', '#34d399').attr('stop-opacity', 0.06);
    grad.append('stop').attr('offset', '100%').attr('stop-color', '#34d399').attr('stop-opacity', 0);

    // Glow filter for the line
    const filter = defs.append('filter').attr('id', 'alt-glow').attr('x', '-20%').attr('y', '-40%').attr('width', '140%').attr('height', '180%');
    filter.append('feGaussianBlur').attr('stdDeviation', '2.5').attr('result', 'blur');
    const merge = filter.append('feMerge');
    merge.append('feMergeNode').attr('in', 'blur');
    merge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Y axis
    const yAxis = d3.axisLeft(y)
      .ticks(4)
      .tickSize(0)
      .tickFormat(v => `${Number(v).toFixed(Number(v) >= 10 ? 0 : 1)} MB`);

    g.append('g')
      .call(yAxis)
      .call(s => s.select('.domain').remove())
      .call(s => s.selectAll('text')
        .attr('fill', '#3a3a3a')
        .attr('font-size', 10)
        .attr('font-family', 'ui-monospace, "SF Mono", Menlo, monospace'))
      .call(s => s.selectAll('.tick line').remove());

    // Horizontal grid lines
    g.append('g')
      .selectAll('line.grid')
      .data(y.ticks(4))
      .enter()
      .append('line')
      .attr('x1', 0).attr('x2', innerW)
      .attr('y1', d => y(d)).attr('y2', d => y(d))
      .attr('stroke', '#161616');

    // X axis labels
    const tickFmt = d3.timeFormat('%b %d');
    const tickCount = Math.min(daysBack, 5);
    const ticks = d3.scaleTime().domain(x.domain()).ticks(tickCount);

    g.append('g')
      .attr('transform', `translate(0,${innerH})`)
      .call(
        d3.axisBottom(x)
          .tickValues(ticks)
          .tickFormat(d => tickFmt(d as Date).toUpperCase())
          .tickSize(0)
      )
      .call(s => s.select('.domain').remove())
      .selectAll('text')
      .attr('fill', '#3a3a3a')
      .attr('font-size', 10)
      .attr('font-family', 'ui-monospace, "SF Mono", Menlo, monospace')
      .attr('dy', '1.2em');

    // Area fill
    const area = d3.area<ChartPoint>()
      .x(d => x(d.date))
      .y0(innerH)
      .y1(d => y(d.mb))
      .curve(d3.curveMonotoneX);

    // Line
    const line = d3.line<ChartPoint>()
      .x(d => x(d.date))
      .y(d => y(d.mb))
      .curve(d3.curveMonotoneX);

    g.append('path')
      .datum(points)
      .attr('d', area)
      .attr('fill', 'url(#altitude-grad)');

    g.append('path')
      .datum(points)
      .attr('d', line)
      .attr('fill', 'none')
      .attr('stroke', '#34d399')
      .attr('stroke-width', 2)
      .attr('stroke-linecap', 'round')
      .attr('filter', 'url(#alt-glow)');

    // Data points
    g.selectAll('circle.pt')
      .data(points)
      .enter()
      .append('circle')
      .attr('class', 'pt')
      .attr('cx', d => x(d.date))
      .attr('cy', d => y(d.mb))
      .attr('r', 3)
      .attr('fill', '#34d399')
      .attr('stroke', '#0d0d0d')
      .attr('stroke-width', 1.5);

    g.selectAll('circle.del')
      .data(points.filter(d => d.deletes > 0))
      .enter()
      .append('circle')
      .attr('class', 'del')
      .attr('cx', d => x(d.date))
      .attr('cy', d => y(d.mb))
      .attr('r', 5)
      .attr('fill', 'none')
      .attr('stroke', '#ef4444')
      .attr('stroke-width', 1.5)
      .append('title')
      .text(d => `${d.deletes} deleted`);

    // Animated draw-on for the line (left → right reveal)
    const pathEl = (svgRef.current!.querySelector('path:nth-of-type(2)') as SVGPathElement | null);
    if (pathEl) {
      const len = pathEl.getTotalLength?.() ?? 0;
      if (len > 0) {
        d3.select(pathEl)
          .attr('stroke-dasharray', `${len} ${len}`)
          .attr('stroke-dashoffset', len)
          .transition().duration(900).ease(d3.easeCubicOut)
          .attr('stroke-dashoffset', 0);
      }
    }
  }, [points]);

  const peakDay = useMemo(
    () => points.reduce<ChartPoint | null>((best, p) => (!best || p.bytes > best.bytes ? p : best), null),
    [points]
  );

  const hasData = points.length > 0;

  return (
    <div ref={wrapRef} style={{
      background: '#0d0d0d',
      border: '1px solid #161616',
      borderRadius: 9,
      padding: 18,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 13, color: '#fff', fontWeight: 500 }}>
            Altitude · {daysBack} days
          </div>
          <div style={{ marginTop: 3, fontSize: 11, color: '#666' }}>
            Captured data volume over time
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{
            fontSize: 11,
            color: wkChange >= 0 ? '#22c55e' : '#ef4444',
            fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
          }}>
            {wkChange >= 0 ? '+' : ''}{wkChange}% wk/wk
          </span>
          <button
            onClick={fetchData}
            disabled={refreshing}
            style={{
              background: 'none', border: '1px solid #1f1f1f', borderRadius: 5,
              padding: '4px 9px', fontSize: 10, color: '#666',
              cursor: refreshing ? 'wait' : 'pointer',
              fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
              opacity: refreshing ? 0.5 : 1,
            }}
            title="Refresh"
          >
            {refreshing ? '…' : '↻'}
          </button>
        </div>
      </div>

      {hasData ? (
        <svg ref={svgRef} />
      ) : (
        <div style={{
          height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#3a3a3a', fontSize: 12,
          fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
          borderTop: '1px solid #111', borderBottom: '1px solid #111',
        }}>
          {refreshing ? 'Loading…' : (loadError ? 'No live altitude data' : 'No captures in this range')}
        </div>
      )}

      <div style={{ marginTop: 8, fontSize: 10, color: '#3a3a3a', fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace' }}>
        {hasData
          ? `${formatMb(totalBytes)} across ${totalCaptures} captures${peakDay ? ` · peak ${formatMb(peakDay.bytes)}/day` : ''}`
          : '0 MB across 0 captures'}
        {totalDeletes > 0 && <span style={{ color: '#6b1f1f', marginLeft: 8 }}>· {totalDeletes} deleted</span>}
      </div>
    </div>
  );
}
