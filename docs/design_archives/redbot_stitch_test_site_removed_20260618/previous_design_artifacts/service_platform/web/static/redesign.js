(function () {
  const STORAGE_KEY = "redbot-ui-theme";
  const body = document.body;
  if (!body || body.dataset.uiRedesign !== "1") {
    return;
  }

  const toggle = document.querySelector("[data-theme-toggle]");
  const cycle = ["light", "dark", "system"];
  const labelByTheme = {
    light: "테마: 라이트",
    dark: "테마: 다크",
    system: "테마: 시스템",
  };

  const readStoredTheme = () => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored && cycle.includes(stored)) {
        return stored;
      }
    } catch (_error) {
      return null;
    }
    return null;
  };

  const resolveSystemTheme = () => {
    const media = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)");
    return media && media.matches ? "dark" : "light";
  };

  const applyTheme = (theme) => {
    const effectiveTheme = theme === "system" ? resolveSystemTheme() : theme;
    body.dataset.theme = effectiveTheme;
    body.dataset.themePreference = theme;
    if (toggle) {
      toggle.textContent = labelByTheme[theme] || labelByTheme.light;
      toggle.setAttribute("aria-label", `${labelByTheme[theme] || labelByTheme.light} 선택됨`);
    }
  };

  const persistTheme = (theme) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch (_error) {
      // ignore storage failures
    }
  };

  const initialTheme = readStoredTheme() || body.dataset.theme || "light";
  applyTheme(cycle.includes(initialTheme) ? initialTheme : "light");

  if (toggle) {
    toggle.addEventListener("click", () => {
      const current = body.dataset.themePreference || "light";
      const idx = cycle.indexOf(current);
      const next = cycle[(idx + 1) % cycle.length];
      applyTheme(next);
      persistTheme(next);
    });
  }

  const media = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)");
  if (media && media.addEventListener) {
    media.addEventListener("change", () => {
      if ((body.dataset.themePreference || "") === "system") {
        applyTheme("system");
      }
    });
  }

  const NUMERIC_HEADER_PATTERNS = [
    /순위/,
    /비중/,
    /수량/,
    /단가/,
    /수수료/,
    /현재가/,
    /투자금액/,
    /평가금액/,
    /평가이익/,
    /이익률/,
    /수익률/,
    /수익/,
    /등락/,
    /변화율/,
    /금액/,
    /가격/,
    /점수/,
    /적합도/,
    /확률/,
    /건수/,
    /CAGR/i,
    /MDD/i,
    /SHARPE/i,
    /RETURN/i,
    /RATE/i,
    /RATIO/i,
    /SCORE/i,
    /WEIGHT/i,
    /RANK/i,
    /PROB/i,
    /OBS/i,
    /\b1W\b/i,
    /\b2W\b/i,
    /\b1M\b/i,
    /\b3M\b/i,
    /\b6M\b/i,
    /\b1Y\b/i,
    /\b2Y\b/i,
    /\b3Y\b/i,
    /\b5Y\b/i,
    /\bFULL\b/i,
    /\bITD\b/i,
  ];

  const NON_NUMERIC_HEADER_PATTERNS = [
    /종목코드/,
    /종목명/,
    /^종목$/,
    /^코드$/,
    /티커/,
    /모델/,
    /이벤트/,
    /상태/,
    /날짜/,
    /일자/,
    /기준/,
    /주차/,
    /스냅샷/,
    /근거/,
    /버킷/,
    /시장/,
    /구분/,
    /이유/,
    /제목/,
    /TICKER/i,
    /CODE/i,
    /NAME/i,
    /MODEL/i,
    /DATE/i,
    /BASIS/i,
    /BUCKET/i,
  ];

  const normalizeHeaderText = (node) =>
    (node?.textContent || "").replace(/\s+/g, " ").trim();

  const shouldAlignNumericColumn = (headerText) => {
    if (!headerText) {
      return false;
    }
    if (NON_NUMERIC_HEADER_PATTERNS.some((pattern) => pattern.test(headerText))) {
      return false;
    }
    return NUMERIC_HEADER_PATTERNS.some((pattern) => pattern.test(headerText));
  };

  const applyNumericTableAlignment = () => {
    document.querySelectorAll("table").forEach((table) => {
      const headers = Array.from(table.querySelectorAll("thead th"));
      if (!headers.length) {
        return;
      }
      headers.forEach((header, idx) => {
        if (!shouldAlignNumericColumn(normalizeHeaderText(header))) {
          return;
        }
        header.classList.add("is-numeric-cell");
        table.querySelectorAll("tbody tr").forEach((row) => {
          const cell = row.children[idx];
          if (cell) {
            cell.classList.add("is-numeric-cell");
          }
        });
      });
    });
  };

  applyNumericTableAlignment();

  const createSvg = (width, height) => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.classList.add("rb-chart-svg");
    return svg;
  };

  const renderLineChart = (node, series) => {
    const clean = (series || []).filter((row) => row && typeof row.score === "number");
    if (!clean.length) {
      node.textContent = "차트 데이터 준비 중";
      return;
    }
    const width = 560;
    const height = 200;
    const pad = { left: 18, right: 12, top: 16, bottom: 22 };
    const xSpan = Math.max(clean.length - 1, 1);
    const values = clean.map((row) => row.score);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = Math.max(max - min, 0.01);

    const xAt = (idx) =>
      pad.left + ((width - pad.left - pad.right) * idx) / xSpan;
    const yAt = (value) =>
      height - pad.bottom - ((height - pad.top - pad.bottom) * (value - min)) / range;

    const svg = createSvg(width, height);
    const last = clean[clean.length - 1];

    if (clean.length === 1) {
      const only = clean[0];
      const x = width / 2;
      const y = height / 2;
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      marker.setAttribute("cx", x.toFixed(2));
      marker.setAttribute("cy", y.toFixed(2));
      marker.setAttribute("r", "5");
      marker.classList.add("rb-chart-marker");
      svg.appendChild(marker);

      const valueLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
      valueLabel.setAttribute("x", x.toFixed(2));
      valueLabel.setAttribute("y", (y - 14).toFixed(2));
      valueLabel.setAttribute("text-anchor", "middle");
      valueLabel.classList.add("rb-chart-latest-label");
      valueLabel.textContent = only.value_label || only.score.toFixed(2);
      svg.appendChild(valueLabel);

      const dateLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
      dateLabel.setAttribute("x", x.toFixed(2));
      dateLabel.setAttribute("y", (height - 10).toFixed(2));
      dateLabel.setAttribute("text-anchor", "middle");
      dateLabel.classList.add("rb-chart-axis-label");
      dateLabel.textContent = String(only.label || "");
      svg.appendChild(dateLabel);

      node.innerHTML = "";
      node.appendChild(svg);
      return;
    }

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    let d = "";
    clean.forEach((row, idx) => {
      const x = xAt(idx);
      const y = yAt(row.score);
      d += `${idx === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)} `;
    });
    path.setAttribute("d", d.trim());
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "2.5");
    path.classList.add("rb-chart-line");
    svg.appendChild(path);

    const yMinLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    yMinLabel.setAttribute("x", "4");
    yMinLabel.setAttribute("y", (height - pad.bottom).toFixed(2));
    yMinLabel.classList.add("rb-chart-axis-label");
    yMinLabel.textContent = (clean.find((row) => row.score === min)?.value_label || min.toFixed(2));
    svg.appendChild(yMinLabel);

    const yMaxLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    yMaxLabel.setAttribute("x", "4");
    yMaxLabel.setAttribute("y", "12");
    yMaxLabel.classList.add("rb-chart-axis-label");
    yMaxLabel.textContent = (clean.find((row) => row.score === max)?.value_label || max.toFixed(2));
    svg.appendChild(yMaxLabel);

    const firstLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    firstLabel.setAttribute("x", xAt(0).toFixed(2));
    firstLabel.setAttribute("y", (height - 6).toFixed(2));
    firstLabel.setAttribute("text-anchor", "start");
    firstLabel.classList.add("rb-chart-axis-label");
    firstLabel.textContent = String(clean[0].label || "");
    svg.appendChild(firstLabel);

    const lastXLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    lastXLabel.setAttribute("x", xAt(clean.length - 1).toFixed(2));
    lastXLabel.setAttribute("y", (height - 6).toFixed(2));
    lastXLabel.setAttribute("text-anchor", "end");
    lastXLabel.classList.add("rb-chart-axis-label");
    lastXLabel.textContent = String(last.label || "");
    svg.appendChild(lastXLabel);

    const marker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    marker.setAttribute("cx", xAt(clean.length - 1).toFixed(2));
    marker.setAttribute("cy", yAt(last.score).toFixed(2));
    marker.setAttribute("r", "3.5");
    marker.classList.add("rb-chart-marker");
    svg.appendChild(marker);

    const latestLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    latestLabel.setAttribute("x", Math.max(pad.left + 24, xAt(clean.length - 1) - 8).toFixed(2));
    latestLabel.setAttribute("y", Math.max(14, yAt(last.score) - 8).toFixed(2));
    latestLabel.setAttribute("text-anchor", "end");
    latestLabel.classList.add("rb-chart-latest-label");
    latestLabel.textContent = last.value_label || last.score.toFixed(2);
    svg.appendChild(latestLabel);

    node.innerHTML = "";
    node.appendChild(svg);
  };

  const renderBarChart = (node, series) => {
    const clean = (series || []).filter((row) => row && typeof row.score === "number");
    if (!clean.length) {
      node.textContent = "차트 데이터 준비 중";
      return;
    }
    const width = 560;
    const height = 220;
    const pad = { left: 16, right: 16, top: 18, bottom: 34 };
    const barGap = 8;
    const chartWidth = width - pad.left - pad.right;
    const chartHeight = height - pad.top - pad.bottom;
    const maxAbs = Math.max(...clean.map((row) => Math.abs(row.score)), 0.1);
    const barWidth = (chartWidth - (clean.length - 1) * barGap) / clean.length;

    const svg = createSvg(width, height);
    clean.forEach((row, idx) => {
      const norm = Math.abs(row.score) / maxAbs;
      const h = Math.max(8, chartHeight * norm);
      const x = pad.left + idx * (barWidth + barGap);
      const y = pad.top + (chartHeight - h);
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", x.toFixed(2));
      rect.setAttribute("y", y.toFixed(2));
      rect.setAttribute("width", barWidth.toFixed(2));
      rect.setAttribute("height", h.toFixed(2));
      rect.classList.add("rb-chart-bar");
      if (row.score < 0) rect.classList.add("rb-chart-bar--negative");
      svg.appendChild(rect);

      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", (x + barWidth / 2).toFixed(2));
      label.setAttribute("y", (height - 12).toFixed(2));
      label.setAttribute("text-anchor", "middle");
      label.classList.add("rb-chart-bar-label");
      label.textContent = String(row.label || row.name || "").slice(0, 10);
      svg.appendChild(label);

      const value = document.createElementNS("http://www.w3.org/2000/svg", "text");
      value.setAttribute("x", (x + barWidth / 2).toFixed(2));
      value.setAttribute("y", Math.max(14, y - 6).toFixed(2));
      value.setAttribute("text-anchor", "middle");
      value.classList.add("rb-chart-bar-value");
      value.textContent = row.score.toFixed(2);
      svg.appendChild(value);
    });
    node.innerHTML = "";
    node.appendChild(svg);
  };

  document.querySelectorAll("[data-rb-chart]").forEach((node) => {
    const chartType = node.dataset.rbChart;
    let series = [];
    try {
      series = JSON.parse(node.dataset.rbChartSeries || "[]");
    } catch (_error) {
      series = [];
    }
    if (chartType === "line") {
      renderLineChart(node, series);
      return;
    }
    if (chartType === "bar") {
      renderBarChart(node, series);
    }
  });

  window.rbRenderLineChart = renderLineChart;

  const environmentModal = document.querySelector("[data-environment-modal]");
  if (environmentModal) {
    const modalTitle = environmentModal.querySelector("[data-environment-modal-title]");
    const modalMeta = environmentModal.querySelector("[data-environment-modal-meta]");
    const modalPeriod = environmentModal.querySelector("[data-environment-modal-period]");
    const modalChart = environmentModal.querySelector("[data-environment-modal-chart]");
    const closeModal = () => {
      environmentModal.hidden = true;
      document.body.classList.remove("has-open-modal");
    };
    environmentModal.querySelectorAll("[data-environment-modal-close]").forEach((button) => {
      button.addEventListener("click", closeModal);
    });
    document.querySelectorAll("[data-environment-chart-card]").forEach((card) => {
      card.addEventListener("click", () => {
        let series = [];
        try {
          series = JSON.parse(card.dataset.environmentSeries || "[]");
        } catch (_error) {
          series = [];
        }
        if (modalTitle) modalTitle.textContent = card.dataset.environmentTitle || "시장 환경 지표";
        if (modalMeta) modalMeta.textContent = card.dataset.environmentSource || "";
        if (modalPeriod) modalPeriod.textContent = card.dataset.environmentPeriod || "";
        if (modalChart) {
          modalChart.style.height = `${card.dataset.environmentPopupHeight || 420}px`;
          renderLineChart(modalChart, series);
        }
        environmentModal.hidden = false;
        document.body.classList.add("has-open-modal");
      });
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !environmentModal.hidden) {
        closeModal();
      }
    });
  }
})();
