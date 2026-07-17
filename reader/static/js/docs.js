(() => {
  const links = [...document.querySelectorAll('.docs-toc a')];
  const sections = links.map(link => document.querySelector(link.getAttribute('href'))).filter(Boolean);

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      links.forEach(link => link.classList.toggle(
        'active', link.getAttribute('href') === `#${visible.target.id}`
      ));
    }, { rootMargin: '-18% 0px -68% 0px', threshold: [0, 0.1, 0.5] });
    sections.forEach(section => observer.observe(section));
  }

  document.querySelectorAll('.copy-code').forEach(button => {
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copy || '');
        const original = button.textContent;
        button.textContent = 'Másolva';
        button.classList.add('copied');
        window.setTimeout(() => {
          button.textContent = original;
          button.classList.remove('copied');
        }, 1600);
      } catch (_) {
        button.textContent = 'Ctrl+C';
      }
    });
  });
})();
