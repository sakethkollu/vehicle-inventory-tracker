(() => {
  function formatMoneyShort(value) {
    if (value == null || Number.isNaN(Number(value))) return "-";
    const num = Number(value);
    const sign = num > 0 ? "+" : "";
    return `${sign}$${Math.round(num).toLocaleString()}`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderInsightsTable(title, rows, valueLabel, valueRender) {
    if (!rows.length) {
      return `
        <div class="geo-insight-panel">
          <h4>${escapeHtml(title)}</h4>
          <div class="chart-empty">Not enough priced data.</div>
        </div>
      `;
    }
    return `
      <div class="geo-insight-panel">
        <h4>${escapeHtml(title)}</h4>
        <table class="geo-insight-table">
          <thead>
            <tr><th>State</th><th>Vehicles</th><th>${escapeHtml(valueLabel)}</th></tr>
          </thead>
          <tbody>
            ${rows
              .map(
                (row) => `
              <tr>
                <td>${escapeHtml(row.state_code)}</td>
                <td class="num">${Number(row.vehicle_count || 0).toLocaleString()}</td>
                <td class="num">${valueRender(row)}</td>
              </tr>
            `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderDealerInsights(dealers) {
    const pricedDealers = (dealers || []).filter((row) => Number(row.priced_count || 0) > 0);
    const below = [...pricedDealers]
      .filter((row) => row.avg_msrp_delta != null)
      .sort((a, b) => a.avg_msrp_delta - b.avg_msrp_delta)
      .slice(0, 6);
    const above = [...pricedDealers]
      .filter((row) => row.avg_msrp_delta != null)
      .sort((a, b) => b.avg_msrp_delta - a.avg_msrp_delta)
      .slice(0, 6);

    const renderRow = (row) =>
      `<tr>
        <td>${escapeHtml(row.dealer_name || row.dealer_cd)}</td>
        <td class="num">${Number(row.vehicle_count || 0).toLocaleString()}</td>
        <td class="num">${formatMoneyShort(row.avg_msrp_delta)}</td>
      </tr>`;

    return `
      <div class="geo-insight-panel">
        <h4>Dealers Most Below MSRP</h4>
        ${
          below.length
            ? `<table class="geo-insight-table"><thead><tr><th>Dealer</th><th>Count</th><th>Avg Delta</th></tr></thead><tbody>${below.map(renderRow).join("")}</tbody></table>`
            : `<div class="chart-empty">Not enough dealer pricing data.</div>`
        }
      </div>
      <div class="geo-insight-panel">
        <h4>Dealers Most Above MSRP</h4>
        ${
          above.length
            ? `<table class="geo-insight-table"><thead><tr><th>Dealer</th><th>Count</th><th>Avg Delta</th></tr></thead><tbody>${above.map(renderRow).join("")}</tbody></table>`
            : `<div class="chart-empty">Not enough dealer pricing data.</div>`
        }
      </div>
    `;
  }

  function renderGeoAnalyticsSection(data) {
    const summary = data?.summary || {};
    const states = data?.states || [];
    const priced = Number(summary.priced_count || 0);
    const belowPct =
      priced > 0 ? Math.round((Number(summary.below_msrp_count || 0) / priced) * 100) : null;
    const mapped = Number(summary.mapped_count || 0);
    const total = Number(summary.vehicle_count || 0);

    const pricedStates = states.filter((row) => Number(row.priced_count || 0) > 0);
    const belowStates = [...pricedStates]
      .sort((a, b) => (a.avg_msrp_delta ?? 0) - (b.avg_msrp_delta ?? 0))
      .slice(0, 6);
    const aboveStates = [...pricedStates]
      .sort((a, b) => (b.avg_msrp_delta ?? 0) - (a.avg_msrp_delta ?? 0))
      .slice(0, 6);

    const captionParts = [
      `${total.toLocaleString()} vehicles in selection`,
      `${mapped.toLocaleString()} with dealer coordinates`,
    ];
    if (Number(summary.unmapped_count || 0) > 0) {
      captionParts.push(`${Number(summary.unmapped_count).toLocaleString()} awaiting dealer geocode`);
    }
    if (belowPct != null) {
      captionParts.push(`${belowPct}% of priced vehicles below MSRP`);
    }

    return `
      <h3>Geography &amp; MSRP Analytics</h3>
      <div class="geo-map-summary">
        <span class="geo-map-stat"><strong>${total.toLocaleString()}</strong> filtered</span>
        <span class="geo-map-stat"><strong>${mapped.toLocaleString()}</strong> geolocated</span>
        <span class="geo-map-stat"><strong>${(data.dealers || []).length.toLocaleString()}</strong> dealers</span>
        ${
          belowPct != null
            ? `<span class="geo-map-stat"><strong>${belowPct}%</strong> below MSRP</span>`
            : ""
        }
      </div>
      <div class="chart-caption">${escapeHtml(captionParts.join(" · "))}</div>
      <div class="geo-insights-grid">
        ${renderInsightsTable("States Most Below MSRP", belowStates, "Avg Delta", (row) =>
          formatMoneyShort(row.avg_msrp_delta)
        )}
        ${renderInsightsTable("States Most Above MSRP", aboveStates, "Avg Delta", (row) =>
          formatMoneyShort(row.avg_msrp_delta)
        )}
        ${renderDealerInsights(data.dealers || [])}
      </div>
    `;
  }

  window.VitGeoMap = {
    renderGeoMapSection: renderGeoAnalyticsSection,
    renderGeoMapSectionAsync: async (data) => renderGeoAnalyticsSection(data),
  };
})();
