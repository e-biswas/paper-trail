const raw = window.BENCHMARK_RAW;
const meta = window.BENCHMARK_META;
const findings = window.BENCHMARK_FINDINGS;

if (!raw || !meta) {
  throw new Error("Missing benchmark payload. data.js must load before app.js.");
}

const slidesRoot = document.getElementById("slides");
const navRoot = document.getElementById("slide-nav");

const verdictTone = {
  confirmed: "teal",
  refuted: "rust",
  unclear: "slate"
};

const derived = buildDerived(raw, meta);

slidesRoot.innerHTML = buildSlides(derived);
const slideElements = Array.from(document.querySelectorAll(".slide"));
let activeSlideIndex = 0;

buildNav();
wireObservers();
wireKeyboardNav();
wireParallax();

function buildDerived(payload, metaInfo) {
  const perGroupEntries = Object.entries(payload.per_group);
  const aggregateEntries = Object.entries(payload.aggregates);

  const quickAggregates = aggregateEntries
    .filter(([label]) => label.endsWith("/check"))
    .map(([label, stats]) => ({
      key: label,
      paper: label.split("/")[0],
      agreement: stats.mean_verdict_agreement,
      lineJaccard: stats.mean_evidence_line_jaccard,
      fileJaccard: stats.mean_evidence_file_jaccard,
      kappa: stats.fleiss_kappa?.kappa ?? null,
      averageCost: stats.mean_cost_usd,
      averageDuration: stats.mean_duration_s,
      questionCount: stats.n_questions
    }));

  const deepAggregates = aggregateEntries
    .filter(([label]) => label.endsWith("/investigate"))
    .map(([label, stats]) => ({
      key: label,
      paper: label.split("/")[0],
      agreement: stats.mean_conclusion_agreement,
      conclusion: (stats.modal_conclusions || [])[0] || "no_actionable_bug",
      validatorPass: stats.mean_validator_pass_fraction,
      averageCost: stats.mean_cost_usd,
      averageDuration: stats.mean_duration_s,
      dossierComplete: stats.dossier_completeness_fraction,
      topHypothesisAgreement: stats.mean_top_hypothesis_agreement
    }));

  const quickRows = perGroupEntries
    .filter(([label]) => label.includes("/check/"))
    .map(([label, stats]) => ({
      key: label,
      paper: label.split("/")[0],
      id: label.split("/").slice(-1)[0],
      label: prettyQuestion(label.split("/").slice(-1)[0]),
      agreement: stats.verdict_agreement,
      lineJaccard: stats.evidence_line_jaccard_pairwise_mean,
      fileJaccard: stats.evidence_file_jaccard_pairwise_mean,
      modalVerdict: stats.modal_verdict,
      confidenceMean: stats.confidence_mean,
      cost: stats.cost_mean_usd,
      duration: stats.duration_mean_s
    }))
    .sort((left, right) => left.key.localeCompare(right.key));

  const scatterPoints = perGroupEntries.map(([label, stats], index) => {
    const isQuick = label.includes("/check/");
    const parts = label.split("/");
    return {
      key: label,
      shortLabel: `${parts[0]} / ${parts[2].replace(/^deep_/, "deep ").replace(/^qc\d+_/, "")}`,
      mode: isQuick ? "check" : "investigate",
      cost: stats.cost_mean_usd,
      duration: stats.duration_mean_s,
      toolCalls: stats.tool_calls_mean,
      delay: index * 55
    };
  });

  const quickMeanCost = average(quickRows.map((row) => row.cost));
  const quickMeanDuration = average(quickRows.map((row) => row.duration));
  const deepMeanCost = average(deepAggregates.map((row) => row.averageCost));
  const deepMeanDuration = average(deepAggregates.map((row) => row.averageDuration));

  return {
    meta: metaInfo,
    overview: {
      totalRuns: metaInfo.totalRuns,
      totalPapers: metaInfo.totalPapers,
      quickAgreementMean: average(quickAggregates.map((row) => row.agreement)),
      deepAgreementMean: average(deepAggregates.map((row) => row.agreement)),
      zeroCrashes: metaInfo.zeroCrashes
    },
    quickAggregates,
    deepAggregates,
    quickRows,
    scatterPoints,
    modeSummary: {
      quick: {
        cost: quickMeanCost,
        duration: quickMeanDuration,
        descriptor: "Fast enough to feel conversational"
      },
      deep: {
        cost: deepMeanCost,
        duration: deepMeanDuration,
        descriptor: "Heavy enough to be careful, still bounded"
      }
    },
    findings
  };
}

