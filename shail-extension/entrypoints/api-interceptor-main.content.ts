import { installApiInterceptor } from '../src/lib/api-interceptor';

export default defineContentScript({
  matches: [
    'https://chat.openai.com/*',
    'https://chatgpt.com/*',
    'https://claude.ai/*',
    'https://gemini.google.com/*',
    'https://www.perplexity.ai/*',
    'https://perplexity.ai/*',
    'https://grok.com/*',
    'https://x.ai/*',
  ],
  runAt: 'document_start',
  world: 'MAIN',

  main() {
    installApiInterceptor();
  },
});
