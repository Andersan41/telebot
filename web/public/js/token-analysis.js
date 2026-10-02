/**
 * token-analysis.js — Token Analysis Tab Logic
 *
 * Layout: verdict first → strategy → market strip → indicators table →
 * levels scale → observations → context. Detail sections are collapsed
 * by default (Strategy stays open).
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

  async function analyzeToken(symbol) {
    symbol = symbol.trim().toUpperCase();
    if (!symbol) return;

    loading.style.display = 'flex';
    error.style.display = 'none';
    report.style.display = 'none';

    try {
      const resp = await fetch(`/api/token-report/${encodeURIComponent(symbol).replace('%2F', '/')}`);
      const data = await resp.json();

      if (data.error) {
        showError(data.error);
        return;
      }

      renderReport(data);
      loading.style.display = 'none';

      // Sync: dashboard follows this symbol; input shows the canonical form
      lastLoaded = data.symbol;
      input.value = data.symbol;
      Common.AppState.set(data.symbol, 'analysis');

    } catch (err) {
      showError('Ошибка сети: ' + err.message);
    }
  }

  function showError(msg) {
    loading.style.display = 'none';
    error.style.display = 'block';
    error.textContent = msg;
  }

  // ─── Cross-tab symbol sync (single source: Common.AppState) ────

  let lastLoaded = null;

  Common.AppState.onSymbolChange(({ symbol, source }) => {
    if (source === 'analysis') return;
    input.value = symbol;
    if (lastLoaded && Common.normSymbol(lastLoaded) !== Common.normSymbol(symbol)) {
      analyzeToken(symbol);
    }
  });

  // Auto-load the report for the current dashboard symbol on first open
  Common.AppState.onTabShown(({ tab }) => {
    if (tab !== 'token-analysis' || lastLoaded) return;
    const sym = Common.AppState.symbol;
    if (sym) {
      input.value = sym;
      analyzeToken(sym);
    }
  });

  const esc = (s) => Common.escapeHtml(s);

  // ─── Formatting helpers ─────────────────────────────────────────

  const fmtPrice = Common.fmtPrice;
  const fmtVol = Common.fmtVol;

  function fmtChange(val) {
    if (val === null || val === undefined) return null;
    const sign = val >= 0 ? '+' : '';
    return sign + val.toFixed(1) + '%';
  }

  function fmtSigned(val, digits) {
    const d = digits === undefined ? 1 : digits;
    return (val >= 0 ? '+' : '−') + Math.abs(val).toFixed(d) + '%';
  }

  function fmtUnits(v) {
    if (v >= 100) return v.toFixed(1);
    if (v >= 1) return v.toFixed(3);
    return v.toFixed(5);
  }

  function isNum(v) {
    return v !== null && v !== undefined && !Number.isNaN(v);
  }

  function signalClass(signal) {
    if (!signal) return '';
    const s = signal.toLowerCase();
    if (['growth', 'recovery', 'aligned up', 'bullish', 'trend', 'high', 'above avg'].includes(s)) return 'signal-bullish';
    if (['decline', 'falling', 'aligned down', 'bearish', 'low', 'below avg'].includes(s)) return 'signal-bearish';
    return 'signal-neutral';
  }

  const RU_SIGNAL = {
    'Neutral': 'нейтр.',
    'Bullish': 'быч.',
    'Bearish': 'медв.',
    'Overbought': 'перекуп.',
    'Oversold': 'перепрод.',
    'Growth': 'рост',
    'Recovery': 'рост',
    'Decline': 'падение',
    'Falling': 'падение',
    'Aligned Up': 'выше',
    'Aligned Down': 'ниже',
    'Trend': 'тренд',
    'Weak Trend': 'слаб. тренд',
    'Sideways': 'флэт',
    'High': 'высокий',
    'Above Avg': 'выше средн.',
    'Below Avg': 'ниже средн.',
    'Low': 'низкий',
  };

  function ru(signal) {
    return RU_SIGNAL[signal] || signal || '—';
  }

  const RU_TYPE = {
    'long_breakout': 'пробой вверх',
    'long_retest': 'возврат к поддержке',
    'short_rejection': 'отбой от сопротивления',
    'short_breakdown': 'пробой вниз',
    'wait': 'нет сетапа',
  };

  // ─── Sections ───────────────────────────────────────────────────

  function section(title, body, open) {
    return `<div class="ta-section"><details class="ta-details"${open ? ' open' : ''}>
      <summary class="ta-section-title">${title}</summary>
      ${body}
    </details></div>`;
  }

  // ─── Verdict ────────────────────────────────────────────────────

  function renderVerdict(data) {
    const rec = data.recommendation || 'WAIT';
    const mod = rec === 'LONG' ? 'bull' : rec === 'SHORT' ? 'bear' : 'wait';
    const v = data.rec_votes || {};
    const total = v.total || 0;

    const votes = total
      ? `<div class="ta-verdict-votes">
           <span class="signal-bullish">${v.bull} за</span>
           <span class="signal-bearish">${v.bear} против</span>
           <span>${v.neutral} нейтр.</span>
           <span class="ta-verdict-total">из ${total}</span>
         </div>`
      : '';

    return `<div class="ta-verdict ta-verdict--${mod}">
      <div class="ta-verdict-line">
        <span class="ta-verdict-label">Вердикт</span>
        <span class="ta-verdict-value">${rec}</span>
      </div>
      ${votes}
      ${data.recommendation_reason ? `<div class="ta-verdict-reason">${esc(data.recommendation_reason)}</div>` : ''}
    </div>`;
  }

  // ─── Market strip (items without data are hidden, not zeroed) ──

  function renderMarket(data) {
    const items = [];
    if (data.market_cap_rank) items.push(['Rank', '#' + data.market_cap_rank, '']);
    const vol = fmtVol(data.volume_24h);
    if (vol) items.push(['Vol 24h', vol, '']);
    [['24h', data.change_24h], ['7D', data.change_7d], ['30D', data.change_30d]].forEach(([label, val]) => {
      if (!isNum(val)) return;
      items.push([label, fmtChange(val), val >= 0 ? 'signal-bullish' : 'signal-bearish']);
    });
    if (!items.length) return '';
    return `<div class="ta-market-data">${items.map(([label, val, cls]) =>
      `<div class="ta-market-item">
         <span class="ta-label">${label}</span>
         <span class="ta-value ${cls}">${val}</span>
       </div>`).join('')}
    </div>`;
  }

  // ─── Strategy ───────────────────────────────────────────────────

  function setupStatus(s, price) {
    if (!isNum(s.entry_price) || !price) return { text: '—', cls: 'signal-neutral' };
    const d = (s.entry_price - price) / price * 100;
    if (Math.abs(d) < 0.15) return { text: 'в зоне входа', cls: 'signal-bullish' };
    const pct = fmtSigned(d);
    const text = {
      'long_breakout': `ожидает пробоя (${pct} до входа)`,
      'short_breakdown': `ожидает пробоя ниже (${pct} до входа)`,
      'long_retest': `ожидает возврата к входу (${pct})`,
      'short_rejection': `ожидает подъёма к входу (${pct})`,
    }[s.type] || `ожидает входа (${pct})`;
    return { text, cls: 'signal-neutral' };
  }

  function strategyCard(s, price) {
    const dirClass = s.direction === 'LONG' ? 'signal-bullish' : s.direction === 'SHORT' ? 'signal-bearish' : 'signal-neutral';
    const conf = { HIGH: 'высокая', MEDIUM: 'средняя', LOW: 'низкая' }[s.confidence] || s.confidence;

    let html = `<div class="ta-strategy"${isNum(s.entry_price) && isNum(s.sl_price) ? ` data-entry="${s.entry_price}" data-sl="${s.sl_price}"` : ''}>
      <div class="ta-strategy-header">
        <span class="ta-strategy-type ${dirClass}">${s.direction}</span>
        <span class="ta-strategy-label">${RU_TYPE[s.type] || s.type}</span>
        <span class="ta-conf conf-${String(s.confidence || '').toLowerCase()}">уверенность: ${conf}</span>
      </div>`;

    if (s.type === 'wait') {
      html += `<div class="ta-strategy-reason">${esc(s.reason)}</div></div>`;
      return html;
    }

    const status = setupStatus(s, price);
    html += `<div class="ta-status ${status.cls}">${status.text}</div>`;

    const fromEntry = (v) => isNum(v) && isNum(s.entry_price)
      ? `<span class="ta-det-dist ${v >= s.entry_price ? 'signal-bullish' : 'signal-bearish'}">${fmtSigned((v - s.entry_price) / s.entry_price * 100)}</span>`
      : '';

    html += `<div class="ta-strategy-details">`;
    html += `<div class="ta-det"><span class="ta-det-l">Entry</span><span class="ta-det-v">${esc(s.entry)}</span></div>`;
    if (s.stop_loss && s.stop_loss !== '-') {
      html += `<div class="ta-det"><span class="ta-det-l">SL</span><span class="ta-det-v signal-bearish">${esc(s.stop_loss)} ${fromEntry(s.sl_price)}</span></div>`;
    }
    if (s.tp1 && s.tp1 !== '-') {
      const rr = isNum(s.rr1) ? `<span class="ta-rr">R:R 1:${s.rr1}</span>` : '';
      html += `<div class="ta-det"><span class="ta-det-l">TP1</span><span class="ta-det-v signal-bullish">${esc(s.tp1)} ${fromEntry(s.tp1_price)} ${rr}</span></div>`;
    }
    if (s.tp2 && s.tp2 !== '-') {
      const rr = isNum(s.rr2) ? `<span class="ta-rr">R:R 1:${s.rr2}</span>` : '';
      html += `<div class="ta-det"><span class="ta-det-l">TP2</span><span class="ta-det-v signal-bullish">${esc(s.tp2)} ${fromEntry(s.tp2_price)} ${rr}</span></div>`;
    }
    if (s.tp3 && s.tp3 !== '-') {
      html += `<div class="ta-det"><span class="ta-det-l">TP3</span><span class="ta-det-v signal-bullish">${esc(s.tp3)} ${fromEntry(s.tp3_price)}</span></div>`;
    }
    html += `</div>`;

    if (isNum(s.sl_price)) {
      const cmp = s.direction === 'LONG' ? 'ниже' : 'выше';
      html += `<div class="ta-cancel">Сценарий невалиден, если закрытие 1H ${cmp} ${esc(s.stop_loss)}</div>`;
    }

    html += `<div class="ta-strategy-reason">${esc(s.reason)}</div>`;

    if (isNum(s.entry_price) && isNum(s.sl_price)) {
      html += `<div class="ta-calc">
        <label class="ta-calc-field">Депозит $<input type="number" class="ta-calc-in ta-calc-dep" min="1" step="any"></label>
        <label class="ta-calc-field">Риск %<input type="number" class="ta-calc-in ta-calc-risk" min="0.01" step="0.1"></label>
        <div class="ta-calc-out"></div>
      </div>`;
    }

    html += `</div>`;
    return html;
  }

  function bindCalculators() {
    const depDefault = localStorage.getItem('ta_dep') || '1000';
    const riskDefault = localStorage.getItem('ta_risk') || '1';
    const base = (document.querySelector('.ta-symbol') || {}).textContent || '';
    const baseCur = base.split('/')[0] || '';

    document.querySelectorAll('.ta-strategy[data-entry]').forEach(card => {
      const calc = card.querySelector('.ta-calc');
      if (!calc) return;
      const dep = calc.querySelector('.ta-calc-dep');
      const risk = calc.querySelector('.ta-calc-risk');
      const out = calc.querySelector('.ta-calc-out');
      const entry = parseFloat(card.dataset.entry);
      const sl = parseFloat(card.dataset.sl);
      dep.value = depDefault;
      risk.value = riskDefault;

      const update = () => {
        const d = parseFloat(dep.value);
        const r = parseFloat(risk.value);
        localStorage.setItem('ta_dep', dep.value || '1000');
        localStorage.setItem('ta_risk', risk.value || '1');
        if (!d || !r || !entry || !sl || entry === sl) {
          out.innerHTML = '';
          return;
        }
        const riskUsdt = d * r / 100;
        const stopDist = Math.abs(entry - sl);
        const units = riskUsdt / stopDist;
        const notional = units * entry;
        out.innerHTML = `Объём: <b>${fmtUnits(units)} ${baseCur}</b> (~$${Math.round(notional).toLocaleString('en-US')}) · Риск: <b>$${riskUsdt.toFixed(2)}</b> до SL`;
      };

      dep.addEventListener('input', update);
      risk.addEventListener('input', update);
      update();
    });
  }

  function renderStrategy(data) {
    if (!data.strategies || !data.strategies.length) return '';
    const body = `<div class="ta-strategies">${data.strategies.map(s => strategyCard(s, data.price)).join('')}</div>`;
    return section('Стратегия', body, true);
  }

  // ─── Indicators: 1H vs 4H summary table + signal bars ──────────

  function tfVotes(ind) {
    if (!ind) return { bull: 0, bear: 0, neutral: 0 };
    let bull = 0, bear = 0, neutral = 0;
    const add = v => { if (v > 0) bull++; else if (v < 0) bear++; else neutral++; };
    add(['Bullish', 'Oversold'].includes(ind.rsi_signal) ? 1 : ['Bearish', 'Overbought'].includes(ind.rsi_signal) ? -1 : 0);
    add(['Growth', 'Recovery'].includes(ind.macd_signal) ? 1 : ['Decline', 'Falling'].includes(ind.macd_signal) ? -1 : 0);
    add(ind.ema_signal === 'Aligned Up' ? 1 : ind.ema_signal === 'Aligned Down' ? -1 : 0);
    neutral++; // ADX — силa тренда без направления
    add(ind.supertrend_direction === 1 ? 1 : ind.supertrend_direction === -1 ? -1 : 0);
    neutral++; // Volume — активность без направления
    return { bull, bear, neutral };
  }

  function barHtml(v) {
    const cells = [];
    for (let i = 0; i < v.bull; i++) cells.push('<i class="b-bull"></i>');
    for (let i = 0; i < v.bear; i++) cells.push('<i class="b-bear"></i>');
    for (let i = 0; i < v.neutral; i++) cells.push('<i class="b-neu"></i>');
    return cells.join('');
  }

  function indCell(get) {
    return function(ind) {
      if (!ind) return `<div class="ta-ind-cell ta-na">—</div>`;
      const c = get(ind);
      return `<div class="ta-ind-cell"><span class="ta-ind-val">${c.val || ''}</span><span class="${c.cls}">${c.sig}</span></div>`;
    };
  }

  function renderIndicators(data) {
    const i1 = data.indicators_1h;
    const i4 = data.indicators_4h;
    if (!i1 && !i4) return `<div class="ta-na">Нет данных</div>`;

    const price = data.price;
    const rows = [
      ['RSI', indCell(i => ({ val: i.rsi.toFixed(1), sig: ru(i.rsi_signal), cls: signalClass(i.rsi_signal) }))],
      ['MACD', indCell(i => ({ val: '', sig: ru(i.macd_signal), cls: signalClass(i.macd_signal) }))],
      ['EMA', indCell(i => ({
        val: `${Math.round(i.ema_fast)}/${Math.round(i.ema_slow)}`,
        sig: price >= i.ema_slow ? 'цена выше' : 'цена ниже',
        cls: price >= i.ema_slow ? 'signal-bullish' : 'signal-bearish',
      }))],
      ['ADX', indCell(i => ({ val: i.adx.toFixed(1), sig: ru(i.adx_signal), cls: signalClass(i.adx_signal) }))],
      ['Supertrend', indCell(i => ({
        val: '',
        sig: i.supertrend_signal === 'Bullish' ? '🟢 бычий' : '🔴 медв.',
        cls: i.supertrend_signal === 'Bullish' ? 'signal-bullish' : 'signal-bearish',
      }))],
      ['Объём', indCell(i => ({ val: '', sig: ru(i.volume_signal), cls: signalClass(i.volume_signal) }))],
    ];

    let html = `<div class="ta-ind-table">
      <div class="ta-ind-row ta-ind-head">
        <div>Индикатор</div><div>1H</div><div>4H</div>
      </div>`;
    rows.forEach(([name, cell]) => {
      html += `<div class="ta-ind-row">
        <div class="ta-ind-name">${name}</div>
        ${cell(i1)}${cell(i4)}
      </div>`;
    });
    html += `</div>`;

    // Per-TF consensus bar
    html += `<div class="ta-tf-bars">`;
    [['1H', i1], ['4H', i4]].forEach(([label, ind]) => {
      if (!ind) return;
      const v = tfVotes(ind);
      html += `<div class="ta-tf-bar-row">
        <span class="ta-tf-label">${label}</span>
        <span class="ta-bar">${barHtml(v)}</span>
        <span class="ta-bar-sum"><b class="signal-bullish">${v.bull}</b> бычих · <b class="signal-bearish">${v.bear}</b> медв. · <b>${v.neutral}</b> нейтр.</span>
      </div>`;
    });
    html += `</div>`;

    return html;
  }

  // ─── Levels: single vertical scale with % distances ────────────

  function renderLevels(data) {
    const price = data.price;
    if (!price) return `<div class="ta-na">Нет данных</div>`;

    const entries = [];
    const push = (v, tf) => {
      if (!isNum(v)) return;
      for (const e of entries) {
        if (Math.abs(e.price - v) / e.price < 0.005) { e.tfs.add(tf); return; }
      }
      entries.push({ price: v, tfs: new Set([tf]) });
    };
    ['resistance_1h', 'resistance_4h'].forEach(key => (data[key] || []).slice(0, 3).forEach(v => push(v, key.endsWith('1h') ? '1H' : '4H')));
    ['support_1h', 'support_4h'].forEach(key => (data[key] || []).slice(0, 3).forEach(v => push(v, key.endsWith('1h') ? '1H' : '4H')));

    const resist = entries.filter(e => e.price > price).sort((a, b) => a.price - b.price).slice(0, 3);
    const suppor = entries.filter(e => e.price < price).sort((a, b) => b.price - a.price).slice(0, 3);

    if (!resist.length && !suppor.length) return `<div class="ta-na">Нет данных</div>`;

    const lvlRow = (tag, e) => {
      const dist = (e.price - price) / price * 100;
      return `<div class="ta-lvl ${tag[0] === 'R' ? 'lvl-r' : 'lvl-s'}">
        <span class="ta-lvl-tag">${tag}</span>
        <span class="ta-lvl-price">${fmtPrice(e.price)}</span>
        <span class="ta-lvl-tf">${[...e.tfs].join('+')}</span>
        <span class="ta-lvl-dist">${fmtSigned(dist)}</span>
      </div>`;
    };

    let html = `<div class="ta-scale">`;
    resist.slice().reverse().forEach((e, i) => { html += lvlRow('R' + (resist.length - i), e); });
    html += `<div class="ta-lvl ta-lvl-cur">
      <span class="ta-lvl-tag"></span>
      <span class="ta-lvl-price">${fmtPrice(price)}</span>
      <span class="ta-lvl-tf"></span>
      <span class="ta-lvl-dist">◄ цена</span>
    </div>`;
    suppor.forEach((e, i) => { html += lvlRow('S' + (i + 1), e); });
    html += `</div>`;

    return html;
  }

  // ─── Observations (✅ for / ⚠️ against / ℹ️ neutral) ────────────

  const OBS_ICONS = [['✅', 'bull'], ['⚠️', 'bear'], ['ℹ️', 'neutral']];

  function renderObservations(data) {
    if (!data.observations || !data.observations.length) return '';
    const items = data.observations.map(o => {
      let kind = 'neutral', text = o, icon = 'ℹ️';
      for (const [ic, k] of OBS_ICONS) {
        if (o.startsWith(ic)) { text = o.slice(ic.length).trim(); kind = k; icon = ic; break; }
      }
      return `<div class="ta-observation obs-${kind}"><span class="ta-obs-icon">${icon}</span><span>${esc(text)}</span></div>`;
    }).join('');
    return section('Наблюдения', `<div class="ta-observations">${items}</div>`);
  }

  // ─── Context chips (missing data shown as «нет данных», gray) ──

  function chip(label, value, cls) {
    return `<span class="ta-chip">${label} <b class="${cls || ''}">${value}</b></span>`;
  }

  function chipNA(label) {
    return `<span class="ta-chip ta-chip--na">${label}: нет данных</span>`;
  }

  function renderContext(data) {
    const chips = [];

    if (isNum(data.fear_greed)) {
      const cls = data.fear_greed >= 70 ? 'signal-bearish' : data.fear_greed <= 25 ? 'signal-bullish' : '';
      const warn = data.fear_greed >= 70 ? ' ⚠️' : '';
      chips.push(chip('F&G', `${data.fear_greed} ${esc(data.fear_greed_label || '')}${warn}`, cls));
    } else {
      chips.push(chipNA('F&G'));
    }

    if (isNum(data.funding_rate)) {
      const cls = data.funding_rate > 0.01 ? 'signal-bearish' : data.funding_rate < -0.01 ? 'signal-bullish' : '';
      chips.push(chip('Funding', data.funding_rate.toFixed(4) + '%', cls));
    } else {
      chips.push(chipNA('Funding'));
    }

    if (isNum(data.long_short_ratio)) {
      const cls = data.long_short_ratio > 1.5 ? 'signal-bearish' : data.long_short_ratio < 0.7 ? 'signal-bullish' : '';
      chips.push(chip('L/S', data.long_short_ratio.toFixed(2), cls));
    } else {
      chips.push(chipNA('L/S'));
    }

    if (isNum(data.oi_delta)) {
      chips.push(chip('OI Δ', fmtSigned(data.oi_delta), data.oi_delta >= 0 ? 'signal-bullish' : 'signal-bearish'));
    } else {
      chips.push(chipNA('OI Δ'));
    }

    return section('Контекст', `<div class="ta-chips">${chips.join('')}</div>`);
  }

  // ─── Report ─────────────────────────────────────────────────────

  function renderReport(data) {
    let html = '';

    // Header: ticker + price + verdict first
    html += `<div class="ta-header">
      <div class="ta-symbol">${esc(data.symbol)}</div>
      <div class="ta-price">${fmtPrice(data.price)}</div>
    </div>`;

    html += renderVerdict(data);
    html += renderMarket(data);
    html += renderStrategy(data);
    html += section('Индикаторы 1H vs 4H', renderIndicators(data));
    html += section('Уровни', renderLevels(data));
    html += renderObservations(data);
    html += renderContext(data);

    report.innerHTML = html;
    report.style.display = 'block';
    bindCalculators();
  }

})();