function buildSlides(data) {
  return [
    buildHeroSlide(data),
    buildQuickSlide(data),
    buildDeepSlide(data),
    buildEvidenceSlide(data),
    buildCostSlide(data),
    buildClosingSlide(data)
  ].join("");
}

function buildHeroSlide(data) {
  return `
    <section class="slide" id="overview" data-title="Overview" data-step="Slide 00">
      <div class="slide__inner">
        <div class="hero-shell panel reveal">
          <div class="hero-grid">
            <div class="hero-copy reveal" style="--delay: 0ms;">
              <div>
                <div class="eyebrow">Paper Trail benchmark story</div>
                <h1 class="hero-copy__title">Same answer. Honest limits. Predictable cost.</h1>
                <p class="hero-copy__lede">
                  This page turns the consistency benchmark into a scroll-led story instead of a markdown table.
                  Thirty repeated runs across two unseen papers show the core behavior judges care about: does the
                  agent land in the same decision, and does it stay honest when there is no actionable bug to claim?
                </p>
                <div class="hero-callout">
                  <strong>Headline</strong>
                  Quick Check reaches the same verdict label about four times out of five. Deep Investigation lands on the same conclusion bucket every time in this benchmark.
                </div>
              </div>
            </div>

            <div class="hero-stats reveal" style="--delay: 120ms;">
              <article class="stat-card">
                <div class="stat-card__kicker">Repeated runs</div>
                <div class="stat-card__value"><span data-count-to="${data.meta.totalRuns}">0</span></div>
                <p>${data.meta.totalPapers} papers, Quick Check and Deep Investigation, 3 repeats each.</p>
              </article>

              <article class="stat-card">
                <div class="stat-card__kicker">Total benchmark cost</div>
                <div class="stat-card__value"><span data-count-to="${data.meta.totalCostUsd}" data-prefix="$" data-decimals="2">$0.00</span></div>
                <p>Includes the independent validator pass. Built to be reproducible without runaway spend.</p>
              </article>

              <article class="stat-card">
                <div class="stat-card__kicker">Deep conclusion agreement</div>
                <div class="stat-card__value"><span data-count-to="${roundPercent(data.overview.deepAgreementMean)}" data-suffix="%">0%</span></div>
                <p>${data.meta.zeroCrashes ? "Zero crashes across all 30 runs." : "Crashes present in the benchmark."}</p>
              </article>
            </div>
          </div>
        </div>
      </div>
    </section>
  `;
}

function buildQuickSlide(data) {
  return `
    <section class="slide" id="quick-check" data-title="Quick Check" data-step="Slide 01">
      <div class="slide__inner">
        <div class="panel reveal" style="padding: 1.5rem; --delay: 0ms;">
          <div class="eyebrow">Quick Check</div>
          <h2 class="section-heading">The verdict holds steadier than the wording.</h2>
          <p class="section-copy">
            The important bit is not whether the agent writes the exact same sentence. It is whether the verdict label lands in the same place.
            These rings show agreement on the label, with kappa underneath to separate real stability from chance agreement.
          </p>
        </div>

        <div class="story-grid">
          ${data.quickAggregates
            .map((card, index) => renderQuickCard(card, index))
            .join("")}
        </div>
      </div>
    </section>
  `;
}

