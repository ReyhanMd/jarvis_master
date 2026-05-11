import { defineConfig } from 'wxt';

export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  manifest: {
    name: 'SHAIL Memory Watchdog',
    description: 'Passively captures your AI conversations and web browsing. Search and inject context back into any AI chat.',
    version: '0.1.0',
    permissions: ['tabs', 'activeTab', 'storage', 'scripting', 'sidePanel'],
    host_permissions: ['<all_urls>', 'http://localhost/*', 'http://127.0.0.1/*'],
    content_security_policy: {
      extension_pages: "script-src 'self'; object-src 'self'; connect-src http://localhost:8000 http://127.0.0.1:8000",
    },
    commands: {
      // Ctrl+Space (Win/Linux) / Control+Space (Mac) → open memory side panel.
      // IMPORTANT: On Mac, Chrome maps "Ctrl" → Command(⌘). To get the real
      // Control key on Mac we must use "MacCtrl". This avoids conflicting with
      // Spotlight (⌘+Space) while matching what ctrlKey=true fires in JS events.
      'open-sidepanel': {
        suggested_key: {
          default: 'Ctrl+Space',
          mac: 'MacCtrl+Space',
        },
        description: 'Open SHAIL memory side panel',
      },
      // Ctrl+Shift+P → toggle capture pause/resume globally.
      // Listed as suggested_key so Chrome falls back gracefully if the slot is
      // taken (e.g. Print Preview on some platforms). Users can rebind via
      // chrome://extensions/shortcuts.
      'toggle-capture': {
        suggested_key: {
          default: 'Ctrl+Shift+P',
          mac: 'MacCtrl+Shift+P',
        },
        description: 'Pause / resume SHAIL capture',
      },
    },
  },
});
