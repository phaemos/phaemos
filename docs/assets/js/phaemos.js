/* Small enhancements. Every page reads in full without this file.
   1. Keyboard controls for the menu button and the theme switch, which the theme builds from labels.
   2. Tables: only a table that really overflows is a scroll region with a name and a hint.
   3. Diagrams: the source sits in the page as text. With script it is drawn as an SVG that follows the theme. The picture is
      one image with a name and a summary beside it, fits the width and opens at full size on request. The drawing library is
      a file of this site and loads only on a page with a diagram. */
(function () {
  var here = document.currentScript ? document.currentScript.src : '';
  var root = here.replace(/js\/phaemos\.js.*$/, '');
  var reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)');

  function press(el, fn) {
    el.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); fn(); }
    });
  }

  /* ---------- 1. menu button and theme switch ---------- */
  var drawer = document.getElementById('__drawer');
  var menu = document.querySelector('label.md-header__button[for="__drawer"]');
  if (drawer && menu) {
    menu.setAttribute('role', 'button');
    menu.setAttribute('tabindex', '0');
    menu.setAttribute('aria-label', 'Navigation menu');
    menu.setAttribute('aria-controls', 'ph-drawer');
    var panel = document.querySelector('.md-sidebar--primary');
    if (panel) panel.id = 'ph-drawer';
    var sync = function () { menu.setAttribute('aria-expanded', drawer.checked ? 'true' : 'false'); };
    sync();
    press(menu, function () { drawer.click(); });
    var leaving = false;
    drawer.addEventListener('change', function () {
      sync();
      if (drawer.checked) {
        var first = document.querySelector('.md-sidebar--primary a[href]');
        if (first) first.focus();
      } else if (!leaving) {
        menu.focus();
      }
    });
    // Tab past the last link of the open drawer closes it, so focus never runs on into the page under the overlay
    if (panel) {
      panel.addEventListener('focusout', function (e) {
        var to = e.relatedTarget;
        if (drawer.checked && to && !panel.contains(to) && to !== menu) {
          leaving = true;
          drawer.click();
          leaving = false;
        }
      });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && drawer.checked) { drawer.click(); }
    });
  }
  var searchBtn = document.querySelector('label.md-header__button[for="__search"]');
  if (searchBtn) {
    searchBtn.setAttribute('role', 'button');
    searchBtn.setAttribute('tabindex', '0');
    searchBtn.setAttribute('aria-label', 'Search');
    press(searchBtn, function () { searchBtn.click(); });
  }
  // the theme switch is a hidden radio and a label. Readers hear a button with the action it does
  var form = document.querySelector('.md-header__option');
  if (form) {
    var radios = form.querySelectorAll('input.md-option');
    for (var r = 0; r < radios.length; r++) { radios[r].setAttribute('tabindex', '-1'); radios[r].setAttribute('aria-hidden', 'true'); }
    var labels = form.querySelectorAll('label');
    for (var l = 0; l < labels.length; l++) {
      labels[l].setAttribute('role', 'button');
      labels[l].setAttribute('tabindex', '0');
      labels[l].setAttribute('aria-label', labels[l].getAttribute('title') || 'Switch theme');
      (function (lab) {
        press(lab, function () {
          // the keyboard sets the other theme itself, then puts focus on the control that is shown next
          var input = document.getElementById(lab.getAttribute('for'));
          if (!input) return;
          input.checked = true;
          input.dispatchEvent(new Event('change', { bubbles: true }));
          setTimeout(function () {
            var shown = form.querySelector('label:not([hidden])');
            if (shown) shown.focus();
          }, 60);
        });
      })(labels[l]);
    }
  }

  /* ---------- 2. tables ---------- */
  function tables() {
    var boxes = document.querySelectorAll('.ph-table-scroll');
    for (var i = 0; i < boxes.length; i++) {
      var box = boxes[i];
      var hint = box.previousElementSibling;
      var has = hint && hint.classList.contains('ph-table-hint');
      var over = box.scrollWidth > box.clientWidth + 1;
      var name = box.getAttribute('data-heading') || 'Table';
      if (over) {
        box.setAttribute('role', 'region');
        box.setAttribute('tabindex', '0');
        box.setAttribute('aria-label', 'Table: ' + name + '. Scrolls sideways for more columns.');
        if (has) hint.hidden = false;
      } else {
        box.removeAttribute('role');
        box.removeAttribute('tabindex');
        box.removeAttribute('aria-label');
        if (has) hint.hidden = true;
      }
    }
  }
  tables();
  window.addEventListener('resize', tables);
  window.addEventListener('load', tables);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(tables);

  /* ---------- 3. diagrams ---------- */
  var blocks = document.querySelectorAll('.ph-diagram');
  if (!blocks.length) return;
  var sources = [];
  for (var b = 0; b < blocks.length; b++) sources.push(blocks[b].textContent);

  // in a sequence diagram a semicolon inside a message ends the statement and stops the drawing. The page text keeps it: the
  // drawing gets the same character as an entity.
  function safe(src) {
    if (!/^\s*sequenceDiagram/.test(src)) return src;
    return src.split('\n').map(function (line) { return /-{1,2}>>?/.test(line) ? line.replace(/;/g, '#59;') : line; }).join('\n');
  }

  function colour(name) { return getComputedStyle(document.body).getPropertyValue(name).trim(); }

  // a diagram is fitted to the width only while its 15 px text stays at 13 px or more on screen (a scale of 0.87). Below that it
  // opens at full size in a scroll box and the fitted view is the option.
  var MIN_SCALE = 0.87;

  function setFull(box, full) {
    var scroll = box.querySelector('.ph-diagram__scroll');
    var btn = box.querySelector('.ph-diagram__zoom');
    var title = box.getAttribute('data-title') || 'Diagram';
    box.classList.toggle('is-full', full);
    btn.setAttribute('aria-pressed', full ? 'true' : 'false');
    if (full) {
      scroll.setAttribute('role', 'region');
      scroll.setAttribute('tabindex', '0');
      scroll.setAttribute('aria-label', title + ', full size. Scroll sideways for more.');
    } else {
      scroll.removeAttribute('role');
      scroll.removeAttribute('tabindex');
      scroll.removeAttribute('aria-label');
    }
    applySize(box);
  }

  function applySize(box) {
    var svg = box.querySelector('svg');
    if (!svg) return;
    var w = parseFloat(svg.getAttribute('data-natural-width'));
    var full = box.classList.contains('is-full');
    svg.style.maxWidth = full ? 'none' : w + 'px';
    svg.style.width = full ? w + 'px' : '100%';
    svg.style.height = 'auto';
  }

  function choose(box) {
    if (box.getAttribute('data-user')) return;
    var svg = box.querySelector('svg');
    var scroll = box.querySelector('.ph-diagram__scroll');
    if (!svg || !scroll) return;
    var w = parseFloat(svg.getAttribute('data-natural-width'));
    setFull(box, scroll.clientWidth / w < MIN_SCALE);
  }
  window.addEventListener('resize', function () { blocks.forEach(choose); });

  function build(el, i) {
    el.setAttribute('data-ready', 'true');
    el.textContent = '';
    var title = el.getAttribute('data-title') || 'Diagram ' + (i + 1);
    var summaryId = el.getAttribute('data-summary-id');
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ph-diagram__zoom';
    btn.setAttribute('aria-pressed', 'false');
    btn.textContent = 'Full size';
    btn.setAttribute('aria-label', 'View at full size');
    var scroll = document.createElement('div');
    scroll.className = 'ph-diagram__scroll';
    var pic = document.createElement('div');
    pic.className = 'ph-diagram__pic';
    pic.setAttribute('role', 'img');
    pic.setAttribute('aria-label', title);
    scroll.appendChild(pic);
    el.appendChild(btn);
    el.appendChild(scroll);
    btn.addEventListener('click', function () {
      el.setAttribute('data-user', 'true');
      setFull(el, !el.classList.contains('is-full'));
    });
    var d = document.createElement('details');
    d.className = 'ph-diagram__text';
    var s = document.createElement('summary');
    s.textContent = 'Diagram as text';
    var pre = document.createElement('pre');
    var code = document.createElement('code');
    code.textContent = sources[i];
    pre.appendChild(code);
    d.appendChild(s);
    d.appendChild(pre);
    el.parentNode.appendChild(d);
  }

  function draw() {
    var m = window.mermaid;
    m.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'base',
      // labels are drawn as SVG text. HTML labels would let diagram source load an image from another site.
      htmlLabels: false,
      fontFamily: 'Manrope, system-ui, sans-serif',
      flowchart: { useMaxWidth: true, htmlLabels: false, wrappingWidth: 200 },
      sequence: { useMaxWidth: true, wrap: true, width: 230, actorMargin: 150, messageMargin: 44, boxMargin: 10, messageFontSize: 15, noteFontSize: 15, actorFontSize: 15 },
      themeVariables: {
        fontSize: '15px',
        background: colour('--ph-bg'),
        mainBkg: colour('--ph-panel'),
        primaryColor: colour('--ph-panel'),
        primaryTextColor: colour('--ph-text'),
        primaryBorderColor: colour('--ph-edge'),
        secondaryColor: colour('--ph-panel'),
        tertiaryColor: colour('--ph-bg'),
        textColor: colour('--ph-text'),
        lineColor: colour('--ph-muted'),
        nodeBorder: colour('--ph-edge'),
        clusterBkg: colour('--ph-bg'),
        clusterBorder: colour('--ph-edge'),
        edgeLabelBackground: colour('--ph-bg'),
        titleColor: colour('--ph-text'),
        actorBkg: colour('--ph-panel'),
        actorBorder: colour('--ph-edge'),
        actorTextColor: colour('--ph-text'),
        actorLineColor: colour('--ph-muted'),
        signalColor: colour('--ph-text'),
        signalTextColor: colour('--ph-text'),
        labelBoxBkgColor: colour('--ph-panel'),
        labelBoxBorderColor: colour('--ph-edge'),
        labelTextColor: colour('--ph-text'),
        loopTextColor: colour('--ph-text'),
        noteBkgColor: colour('--ph-panel'),
        noteBorderColor: colour('--ph-edge'),
        noteTextColor: colour('--ph-text'),
        activationBkgColor: colour('--ph-tint'),
        activationBorderColor: colour('--ph-edge'),
        sequenceNumberColor: colour('--ph-accent-ink')
      }
    });
    blocks.forEach(function (el, i) {
      m.render('ph-diagram-svg-' + i + '-' + Date.now(), safe(sources[i])).then(function (out) {
        if (!el.getAttribute('data-ready')) build(el, i);
        var pic = el.querySelector('.ph-diagram__pic');
        pic.innerHTML = out.svg;
        var svg = pic.querySelector('svg');
        // the picture is one image to a reader: its parts are hidden and the name and summary carry the content
        svg.setAttribute('aria-hidden', 'true');
        svg.removeAttribute('role');
        svg.removeAttribute('aria-roledescription');
        var vb = (svg.getAttribute('viewBox') || '').split(/\s+/);
        var w = parseFloat(vb[2]) || parseFloat(svg.getAttribute('width')) || 800;
        svg.setAttribute('data-natural-width', String(w));
        applySize(el);
        choose(el);
      }).catch(function () { /* the text stays as it is */ });
    });
  }

  var s = document.createElement('script');
  s.src = root + 'vendor/mermaid/mermaid.min.js';
  s.onload = function () {
    draw();
    // the theme switch changes this attribute: draw again in the new colours
    new MutationObserver(draw).observe(document.body, { attributes: true, attributeFilter: ['data-md-color-scheme'] });
  };
  document.head.appendChild(s);
})();