function buildDeepSlide(data) {
  return `
    <section class="slide" id="deep" data-title="Deep" data-step="Slide 02">
      <div class="slide__inner">
        <div class="deep-intro panel reveal" style="--delay: 0ms;">
          <div>
            <div class="eyebrow">Deep Investigation</div>
            <strong>The clean paper stayed clean. The hard paper stayed humble.</strong>
            <div class="section-copy">Both Deep prompts converged to the same conclusion bucket across all repeats: no actionable bug. That matters because over-eager agents usually fail by inventing one.</div>
          </div>
          <div class="pill pill--amber">All Deep runs produced complete dossiers</div>
        </div>

        <div class="deep-grid">
          ${data.deepAggregates
            .map((card, index) => renderDeepCard(card, index))
            .join("")}
        </div>
      </div>
    </section>
  `;
}

function buildEvidenceSlide(data) {
  const paperComparisons = data.quickAggregates.map((card, index) => {
    return `
      <article class="compare-block reveal" style="--delay: ${index * 110 + 100}ms;">
        <div class="meter-card__header">
          <h3>${escapeHtml(card.paper)} Quick Check</h3>
          <span class="pill pill--slate">${card.questionCount} questions</span>
        </div>
        <p>The answer is more stable than the exact citation line. That is the signature of a system that keeps returning to the right files.</p>
        <div class="compare-bars">
          ${renderBarRow("Verdict agreement", card.agreement, "teal")}
          ${renderBarRow("Line-level evidence", card.lineJaccard, "slate")}
          ${renderBarRow("File-level evidence", card.fileJaccard, "amber")}
        </div>
      </article>
    `;
  });

  return `
    <section class="slide" id="evidence" data-title="Evidence" data-step="Slide 03">
      <div class="slide__inner">
        <div class="compare-grid">
          <div class="compare-list panel reveal" style="padding: 1.35rem; --delay: 0ms;">
            <div>
              <div class="eyebrow">Evidence stability</div>
              <h2 class="section-heading">Same files. Slightly different lines.</h2>
              <p class="section-copy">
                This is the benchmark's most human-looking pattern. The agent usually lands in the same file and the same answer, but the exact cited line drifts more than expected.
              </p>
            </div>
            ${paperComparisons.join("")}
          </div>

          <div class="question-table panel reveal" style="--delay: 120ms;">
            <h3>Question by question</h3>
            <p>The rough edges are concentrated in genuinely ambiguous prompts, not in catastrophic disagreements.</p>
            <div class="question-table__list">
              ${data.quickRows.map((row, index) => renderQuestionRow(row, index)).join("")}
            </div>
          </div>
        </div>
      </div>
    </section>
  `;
}

