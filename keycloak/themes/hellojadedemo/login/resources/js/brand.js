(function () {
  function getResourceBase() {
    var links = document.querySelectorAll('link[rel="stylesheet"]');
    for (var i = 0; i < links.length; i++) {
      var m = links[i].href.match(/(.*resources\/[^/]+\/login\/hellojadedemo\/)/);
      if (m) return m[1];
    }
    return '';
  }

  function injectSidebar(base) {
    var logoSrc = base ? base + 'img/hellojade_logo.png' : '';

    var sidebar = document.createElement('div');
    sidebar.id = 'hj-sidebar';
    sidebar.innerHTML =
      (logoSrc
        ? '<img class="hj-sidebar-logo" src="' + logoSrc + '" alt="HelloJADE" onerror="this.style.display=\'none\'" />'
        : '') +
      '<p class="hj-sidebar-tag">HelloJADE by Maolys</p>' +
      '<h2 class="hj-sidebar-headline">La plateforme de<br>suivi patient<br>automatisé.</h2>' +
      '<p class="hj-sidebar-sub">Appels IA, analyse des réponses et alertes cliniques pour vos équipes soignantes.</p>';

    var page = document.querySelector('.login-pf-page');
    if (page) page.insertBefore(sidebar, page.firstChild);
  }

  function injectBrand(base) {
    var logoSrc = base ? base + 'img/hellojade_logo.png' : '';

    var brand = document.createElement('div');
    brand.id = 'hj-brand';
    brand.innerHTML =
      (logoSrc
        ? '<img class="hj-logo-img" src="' + logoSrc + '" alt="HelloJADE" onerror="this.style.display=\'none\'" />'
        : '') +
      '<h1 class="hj-form-title">Connexion</h1>' +
      '<p class="hj-form-subtitle">Connectez-vous pour accéder à la plateforme.</p>';

    var target =
      document.getElementById('kc-content-wrapper') ||
      document.getElementById('kc-content') ||
      document.querySelector('.card-pf');

    if (target) target.insertBefore(brand, target.firstChild);
  }

  function injectFooter() {
    var footer = document.createElement('p');
    footer.id = 'hj-footer';
    footer.textContent =
      'HelloJADE by Maolys · Environnement de démonstration. ' +
      'Sessions sécurisées — données non réelles.';

    var wrapper =
      document.getElementById('kc-content-wrapper') ||
      document.getElementById('kc-content');
    if (wrapper) wrapper.appendChild(footer);
  }

  function init() {
    var base = getResourceBase();
    injectSidebar(base);
    injectBrand(base);
    injectFooter();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
