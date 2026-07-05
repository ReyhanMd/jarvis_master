import {
  buildGithubDiffCandidate,
  isCaptureAllowed,
  observeWithStability,
  sendCapture,
} from '../src/lib/capture';
import { showCapturePrompt } from '../src/lib/notify';
import type { GithubDiffPayload, GithubFile, GithubHunk, GithubHunkLine } from '../src/types/contracts';

const PR_PATH_RE = /^\/([^/]+)\/([^/]+)\/pull\/(\d+)\/?(files)?/;

function parsePrUrl(): { owner: string; repo: string; pr: number } | null {
  const match = location.pathname.match(PR_PATH_RE);
  if (!match) return null;
  return { owner: match[1], repo: match[2], pr: Number(match[3]) };
}

function parseHunkHeader(header: string): { fromStart: number; toStart: number } | null {
  const match = header.match(/@@\s*-(\d+),?\d*\s*\+(\d+),?\d*\s*@@/);
  if (!match) return null;
  return { fromStart: Number(match[1]), toStart: Number(match[2]) };
}

function readShasFromDom(): { base?: string; head?: string } {
  const baseEl = document.querySelector<HTMLElement>('[data-base-ref-sha]');
  const headEl = document.querySelector<HTMLElement>('[data-head-ref-sha]');
  return {
    base: baseEl?.getAttribute('data-base-ref-sha') || undefined,
    head: headEl?.getAttribute('data-head-ref-sha') || undefined,
  };
}

function extractFromDom(owner: string, repo: string, pr: number): GithubDiffPayload | null {
  const fileBlocks = Array.from(document.querySelectorAll<HTMLElement>('div.file, [data-file-type]'));
  if (!fileBlocks.length) return null;
  const files: GithubFile[] = [];
  const renderedParts: string[] = [];
  for (const block of fileBlocks) {
    const pathEl = block.querySelector<HTMLElement>('[data-path], .file-info a, .file-header [title]');
    const path = (
      pathEl?.getAttribute('data-path') ||
      pathEl?.getAttribute('title') ||
      pathEl?.textContent ||
      ''
    ).trim();
    if (!path) continue;
    const hunks: GithubHunk[] = [];
    const hunkRows = Array.from(block.querySelectorAll<HTMLElement>('tr.js-expandable-line, tr.diff-line, tr'));
    let current: GithubHunk | null = null;
    for (const row of hunkRows) {
      const text = (row.textContent || '').replace(/\s+$/, '');
      if (!text) continue;
      const isHeader = row.classList.contains('js-expandable-line') ||
        text.startsWith('@@') || row.classList.contains('blob-expanded');
      if (isHeader && text.includes('@@')) {
        if (current) hunks.push(current);
        current = { header: text, lines: [] };
        continue;
      }
      if (!current) continue;
      const cls = row.className || '';
      let kind: GithubHunkLine['kind'] = ' ';
      if (cls.includes('addition') || cls.includes('blob-code-addition')) kind = '+';
      else if (cls.includes('deletion') || cls.includes('blob-code-deletion')) kind = '-';
      const codeCell = row.querySelector<HTMLElement>('td.blob-code, td[data-code-marker]');
      const lineText = (codeCell?.textContent || text).replace(/^\s/, '');
      current.lines.push({ kind, text: lineText });
    }
    if (current) hunks.push(current);
    if (!hunks.length) continue;
    const fileText = hunks
      .map(h => [h.header, ...h.lines.map(l => `${l.kind}${l.text}`)].join('\n'))
      .join('\n');
    files.push({ path, hunks, patch_text: fileText });
    renderedParts.push(`diff --git a/${path} b/${path}\n${fileText}`);
  }
  if (!files.length) return null;
  const { base, head } = readShasFromDom();
  return {
    owner,
    repo,
    pr_number: pr,
    base_sha: base,
    head_sha: head,
    files,
    rendered_patch: renderedParts.join('\n'),
  };
}

async function fetchFromApi(owner: string, repo: string, pr: number): Promise<GithubDiffPayload | null> {
  try {
    const filesResp = await fetch(`https://api.github.com/repos/${owner}/${repo}/pulls/${pr}/files?per_page=100`, {
      headers: { Accept: 'application/vnd.github+json' },
      credentials: 'omit',
    });
    if (!filesResp.ok) return null;
    const filesJson = (await filesResp.json()) as Array<{
      filename: string;
      status: string;
      patch?: string;
    }>;
    const prResp = await fetch(`https://api.github.com/repos/${owner}/${repo}/pulls/${pr}`, {
      headers: { Accept: 'application/vnd.github+json' },
      credentials: 'omit',
    });
    const prJson = prResp.ok ? ((await prResp.json()) as { base?: { sha?: string }; head?: { sha?: string } }) : {};
    const files: GithubFile[] = filesJson.map(f => {
      const hunks: GithubHunk[] = [];
      if (f.patch) {
        let current: GithubHunk | null = null;
        for (const line of f.patch.split('\n')) {
          if (line.startsWith('@@')) {
            if (current) hunks.push(current);
            current = { header: line, lines: [] };
            continue;
          }
          if (!current) continue;
          const ch = line.charAt(0);
          const kind: GithubHunkLine['kind'] = ch === '+' ? '+' : ch === '-' ? '-' : ' ';
          current.lines.push({ kind, text: line.slice(1) });
        }
        if (current) hunks.push(current);
      }
      return { path: f.filename, status: f.status, hunks, patch_text: f.patch };
    });
    return {
      owner,
      repo,
      pr_number: pr,
      base_sha: prJson.base?.sha,
      head_sha: prJson.head?.sha,
      files,
      rendered_patch: filesJson
        .map(f => `diff --git a/${f.filename} b/${f.filename}\n${f.patch || ''}`)
        .join('\n'),
    };
  } catch {
    return null;
  }
}

export default defineContentScript({
  matches: ['https://github.com/*/*/pull/*'],
  runAt: 'document_idle',

  main() {
    let lastSig = '';
    let captured = false;
    let stopObs: (() => void) | null = null;

    async function tryCapture() {
      if (captured) return;
      if (!(await isCaptureAllowed(location.href))) return;
      const meta = parsePrUrl();
      if (!meta) return;
      let diff = await fetchFromApi(meta.owner, meta.repo, meta.pr);
      if (!diff || !diff.files.length) {
        diff = extractFromDom(meta.owner, meta.repo, meta.pr);
      }
      if (!diff || !diff.files.length) return;
      const sig = `${meta.owner}/${meta.repo}#${meta.pr}@${diff.head_sha || ''}:${diff.files.length}`;
      if (sig === lastSig) return;
      lastSig = sig;

      const candidate = await buildGithubDiffCandidate(diff);
      showCapturePrompt({
        title: document.title || `${meta.owner}/${meta.repo}#${meta.pr}`,
        sourceApp: 'web',
        onSave: async () => {
          captured = true;
          await sendCapture(candidate);
        },
        onSkip: () => {
          captured = true;
        },
      });
    }

    setTimeout(() => { void tryCapture(); }, 1500);
    stopObs = observeWithStability(document.body, () => { void tryCapture(); }, 1500);
    window.addEventListener('beforeunload', () => stopObs?.());
  },
});