function buildCostSlide(data) {
  return `
    <section class="slide slide--cost" id="cost" data-title="Cost" data-step="Slide 04">
      <div class="slide__inner">
        <div class="plot-card plot-card--compact panel reveal" style="--delay: 0ms;">
          <div>
            <div class="eyebrow">Predictability</div>
            <h2 class="section-heading">The cost curve separates into two clean clusters.</h2>
            <p class="section-copy">
              Quick Check stays in the cheap-and-fast corner. Deep Investigation is slower and more expensive, but still bounded enough to plan around. Tool-call volume scales with that split rather than exploding unpredictably.
            </p>
          </div>
          <div class="plot-shell plot-shell--compact">
            ${renderScatter(data.scatterPoints)}
            <div class="plot-meta">
              <div class="plot-meta__item"><span class="plot-meta__dot" style="background: var(--teal);"></span> Quick Check</div>
              <div class="plot-meta__item"><span class="plot-meta__dot" style="background: var(--amber);"></span> Deep Investigation</div>
              <div class="plot-meta__item">Point size tracks mean tool calls</div>
            </div>
          </div>
        </div>

        <div class="mode-summary mode-summary--compact">
          <article class="summary-card panel reveal" style="--delay: 110ms;">
            <div class="eyebrow">Mode profile</div>
            <h3>Quick Check</h3>
            <p>${data.modeSummary.quick.descriptor} and cheap enough for repeated use during code review.</p>
            <div class="mode-summary__value">
              <div class="mode-summary__big"><span data-count-to="${data.modeSummary.quick.cost}" data-prefix="$" data-decimals="2">$0.00</span></div>
              <div class="section-copy">mean cost</div>
            </div>
            <div class="mode-summary__stats">
              <div class="mini-stat">
                <span class="mini-stat__label">Mean duration</span>
                <span class="mini-stat__value"><span data-count-to="${data.modeSummary.quick.duration}" data-suffix="s" data-decimals="1">0.0s</span></span>
              </div>
            </div>
          </article>

          <article class="summary-card panel reveal" style="--delay: 210ms;">
            <div class="eyebrow">Mode profile</div>
            <h3>Deep Investigation</h3>
            <p>${data.modeSummary.deep.descriptor}, which is exactly what you want from the PR-producing path.</p>
            <div class="mode-summary__value">
              <div class="mode-summary__big"><span data-count-to="${data.modeSummary.deep.cost}" data-prefix="$" data-decimals="2">$0.00</span></div>
              <div class="section-copy">mean cost</div>
            </div>
            <div class="mode-summary__stats">
              <div class="mini-stat">
                <span class="mini-stat__label">Mean duration</span>
                <span class="mini-stat__value"><span data-count-to="${data.modeSummary.deep.duration}" data-suffix="s" data-decimals="1">0.0s</span></span>
              </div>
            </div>
          </article>
        </div>
      </div>
    </section>
  `;
}

function buildClosingSlide(data) {
  return `
    <section class="slide" id="takeaways" data-title="Takeaways" data-step="Slide 05">
      <div class="slide__inner">
        <div class="takeaway-grid">
          ${data.findings.map((item, index) => renderFindingCard(item, index)).join("")}
        </div>

        <div class="summary-grid">
          <article class="closing-card panel reveal" style="--delay: 140ms;">
            <div class="eyebrow">What to say out loud</div>
            <h3>One clean sentence for judges</h3>
            <p>
              The agent reaches the same Quick Check verdict about four times out of five, and on Deep Investigation it unanimously avoided hallucinating a bug on both a clean paper and a hard paper where no actionable bug could be proven.
            </p>
            <p class="footnote">
              Model: ${escapeHtml(data.meta.model)}. Run date: ${escapeHtml(data.meta.runDate)}. Validator spend: ${formatMoney(data.meta.validatorCostUsd)}.
            </p>
          </article>

          <article class="closing-card panel reveal" style="--delay: 220ms;">
            <div class="eyebrow">Raw files</div>
            <h3>Open the source artifacts</h3>
            <div class="resource-list">
              <a class="resource-link" href="SUMMARY.md">
                <div>
                  <strong>Summary tables</strong>
                  <span>benchmark/results/SUMMARY.md</span>
                </div>
                <span>open</span>
              </a>
              <a class="resource-link" href="FINDINGS.md">
                <div>
                  <strong>Interpretation notes</strong>
                  <span>benchmark/results/FINDINGS.md</span>
                </div>
                <span>open</span>
              </a>
              <a class="resource-link" href="consistency.json">
                <div>
                  <strong>Machine-readable metrics</strong>
                  <span>benchmark/results/consistency.json</span>
                </div>
                <span>open</span>
              </a>
            </div>
          </article>
        </div>
      </div>
    </section>
  `;
}

