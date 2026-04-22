/**
 * Cardboard – theme management and player avatar helpers
 *
 * No dependencies on state. Loaded before app.js.
 */

// ===== Player Avatar Helpers =====

const _AVATAR_PALETTE = ['#e05c5c','#e0875c','#d4c44a','#5ca85c','#5cb8e0','#5c7ae0','#a05ce0','#e05ca8'];

function playerAvatarColor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return _AVATAR_PALETTE[hash % _AVATAR_PALETTE.length];
}

function playerInitials(name) {
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

// ===== Theme =====

const THEME_KEY     = 'cardboard_theme';
const THEME_SET_KEY = 'cardboard_theme_manual'; // set when user explicitly chose a theme

function applyTheme(isLight) {
  if (isLight) {
    document.documentElement.setAttribute('data-theme', 'light');
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
}

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  const userSet = localStorage.getItem(THEME_SET_KEY);
  if (saved && userSet) {
    // User previously made an explicit choice — respect it
    applyTheme(saved === 'light');
  } else {
    // No manual choice — follow OS preference
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    applyTheme(!prefersDark);
  }
  // Listen for OS changes and follow automatically if user hasn't set manually
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
      if (!localStorage.getItem(THEME_SET_KEY)) {
        applyTheme(!e.matches);
      }
    });
  }
}

function bindThemeToggle() {
  const btn = document.getElementById('theme-toggle-btn');
  if (!btn) return;
  const update = () => {
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    btn.title = isLight ? 'Switch to dark mode' : 'Switch to light mode';
  };
  update();
  btn.addEventListener('click', () => {
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    const goLight = !isLight;

    const doApply = () => { applyTheme(goLight); update(); };

    if (document.startViewTransition) {
      // View Transitions API — native cross-fade (Chrome / Edge).
      // Suppress element-level CSS transitions during the cross-fade to prevent
      // double-animation flicker (elements reacting to custom-property changes
      // while the page-level overlay is also animating).
      document.documentElement.classList.add('view-transitioning');
      const vt = document.startViewTransition(doApply);
      vt.finished.then(() => document.documentElement.classList.remove('view-transitioning'));
    } else {
      // Fallback for Safari / Firefox — fade body out, swap, fade back in
      const body = document.body;
      body.style.transition = 'opacity 180ms ease';
      body.style.opacity = '0.01';
      setTimeout(() => {
        doApply();
        body.style.opacity = '';
        setTimeout(() => { body.style.transition = ''; }, 200);
      }, 180);
    }

    localStorage.setItem(THEME_KEY, goLight ? 'light' : 'dark');
    localStorage.setItem(THEME_SET_KEY, '1');
  });
}
