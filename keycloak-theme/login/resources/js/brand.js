
(function() {
  function injectBrand() {
    var headerWrapper = document.getElementById('kc-header-wrapper');
    if (headerWrapper) headerWrapper.style.display = 'none';
    var pageTitle = document.getElementById('kc-page-title');
    if (pageTitle) pageTitle.style.display = 'none';

    var imgSrc = '';
    var links = document.querySelectorAll('link[rel="stylesheet"]');
    for (var i = 0; i < links.length; i++) {
      var m = links[i].href.match(/(.*resources\/[^/]+\/login\/hellojadedemo\/)/);
      if (m) { imgSrc = m[1] + 'img/hellojade_logo.png'; break; }
    }

    var brand = document.createElement('div');
    brand.id = 'hj-brand';
    brand.innerHTML =
      '<div class="hj-logo-wrap">' +
        (imgSrc
          ? '<img class="hj-logo-img" src="' + imgSrc + '" alt="HelloJADE" onerror="this.style.display=\'none\'" />'
          : '<div class="hj-logo-mark">HJ</div>') +
      '</div>' +
      '<div class="hj-tagline">Demo · Suivi post-hospitalisation</div>' +
      '<div class="hj-demo-badge">Environnement de demonstration - donnees non reelles</div>';

    var target = document.getElementById('kc-form-wrapper') ||
                 document.getElementById('kc-content-wrapper') ||
                 document.getElementById('kc-content') ||
                 document.querySelector('.login-pf-body') ||
                 document.body;
    target.insertBefore(brand, target.firstChild);
  }

  function fixPasswordField() {
    // Get username input as reference
    var usernameInput = document.getElementById('username');
    if (!usernameInput) return;

    var refHeight = usernameInput.getBoundingClientRect().height;
    if (!refHeight) return;

    // Find the password input group wrapper
    var pwdInput = document.getElementById('password');
    if (!pwdInput) return;

    var group = pwdInput.closest('.pf-v5-c-input-group') || pwdInput.parentElement;
    if (!group) return;

    // Force same height on the group
    group.style.cssText += [
      'height:' + refHeight + 'px',
      'min-height:0',
      'max-height:' + refHeight + 'px',
      'overflow:hidden',
      'box-sizing:border-box',
      'padding:0',
      'margin:0'
    ].join('!important;') + '!important';

    // Make the inner input fill height
    pwdInput.style.cssText += 'height:100%!important;padding:0 14px!important;box-sizing:border-box!important;';

    // Make the eye button fill height, no border anywhere
    var btn = group.querySelector('button');
    if (btn) {
      btn.style.cssText += 'height:100%!important;padding:0 12px!important;box-sizing:border-box!important;margin:0!important;border:none!important;border-left:none!important;border-right:none!important;border-top:none!important;border-bottom:none!important;outline:none!important;box-shadow:none!important;background:transparent!important;';
    }
  }

  function init() {
    injectBrand();
    // Run fixPasswordField after a tick so layout is computed
    setTimeout(fixPasswordField, 0);
    setTimeout(fixPasswordField, 100);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