function renderQuickCard(card, index) {
  const tone = index % 2 === 0 ? "var(--teal)" : "var(--amber)";
  return `
    <article class="meter-card panel reveal" style="--delay: ${index * 120 + 120}ms;">
      <div class="meter-card__header">
        <h3>${escapeHtml(card.paper)} consistency</h3>
        <span class="pill ${index % 2 === 0 ? "pill--teal" : "pill--amber"}">${card.questionCount} prompts</span>
      </div>
      <div class="meter-card__layout">
        <div class="meter-ring" data-progress="${card.agreement}" style="--tone: ${tone};">
          <div class="meter-ring__value">
            <strong><span data-count-to="${roundPercent(card.agreement)}" data-suffix="%">0%</span></strong>
            <small>verdict agreement</small>
          </div>
        </div>

        <div class="meter-metrics">
          <div class="mini-stat">
            <span class="mini-stat__label">Fleiss kappa</span>
            <span class="mini-stat__value">${card.kappa != null ? card.kappa.toFixed(3) : "-"}</span>
            <span class="mini-stat__caption">Chance-corrected stability on the verdict label.</span>
          </div>
          <div class="mini-stat">
            <span class="mini-stat__label">Line evidence Jaccard</span>
            <span class="mini-stat__value">${roundPercent(card.lineJaccard)}%</span>
            <span class="mini-stat__caption">Same answer, but not always the same representative line.</span>
          </div>
          <div class="mini-stat">
            <span class="mini-stat__label">Mean cost / duration</span>
            <span class="mini-stat__value">${formatMoney(card.averageCost)} / ${formatCompactDuration(card.averageDuration)}</span>
          </div>
        </div>
      </div>
    </article>
  `;
}

function renderDeepCard(card, index) {
  return `
    <article class="deep-card panel reveal" style="--delay: ${index * 120 + 120}ms;">
      <div class="deep-card__header">
        <h3>${escapeHtml(card.paper)} Deep run</h3>
        <span class="pill ${card.validatorPass >= 0.8 ? "pill--teal" : "pill--amber"}">${card.validatorPass >= 0.8 ? "strong validator" : "acceptable validator"}</span>
      </div>

      <div class="deep-card__value">
        <div class="deep-card__big"><span data-count-to="${roundPercent(card.agreement)}" data-suffix="%">0%</span></div>
        <p>agreement on the conclusion bucket across three independent Deep reruns</p>
      </div>

      <div class="progress-stack">
        <div class="progress-row">
          <div class="progress-row__labels">
            <span>Validator pass fraction</span>
            <span>${roundPercent(card.validatorPass)}%</span>
          </div>
          <div class="progress-row__track">
            <div class="progress-row__fill progress-row__fill--teal" style="--scale: ${card.validatorPass}; --delay: ${index * 80 + 260}ms;"></div>
          </div>
        </div>

        <div class="progress-row">
          <div class="progress-row__labels">
            <span>Dossier completeness</span>
            <span>${roundPercent(card.dossierComplete)}%</span>
          </div>
          <div class="progress-row__track">
            <div class="progress-row__fill progress-row__fill--amber" style="--scale: ${card.dossierComplete}; --delay: ${index * 80 + 340}ms;"></div>
          </div>
        </div>
      </div>

      <div class="deep-metrics" style="margin-top: 1rem;">
        <div class="mini-stat">
          <span class="mini-stat__label">Modal conclusion</span>
          <span class="mini-stat__value">${escapeHtml(card.conclusion.replace(/_/g, " "))}</span>
        </div>
        <div class="mini-stat">
          <span class="mini-stat__label">Mean cost / duration</span>
          <span class="mini-stat__value">${formatMoney(card.averageCost)} / ${formatCompactDuration(card.averageDuration)}</span>
        </div>
      </div>
    </article>
  `;
}

function renderQuestionRow(row, index) {
  const tone = verdictTone[row.modalVerdict] || "slate";
  return `
    <article class="question-row reveal" style="--delay: ${index * 45 + 140}ms;">
      <div class="question-row__top">
        <div class="question-row__title">
          <span class="question-id">${escapeHtml(row.paper)} / ${escapeHtml(row.id)}</span>
          <strong>${escapeHtml(row.label)}</strong>
        </div>
        <span class="pill pill--${tone}">${escapeHtml(row.modalVerdict)}</span>
      </div>

      <div class="question-row__metrics">
        <div class="mini-bar-wrap">
          <span>Verdict agreement - ${roundPercent(row.agreement)}%</span>
          <div class="mini-bar"><div class="mini-bar__fill mini-bar__fill--teal" style="--scale: ${row.agreement}; --delay: ${index * 45 + 220}ms;"></div></div>
        </div>
        <div class="mini-bar-wrap">
          <span>Line evidence - ${roundPercent(row.lineJaccard)}%</span>
          <div class="mini-bar"><div class="mini-bar__fill mini-bar__fill--slate" style="--scale: ${row.lineJaccard}; --delay: ${index * 45 + 260}ms;"></div></div>
        </div>
      </div>
    </article>
  `;
}

