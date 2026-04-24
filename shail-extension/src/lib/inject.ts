/**
 * inject.ts — resolves the active AI composer on the current page and
 * inserts text, firing the synthetic events React/Vue/Quill need to
 * register the change.
 */

type Site = 'chatgpt' | 'claude' | 'gemini' | 'perplexity' | 'web';

function detectSite(): Site {
  const h = location.hostname;
  if (h.includes('chatgpt.com') || h.includes('openai.com')) return 'chatgpt';
  if (h.includes('claude.ai')) return 'claude';
  if (h.includes('gemini.google.com')) return 'gemini';
  if (h.includes('perplexity.ai')) return 'perplexity';
  return 'web';
}

function resolveComposer(): HTMLElement | null {
  const site = detectSite();

  switch (site) {
    case 'chatgpt':
      return (
        document.querySelector<HTMLElement>('#prompt-textarea') ??
        document.querySelector<HTMLElement>('textarea[data-id="root"]') ??
        null
      );

    case 'claude':
      return (
        document.querySelector<HTMLElement>('.ProseMirror[contenteditable="true"]') ??
        document.querySelector<HTMLElement>('[contenteditable="true"][data-placeholder]') ??
        null
      );

    case 'gemini':
      return (
        document.querySelector<HTMLElement>('rich-textarea .ql-editor') ??
        document.querySelector<HTMLElement>('.ql-editor[contenteditable="true"]') ??
        null
      );

    case 'perplexity':
      return (
        document.querySelector<HTMLElement>('textarea[placeholder]') ??
        document.querySelector<HTMLElement>('textarea') ??
        null
      );

    default:
      // Generic fallback for any site
      return (
        document.querySelector<HTMLElement>('textarea') ??
        document.querySelector<HTMLElement>('[contenteditable="true"]') ??
        null
      );
  }
}

/**
 * Inserts `text` into the detected composer.
 * Returns true if it found a target, false if no composer was found.
 */
export function injectText(text: string): boolean {
  const el = resolveComposer();
  if (!el) return false;

  el.focus();

  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
    // React tracks value via the native setter — bypass the JS prop directly
    const proto = el.tagName === 'TEXTAREA'
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    const current = (el as HTMLTextAreaElement).value;
    if (nativeSetter) {
      nativeSetter.call(el, current ? `${current}\n${text}` : text);
    } else {
      (el as HTMLTextAreaElement).value = current ? `${current}\n${text}` : text;
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));

  } else if (el.isContentEditable) {
    // ProseMirror / Quill — move caret to end then execCommand
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    sel?.removeAllRanges();
    sel?.addRange(range);

    // Prepend newline if there's existing content
    const prefix = el.textContent?.trim() ? '\n' : '';
    document.execCommand('insertText', false, prefix + text);
  }

  return true;
}
