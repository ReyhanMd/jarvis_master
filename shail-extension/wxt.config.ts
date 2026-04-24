import { defineConfig } from 'wxt';

export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  manifest: {
    name: 'SHAIL Memory Watchdog',
    description: 'Passively captures your AI conversations and web browsing. Search and inject context back into any AI chat.',
    version: '0.1.0',
    permissions: ['tabs', 'activeTab', 'storage', 'scripting', 'sidePanel'],
    host_permissions: ['<all_urls>'],
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
    },
  },
});