function renderFindingCard(item, index) {
  return `
    <article class="takeaway-card panel reveal" style="--delay: ${index * 85 + 80}ms;">
      <div class="takeaway-card__header">
        <div class="takeaway-card__number">Finding ${escapeHtml(item.number)}</div>
      </div>
      <h3>${escapeHtml(item.title)}</h3>
      <p>${escapeHtml(item.body)}</p>
    </article>
  `;
}

function renderBarRow(label, value, tone) {
  return `
    <div class="bar-row">
      <div class="bar-row__header">
        <span class="bar-row__label">${escapeHtml(label)}</span>
        <span class="bar-row__value">${roundPercent(value)}%</span>
      </div>
      <div class="bar-track">
        <div class="bar-fill bar-fill--${tone}" style="--scale: ${value};"></div>
      </div>
    </div>
  `;
}

function renderScatter(points) {
  const width = 700;
  const height = 250;
  const padding = { top: 16, right: 24, bottom: 48, left: 48 };
  const maxCost = Math.max(...points.map((point) => point.cost)) * 1.15;
  const maxDuration = Math.max(...points.map((point) => point.duration)) * 1.1;

  const scaleX = (value) =>
    padding.left + (value / maxCost) * (width - padding.left - padding.right);
  const scaleY = (value) =>
    height - padding.bottom - (value / maxDuration) * (height - padding.top - padding.bottom);

  const xTicks = [0, 0.5, 1, 1.5, 2].filter((tick) => tick <= maxCost + 0.05);
  const yTicks = [0, 60, 120, 180, 240, 300].filter((tick) => tick <= maxDuration + 10);

  const gridLines = [
    ...xTicks.map(
      (tick) => `
        <line class="plot-grid" x1="${scaleX(tick)}" y1="${padding.top}" x2="${scaleX(tick)}" y2="${height - padding.bottom}"></line>
        <text class="plot-label" x="${scaleX(tick)}" y="${height - padding.bottom + 22}" text-anchor="middle">$${tick.toFixed(1)}</text>
      `
    ),
    ...yTicks.map(
      (tick) => `
        <line class="plot-grid" x1="${padding.left}" y1="${scaleY(tick)}" x2="${width - padding.right}" y2="${scaleY(tick)}"></line>
        <text class="plot-label" x="${padding.left - 12}" y="${scaleY(tick) + 4}" text-anchor="end">${tick}s</text>
      `
    )
  ].join("");

  const pointMarkup = points
    .map((point, index) => {
      const x = scaleX(point.cost);
      const y = scaleY(point.duration);
      const radius = 7 + point.toolCalls * 0.18;
      return `
        <g class="plot-point plot-point--${point.mode}" style="--delay: ${point.delay}ms;" transform="translate(${x} ${y})">
          <title>${escapeHtml(point.shortLabel)}</title>
          <circle r="${radius}"></circle>
        </g>
      `;
    })
    .join("");

  return `
    <svg class="plot" viewBox="0 0 ${width} ${height}" role="img" aria-label="Cost versus duration across benchmark groups">
      ${gridLines}
      <line class="plot-axis" x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}"></line>
      <line class="plot-axis" x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${height - padding.bottom}"></line>
      <text class="plot-label" x="${width / 2}" y="${height - 12}" text-anchor="middle">Mean cost per group</text>
      <text class="plot-label" x="18" y="${height / 2}" text-anchor="middle" transform="rotate(-90 18 ${height / 2})">Mean duration</text>
      ${pointMarkup}
    </svg>
  `;
}

