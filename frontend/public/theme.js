// applies the stored theme class before the page renders, to prevent a flash of the wrong theme during hydration. It also sets
// the colour of the browser chrome (theme-color) for the chosen theme. The two colours are those of lib/theme.ts (THEME_COLOR).
// This is a file and not inline script so that the dashboard's content security policy can forbid inline script.
(function () {
  // a theme the visitor picked with the switch wins. Without one the page follows the system setting, so nobody is put in a
  // dark theme they did not ask for. Dark stays the fallback when neither can be read.
  var stored = null;
  try {
    stored = localStorage.getItem('theme');
  } catch (e) {
    // storage can be blocked: the system setting decides
  }
  var light = stored === 'light';
  if (stored !== 'light' && stored !== 'dark') {
    try {
      light = window.matchMedia('(prefers-color-scheme: light)').matches;
    } catch (e) {
      light = false;
    }
  }
  var root = document.documentElement;
  if (light) {
    root.classList.remove('dark');
  } else {
    root.classList.add('dark');
  }
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', light ? '#f7f8f9' : '#0b0c0e');
})();
