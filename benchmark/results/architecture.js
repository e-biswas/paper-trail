const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const sequence = [
  {
    name: "paper",
    selectors: [
      '[data-connection="paper"]',
      '[data-edge-note="paper"]',
      '[data-node="main"]',
      '[data-node="paper"]',
    ],
  },
  {
    name: "audit",
    selectors: [
      '[data-connection="audit"]',
      '[data-edge-note="audit"]',
      '[data-node="main"]',
      '[data-node="audit"]',
    ],
  },
  {
    name: "runner",
    selectors: [
      '[data-connection="runner"]',
      '[data-edge-note="runner"]',
      '[data-node="main"]',
      '[data-node="runner"]',
      '.sandbox-shell',
    ],
  },
  {
    name: "ledger",
    selectors: [
      '[data-connection="ledger"]',
      '[data-edge-note="ledger"]',
      '[data-node="main"]',
      '[data-node="ledger"]',
    ],
  },
  {
    name: "validator",
    selectors: [
      '[data-connection="validator"]',
      '[data-edge-note="validator"]',
      '[data-node="ledger"]',
      '[data-node="validator"]',
    ],
  },
  {
    name: "pr",
    selectors: [
      '[data-connection="pr"]',
      '[data-edge-note="pr"]',
      '[data-node="ledger"]',
      '[data-node="pr"]',
    ],
  },
].map((item) => ({
  ...item,
  elements: item.selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector))),
}));

const uniqueElements = Array.from(new Set(sequence.flatMap((item) => item.elements)));

window.requestAnimationFrame(() => {
  document.body.classList.add("is-ready");
});

function setActive(index) {
  const activeElements = new Set(sequence[index]?.elements || []);
  uniqueElements.forEach((element) => {
    element.classList.toggle("is-active", activeElements.has(element));
  });
}

if (sequence.length) {
  let index = 0;
  setActive(index);

  const cycleIntervalMs = reduceMotion ? 2600 : 1800;
  window.setInterval(() => {
    index = (index + 1) % sequence.length;
    setActive(index);
  }, cycleIntervalMs);
}