function buildNav() {
  navRoot.innerHTML = slideElements
    .map(
      (slide) => `
        <button class="slide-nav__button" type="button" data-target="${slide.id}">
          <span class="slide-nav__dot"></span>
          <span class="slide-nav__title">${escapeHtml(slide.dataset.title || slide.id)}</span>
        </button>
      `
    )
    .join("");

  navRoot.querySelectorAll(".slide-nav__button").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById(button.dataset.target)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

function wireObservers() {
  const navButtons = Array.from(navRoot.querySelectorAll(".slide-nav__button"));
  const seen = new WeakSet();

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.intersectionRatio >= 0.48) {
          entry.target.classList.add("is-visible");
          const targetId = entry.target.id;
          activeSlideIndex = slideElements.findIndex((slide) => slide.id === targetId);
          navButtons.forEach((button) => {
            button.classList.toggle("is-active", button.dataset.target === targetId);
          });

          if (!seen.has(entry.target)) {
            animateNumbers(entry.target);
            animateRings(entry.target);
            seen.add(entry.target);
          }
        }
      });
    },
    {
      threshold: [0.2, 0.48, 0.72]
    }
  );

  slideElements.forEach((slide) => observer.observe(slide));
}

function wireKeyboardNav() {
  window.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) {
      return;
    }

    const target = event.target;
    if (
      target instanceof HTMLElement &&
      (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
    ) {
      return;
    }

    if (event.key === "ArrowRight") {
      event.preventDefault();
      scrollToSlide(activeSlideIndex + 1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      scrollToSlide(activeSlideIndex - 1);
    }
  });
}

function scrollToSlide(index) {
  const clamped = Math.max(0, Math.min(index, slideElements.length - 1));
  activeSlideIndex = clamped;
  slideElements[clamped]?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function animateNumbers(scope) {
  scope.querySelectorAll("[data-count-to]").forEach((element) => {
    if (element.dataset.animated === "true") {
      return;
    }

    element.dataset.animated = "true";
    const target = Number(element.dataset.countTo);
    const decimals = Number(element.dataset.decimals || 0);
    const prefix = element.dataset.prefix || "";
    const suffix = element.dataset.suffix || "";
    const duration = Number(element.dataset.duration || 1400);
    const start = performance.now();

    const tick = (now) => {
      const rawProgress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - rawProgress, 3);
      const current = target * eased;
      element.textContent = `${prefix}${formatAnimatedNumber(current, decimals)}${suffix}`;
      if (rawProgress < 1) {
        requestAnimationFrame(tick);
      }
    };

    requestAnimationFrame(tick);
  });
}

function animateRings(scope) {
  scope.querySelectorAll(".meter-ring").forEach((ring) => {
    ring.style.setProperty("--progress", ring.dataset.progress || "0");
  });
}

function wireParallax() {
  const sync = () => {
    const scrollTop = window.scrollY || document.documentElement.scrollTop;
    const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
    const ratio = maxScroll > 0 ? scrollTop / maxScroll : 0;
    document.documentElement.style.setProperty("--scroll-ratio", ratio.toFixed(4));
  };

  sync();
  window.addEventListener("scroll", sync, { passive: true });
  window.addEventListener("resize", sync);
}

function prettyQuestion(input) {
  return input
    .replace(/^qc\d+_/, "")
    .replace(/^deep_/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function average(values) {
  if (!values.length) {
    return 0;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function roundPercent(value) {
  return Math.round(value * 100);
}

function formatMoney(value) {
  return `$${value.toFixed(value < 1 ? 3 : 2)}`;
}

function formatCompactDuration(value) {
  if (value >= 60) {
    const minutes = Math.floor(value / 60);
    const seconds = Math.round(value % 60);
    return `${minutes}m ${seconds}s`;
  }
  return `${Math.round(value)}s`;
}

function formatAnimatedNumber(value, decimals) {
  if (decimals === 0) {
    return String(Math.round(value));
  }
  return value.toFixed(decimals);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}