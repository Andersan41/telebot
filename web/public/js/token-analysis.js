/**
 * token-analysis.js — Token Analysis Tab Logic
 */

(function() {
  'use strict';

  const input = document.getElementById('tokenAnalysisInput');
  const btn = document.getElementById('tokenAnalysisBtn');
  const loading = document.getElementById('tokenAnalysisLoading');
  const error = document.getElementById('tokenAnalysisError');
  const report = document.getElementById('tokenAnalysisReport');

  // Quick token buttons
  document.querySelectorAll('.qtok-analysis').forEach(el => {
    el.addEventListener('click', () => {
      input.value = el.dataset.symbol;
      analyzeToken(el.dataset.symbol);
    });
  });

  // Enter key
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      analyzeToken(input.value);
    }
  });

  // Button click
  btn.addEventListener('click', () => {
    analyzeToken(input.value);
  });

  // Tab switching
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
      btn.classList.add('active');
      const tabId = 'tab-' + btn.dataset.tab;
      document.getElementById(tabId).classList.remove('hidden');
    });
  });

  async function analyzeToken(symbol) {
    symbol = symbol.trim().toUpperCase();
    if (!symbol) return;

    loading.style.display = 'flex';
    error.style.display = 'none';
    report.style.display = 'none';

    try {
      const resp = await fetch(`/api/token-report/${symbol}`);
      const data = await resp.json();

      if (data.error) {
        showError(data.error);
        return;
      }

      renderReport(data);
      loading.style.display = 'none';

    } catch (err) {
      showError('Ошибка сети: ' + err.message);
    }
  }

  function showError(msg) {
    loading.style.display = 'none';
    error.style.display = 'block';
    error.textContent = msg;
  }

  function fmtPrice(val) {
    if (val === null || val === undefined) return '—';
    if (val < 0.001) return '$' + val.toFixed(8);
    if (val < 0.10) return '$' + val.toFixed(6);
    if (val < 1) return '$' + val.toFixed(4);
    if (val < 100) return '$' + val.toFixed(4);
    return '$' + val.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }

  function fmtVol(val) {
    if (!val) return '—';
    if (val >= 1e9) return '$' + (val/1e9).toFixed(1) + 'B';
    if (val >= 1e6) return '$' + (val/1e6).toFixed(1) + 'M';
    if (val >= 1e3) return '$' + (val/1e3).toFixed(1) + 'K';
    return '$' + val.toFixed(0);
  }

  function fmtChange(val) {
    if (val === null || val === undefined) return 'N/A';
    const sign = val >= 0 ? '+' : '';
    return sign + val.toFixed(1) + '%';
  }

  function signalClass(signal) {
    if (!signal) return '';
    const s = signal.toLowerCase();
    if (['growth', 'aligned up', 'bullish', 'trend', 'high', 'above avg'].includes(s)) return 'signal-bullish';
    if (['decline', 'aligned down', 'bearish', 'low', 'below avg'].includes(s)) return 'signal-bearish';
    return 'signal-neutral';
  }

  function renderReport(data) {
    let html = '';

    // Header
    html += `<div class="ta-header">
      <div class="ta-symbol">${data.symbol}</div>
      <div class="ta-price">${fmtPrice(data.price)}</div>
    </div>`;

    // Market data
    html += `<div class="ta-market-data">
      <div class="ta-market-item">
        <span class="ta-label">Rank</span>
        <span class="ta-value">${data.market_cap_rank ? '#' + data.market_cap_rank : '—'}</span>
      </div>
      <div class="ta-market-item">
        <span class="ta-label">Vol 24h</span>
        <span class="ta-value">${fmtVol(data.volume_24h)}</span>
      </div>
      <div class="ta-market-item">
        <span class="ta-label">24h</span>
        <span class="ta-value ${data.change_24h >= 0 ? 'signal-bullish' : 'signal-bearish'}">${fmtChange(data.change_24h)}</span>
      </div>
      <div class="ta-market-item">
        <span class="ta-label">7D</span>
        <span class="ta-value ${data.change_7d >= 0 ? 'signal-bullish' : 'signal-bearish'}">${fmtChange(data.change_7d)}</span>
      </div>
      <div class="ta-market-item">
        <span class="ta-label">30D</span>
        <span class="ta-value ${data.change_30d >= 0 ? 'signal-bullish' : 'signal-bearish'}">${fmtChange(data.change_30d)}</span>
      </div>
    </div>`;

    // Indicators 1H
    if (data.indicators_1h) {
      html += renderIndicators('1H', data.indicators_1h);
    }

    // Indicators 4H
    if (data.indicators_4h) {
      html += renderIndicators('4H', data.indicators_4h);
    }

    // Context
    html += `<div class="ta-section">
      <div class="ta-section-title">🌍 Контекст</div>
      <div class="ta-context-grid">
        <div class="ta-context-item">
          <span class="ta-label">F&G</span>
          <span class="ta-value">${data.fear_greed || '—'} (${data.fear_greed_label || 'N/A'})</span>
        </div>
        <div class="ta-context-item">
          <span class="ta-label">Funding</span>
          <span class="ta-value">${data.funding_rate ? data.funding_rate.toFixed(4) + '%' : '—'}</span>
        </div>
        <div class="ta-context-item">
          <span class="ta-label">Long/Short</span>
          <span class="ta-value">${data.long_short_ratio ? data.long_short_ratio.toFixed(2) : '—'}</span>
        </div>
        <div class="ta-context-item">
          <span class="ta-label">OI Delta</span>
          <span class="ta-value">${data.oi_delta ? data.oi_delta.toFixed(1) + '%' : '—'}</span>
        </div>
      </div>
    </div>`;

    // Levels
    html += `<div class="ta-section">
      <div class="ta-section-title">📍 Уровни</div>
      <div class="ta-levels-grid">`;

    if (data.resistance_1h && data.resistance_1h.length) {
      html += `<div class="ta-levels-card resistance">
        <div class="ta-levels-label">R (1H)</div>
        <div class="ta-levels-list">
          ${data.resistance_1h.slice(0, 3).map((r, i) => `<div class="ta-level">R${i+1}: ${fmtPrice(r)}</div>`).join('')}
        </div>
      </div>`;
    }
    if (data.support_1h && data.support_1h.length) {
      html += `<div class="ta-levels-card support">
        <div class="ta-levels-label">S (1H)</div>
        <div class="ta-levels-list">
          ${data.support_1h.slice(0, 3).map((s, i) => `<div class="ta-level">S${i+1}: ${fmtPrice(s)}</div>`).join('')}
        </div>
      </div>`;
    }
    if (data.resistance_4h && data.resistance_4h.length) {
      html += `<div class="ta-levels-card resistance">
        <div class="ta-levels-label">R (4H)</div>
        <div class="ta-levels-list">
          ${data.resistance_4h.slice(0, 3).map((r, i) => `<div class="ta-level">R${i+1}: ${fmtPrice(r)}</div>`).join('')}
        </div>
      </div>`;
    }
    if (data.support_4h && data.support_4h.length) {
      html += `<div class="ta-levels-card support">
        <div class="ta-levels-label">S (4H)</div>
        <div class="ta-levels-list">
          ${data.support_4h.slice(0, 3).map((s, i) => `<div class="ta-level">S${i+1}: ${fmtPrice(s)}</div>`).join('')}
        </div>
      </div>`;
    }

    html += `</div></div>`;

    // Strategies
    if (data.strategies && data.strategies.length) {
      html += `<div class="ta-section">
        <div class="ta-section-title">💼 Стратегии</div>
        <div class="ta-strategies">`;

      data.strategies.forEach((s, i) => {
        const dirClass = s.direction === 'LONG' ? 'signal-bullish' : s.direction === 'SHORT' ? 'signal-bearish' : 'signal-neutral';
        html += `<div class="ta-strategy">
          <div class="ta-strategy-header">
            <span class="ta-strategy-num">${i+1}.</span>
            <span class="ta-strategy-type ${dirClass}">${s.direction}</span>
            <span class="ta-strategy-label">${s.type}</span>
          </div>
          <div class="ta-strategy-details">
            <div>Entry: ${s.entry}</div>
            <div>SL: ${s.stop_loss}</div>
            <div>TP1: ${s.tp1} | TP2: ${s.tp2 || '—'}</div>
            <div>R:R: ${s.rr_ratio}</div>
          </div>
          <div class="ta-strategy-reason">${s.reason}</div>
        </div>`;
      });

      html += `</div></div>`;
    }

    // Observations
    if (data.observations && data.observations.length) {
      html += `<div class="ta-section">
        <div class="ta-section-title">💡 Наблюдения</div>
        <div class="ta-observations">
          ${data.observations.map(o => `<div class="ta-observation">${o}</div>`).join('')}
        </div>
      </div>`;
    }

    // Recommendation
    const recClass = data.recommendation === 'LONG' ? 'signal-bullish' : data.recommendation === 'SHORT' ? 'signal-bearish' : 'signal-neutral';
    html += `<div class="ta-section">
      <div class="ta-recommendation ${recClass}">
        <div class="ta-rec-label">Рекомендация:</div>
        <div class="ta-rec-value">${data.recommendation}</div>
        ${data.recommendation_reason ? `<div class="ta-rec-reason">${data.recommendation_reason}</div>` : ''}
      </div>
    </div>`;

    report.innerHTML = html;
    report.style.display = 'block';
  }

  function renderIndicators(label, ind) {
    let html = `<div class="ta-section">
      <div class="ta-section-title">📊 Индикаторы ${label}</div>
      <div class="ta-indicators-grid">`;

    const indicators = [
      { name: 'RSI', value: ind.rsi, signal: ind.rsi_signal },
      { name: 'MACD', value: ind.macd, signal: ind.macd_signal },
      { name: 'EMA', value: `${ind.ema_fast}/${ind.ema_slow}`, signal: ind.ema_signal },
      { name: 'ADX', value: ind.adx, signal: ind.adx_signal },
      { name: 'Supertrend', value: ind.supertrend_signal, signal: ind.supertrend_signal },
      { name: 'Volume', value: ind.volume_signal, signal: ind.volume_signal },
    ];

    indicators.forEach(ind => {
      html += `<div class="ta-indicator">
        <div class="ta-indicator-name">${ind.name}</div>
        <div class="ta-indicator-value">${ind.value}</div>
        <div class="ta-indicator-signal ${signalClass(ind.signal)}">${ind.signal}</div>
      </div>`;
    });

    html += `</div></div>`;
    return html;
  }

})();
