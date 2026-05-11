import React, { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { api, AscentListResponse } from '../api';
import { AccountBar } from './AccountBar';
import { flag } from '../lib/featureFlags';

const PRIMARY_NAV = [
  { to: '/',         label: 'Today',    icon: '◐' },
  { to: '/ascents',  label: 'Ascents',  icon: '△' },
  { to: '/routes',   label: 'Routes',   icon: '∿' },
  { to: '/horizon',  label: flag('ui_v2') ? 'Replay' : 'Horizon',  icon: '◇' },
];

const SECONDARY_NAV = [
  { to: '/chat',        label: 'Chat',         icon: '◈' },
  { to: '/memories',    label: 'Memories',     icon: '◯' },
  { to: '/graph',       label: 'Graph',        icon: '⬡' },
  { to: '/graphify',    label: 'Graphify',     icon: '◈' },
  { to: '/connections', label: 'Connections',  icon: '⊕' },
  { to: '/services',    label: 'Services',     icon: '◉' },
  { to: '/export',      label: 'Export',       icon: '↓' },
  { to: '/settings',    label: 'Settings',     icon: '⚙' },
];

interface Counts {
  today: number | null;
  ascents: number | null;
  routes: number | null;
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [counts, setCounts] = useState<Counts>({ today: null, ascents: null, routes: null });

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const todayStart = new Date();
        todayStart.setHours(0, 0, 0, 0);
        const [searchResp, ascentsResp, routesResp] = await Promise.all([
          api.search({ query: '', k: 100, after: todayStart.toISOString() }).catch(() => ({ items: [], total: 0 })),
          api.listAscents().catch(() => ({ items: [], active_count: 0, limit: 5, tier: 'free' } as AscentListResponse)),
          api.routes().catch(() => ({ routes: [], total_clusters: 0 })),
        ]);
        if (!alive) return;
        setCounts({
          today: searchResp.items.length,
          ascents: ascentsResp.active_count,
          routes: routesResp.total_clusters ?? routesResp.routes.length,
        });
      } catch { /* ignore — sidebar isn't critical */ }
    };
    tick();
    const id = setInterval(tick, 60_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  return (
    <aside
      style={{
        width: collapsed ? 56 : 220,
        minWidth: collapsed ? 56 : 220,
        background: '#080808',
        borderRight: '1px solid #1a1a1a',
        display: 'flex',
        flexDirection: 'column',
        transition: 'width 0.15s ease',
        overflow: 'hidden',
      }}
    >
      {/* Logo row */}
      <div style={{
        padding: collapsed ? '20px 0' : '20px 18px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: collapsed ? 'center' : 'space-between',
        gap: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <img
            src="/dashboard/logo.png"
            alt=""
            width={collapsed ? 24 : 26}
            height={collapsed ? 24 : 26}
            style={{ borderRadius: 5, flexShrink: 0, objectFit: 'cover' }}
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
          />
          {!collapsed && (
            <span style={{
              color: '#fff',
              fontSize: 14,
              fontWeight: 600,
              letterSpacing: '0.04em',
              fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
            }}>
              SHAIL
            </span>
          )}
        </div>
        {!collapsed && (
          <button
            onClick={() => setCollapsed(true)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#3a3a3a', fontSize: 14, padding: 4, lineHeight: 1 }}
            title="Collapse"
          >
            ‹
          </button>
        )}
        {collapsed && (
          <button
            onClick={() => setCollapsed(false)}
            style={{ position: 'absolute', top: 22, left: 32, background: 'none', border: 'none', cursor: 'pointer', color: '#3a3a3a', fontSize: 12 }}
            title="Expand"
          >›</button>
        )}
      </div>

      {/* BASECAMP section label */}
      {!collapsed && (
        <div style={{
          padding: '12px 20px 6px',
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.12em',
          color: '#3a3a3a',
          fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
        }}>
          BASECAMP
        </div>
      )}

      {/* Primary nav (with counts) */}
      <nav style={{ padding: '2px 0' }}>
        {PRIMARY_NAV.map(({ to, label, icon }) => {
          const count =
            to === '/'        ? counts.today :
            to === '/ascents' ? counts.ascents :
            to === '/routes'  ? counts.routes :
            null;
          return (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              style={({ isActive }) => ({
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: collapsed ? '9px 0' : '9px 20px',
                justifyContent: collapsed ? 'center' : 'space-between',
                textDecoration: 'none',
                fontSize: 13,
                fontWeight: 450,
                color: isActive ? '#fff' : '#666',
                background: isActive ? '#111' : 'transparent',
                borderLeft: isActive ? '2.5px solid #fff' : '2.5px solid transparent',
                transition: 'color 0.1s, background 0.1s',
                whiteSpace: 'nowrap',
              })}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
                <span style={{ fontSize: 14, lineHeight: 1, flexShrink: 0 }}>{icon}</span>
                {!collapsed && <span>{label}</span>}
              </span>
              {!collapsed && count !== null && (
                <span style={{
                  fontSize: 10,
                  color: '#444',
                  fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
                }}>
                  {to === '/horizon' ? '—' : count}
                </span>
              )}
              {!collapsed && to === '/horizon' && false}
            </NavLink>
          );
        })}
      </nav>

      {/* Divider */}
      <div style={{ height: 18 }} />
      {!collapsed && (
        <div style={{
          padding: '0 20px 6px',
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.12em',
          color: '#3a3a3a',
          fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
        }}>
          WORKBENCH
        </div>
      )}

      {/* Secondary nav */}
      <nav style={{ flex: 1, padding: '2px 0', overflowY: 'auto' }}>
        {SECONDARY_NAV.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: collapsed ? '9px 0' : '9px 20px',
              justifyContent: collapsed ? 'center' : 'flex-start',
              textDecoration: 'none',
              fontSize: 13,
              fontWeight: 450,
              color: isActive ? '#fff' : '#555',
              background: isActive ? '#111' : 'transparent',
              borderLeft: isActive ? '2.5px solid #fff' : '2.5px solid transparent',
              transition: 'color 0.1s, background 0.1s',
              whiteSpace: 'nowrap',
            })}
          >
            <span style={{ fontSize: 14, lineHeight: 1, flexShrink: 0 }}>{icon}</span>
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Account bar */}
      <AccountBar collapsed={collapsed} />
    </aside>
  );
}
