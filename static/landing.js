(() => {
  'use strict';
  const nav = document.querySelector('.nav');
  const toggle = document.querySelector('.menu-toggle');
  if (nav && toggle) {
    toggle.addEventListener('click', () => {
      const open = nav.classList.toggle('mobile-open');
      toggle.setAttribute('aria-expanded', String(open));
      toggle.textContent = open ? '×' : '☰';
    });
    nav.querySelectorAll('.nav-links a').forEach(link => link.addEventListener('click', () => {
      nav.classList.remove('mobile-open'); toggle.setAttribute('aria-expanded', 'false'); toggle.textContent = '☰';
    }));
  }
  const year = document.getElementById('year');
  if (year) year.textContent = String(new Date().getFullYear());
  const items = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.add('visible'); observer.unobserve(entry.target); }
    }), { threshold: 0.08 });
    items.forEach(item => observer.observe(item));
  } else items.forEach(item => item.classList.add('visible'));
  const video = document.querySelector('.brand-film');
  if (video) {
    // Autoplay is muted, but mobile browsers can still reject it; controls remain available.
    const play = video.play(); if (play && typeof play.catch === 'function') play.catch(() => {});
  }
})();
