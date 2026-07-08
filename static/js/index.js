// Spec Kit Agents — main JS
// Handles: smooth scroll, active-section highlighting, image modal

document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  const sections = document.querySelectorAll('section[id]');
  const navLinks = document.querySelectorAll('.top-nav a[href^="#"]');

  function onScroll() {
    let current = '';
    sections.forEach(function (s) {
      const rect = s.getBoundingClientRect();
      if (rect.top <= 80 && rect.bottom > 80) current = '#' + s.id;
    });
    navLinks.forEach(function (a) {
      a.classList.remove('active');
      if (a.getAttribute('href') === current) a.classList.add('active');
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
});
