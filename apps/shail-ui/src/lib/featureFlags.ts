const STORAGE_KEY = 'shail_feature_flags';

type FlagMap = { ui_v2?: boolean };

function read(): FlagMap {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}');
  } catch {
    return {};
  }
}

const GRADUATED: Set<keyof FlagMap> = new Set(['ui_v2']);

export function flag(name: keyof FlagMap): boolean {
  const env = (import.meta.env?.[`VITE_FLAG_${name.toUpperCase()}`] as string | undefined);
  if (env === '1' || env === 'true') return true;
  if (env === '0' || env === 'false') return false;
  const stored = read();
  if (name in stored) return !!stored[name];
  return GRADUATED.has(name);
}

export function setFlag(name: keyof FlagMap, value: boolean): void {
  const cur = read();
  cur[name] = value;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cur));
}
