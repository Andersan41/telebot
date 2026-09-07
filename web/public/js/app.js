// =====================================================
// Trading Signal Bot — Dashboard Frontend
// =====================================================

const WS_URL = `ws://${location.host}/ws`;
let socket = null;
let priceChart = null;
let reconnectTimer = null;
let currentTimeframe = null;

// ── Init ────────────────────────────────────────────
function connect() {
  socket = new WebSocket(WS_URL);

  socket.onopen = () => {
    updateStatus('Анализ активен');
    clearTimeout(reconnectTimer);
    hideLoader();
  };

  socket.onclose = () => {
    updateStatus('Переподключение...');
    showLoader('Переподключение к серверу...');
    reconnectTimer = setTimeout(connect, 3000);
  };

  socket.onerror = () => updateStatus('Ошибка соединения');

  socket.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === 'update') renderDashboard(data);
      if (data.type === 'open_trades') renderOpenTrades(data.trades || []);
      if (data.type === 'init') renderTimeframePicker(data);
    } catch (err) {
      console.error('Parse error:', err);
    }
  };
}

// ── Render ──────────────────────────────────────────
function renderDashboard(data) {
  const { indicators, structure, liquidity, levels, signal, priceHistory, price, symbol, error, openInterest, volumeProfile, bookAnomalies, waves, footprint } = data;

  if (error) {
    updateStatus(`Ошибка: ${error}`);
    return;
  }

  const sym = (symbol || '').replace('/USDT', '');
  updateStatus(`Анализ активен · ${sym} $${Number(price || 0).toLocaleString()}`);

  if (indicators) renderIndicators(indicators);
  if (signal) renderSignal(signal);
  if (levels) renderLevelsData(levels);
  if (structure) renderSMC(structure, liquidity);
  if (priceHistory) updatePriceChart(priceHistory);
  if (openInterest) renderOpenInterest(openInterest);
  if (volumeProfile) renderVolumeProfile(volumeProfile, price);
  if (bookAnomalies) renderBookAnomalies(bookAnomalies);
  if (waves) renderWaves(waves, price);

  if (footprint) footprintChart.updateFromData(footprint);

  renderVerdictFromSignal(signal, indicators);
}

// ── Indicators ──────────────────────────────────────
function renderIndicators(ind) {
  // RSI
  const rsiSignal = ind.rsi > 70 ? 'bearish' : ind.rsi > 55 ? 'bullish' : ind.rsi > 45 ? 'neutral' : ind.rsi > 30 ? 'bearish' : 'bullish';
  renderCard('rsi', ind.rsi?.toFixed(1) || '—', rsiLabel(ind.rsi), rsiSignal, ind.rsi);

  // MACD
  const macdSig = ind.macd_bullish_cross ? 'bullish_cross' : ind.macd_bearish_cross ? 'bearish_cross' : ind.macd_hist > 0 ? 'bullish' : 'bearish';
  const macdLabel = ind.macd_bullish_cross ? 'Бычье пересечение' : ind.macd_bearish_cross ? 'Медвежье пересечение' : ind.macd_hist > 0 ? 'Выше нуля' : 'Ниже нуля';
  renderCard('macd', ind.macd_hist?.toFixed(2) || '—', macdLabel, macdSig, 50 + (ind.macd_hist || 0) * 10);

  // EMA
  const emaSig = ind.ema_bullish_alignment ? 'bullish' : ind.ema_bearish_alignment ? 'bearish' : 'neutral';
  const emaLabel = ind.ema_bullish_cross ? 'Бычье пересечение' : ind.ema_bearish_cross ? 'Медвежье пересечение' :
    ind.ema_bullish_alignment ? 'Aligned ↑' : ind.ema_bearish_alignment ? 'Aligned ↓' : 'Neutr.';
  renderCard('ema', ind.ema_fast?.toFixed(0) || '—', emaLabel, emaSig, 50);

  // ADX
  const adxSig = ind.trend_is_strong ? (ind.dmi_plus > ind.dmi_minus ? 'bullish' : 'bearish') : 'neutral';
  const adxLabel = ind.trend_is_strong ? `Trend (${ind.dmi_plus?.toFixed(1)} / ${ind.dmi_minus?.toFixed(1)})` : `Flat (${ind.adx?.toFixed(1)})`;
  renderCard('adx', ind.adx?.toFixed(1) || '—', adxLabel, adxSig, Math.min(100, (ind.adx || 0) * 2.5));

  // Supertrend
  const stSig = ind.supertrend_bullish ? 'bullish' : 'bearish';
  const stLabel = ind.supertrend_bullish ? 'Bullish trend' : 'Bearish trend';
  renderCard('st', ind.supertrend?.toFixed(0) || '—', stLabel, stSig, ind.supertrend_bullish ? 70 : 30);

  // Volume
  const volSig = ind.volume_above_avg ? 'bullish' : 'bearish';
  const volLabel = ind.volume_above_avg ? `Above SMA (${((ind.volume / ind.volume_sma) * 100).toFixed(0)}%)` : 'Below average';
  const volPct = ind.volume_sma > 0 ? Math.min(100, (ind.volume / ind.volume_sma) * 50) : 50;
  renderCard('vol', ind.volume?.toFixed(0) || '—', volLabel, volSig, volPct);
}

function rsiLabel(rsi) {
  if (!rsi) return '—';
  if (rsi >= 70) return 'Перекупленность';
  if (rsi >= 55) return 'Зона роста';
  if (rsi >= 45) return 'Нейтрально';
  if (rsi >= 30) return 'Зона снижения';
  return 'Перепроданность';
}

function renderCard(id, value, sub, signal, barWidth) {
  setText(`val-${id}`, value);
  setText(`sub-${id}`, sub);

  const signalMap = {
    bullish:       { text: 'Рост',       cls: 'badge-bull', bar: 'bar-green'  },
    bullish_cross: { text: 'Рост',       cls: 'badge-bull', bar: 'bar-green'  },
    bearish:       { text: 'Падение',    cls: 'badge-bear', bar: 'bar-red'    },
    bearish_cross: { text: 'Падение',    cls: 'badge-bear', bar: 'bar-red'    },
    neutral:       { text: 'Нейтрально', cls: 'badge-neu',  bar: 'bar-orange' }
  };
  const s = signalMap[signal] || signalMap.neutral;

  const badge = document.getElementById(`badge-${id}`);
  if (badge) { badge.textContent = s.text; badge.className = `badge ${s.cls}`; }

  const bar = document.getElementById(`bar-${id}`);
  if (bar) {
    bar.className = `bar-fill ${s.bar}`;
    bar.style.width = clamp(barWidth ?? 50, 0, 100) + '%';
  }
}

// ── Signal ──────────────────────────────────────────
function renderSignal(sig) {
  const card = document.getElementById('signalCard');
  const typeEl = document.getElementById('signalType');
  const scoreEl = document.getElementById('signalScore');

  const signal = sig.signal || 'NO_SIGNAL';
  const isBuy = signal === 'BUY';
  const isSell = signal === 'SELL';

  card.className = `signal-card ${isBuy ? 'buy' : isSell ? 'sell' : 'no'}`;
  typeEl.className = `signal-type ${isBuy ? 'buy' : isSell ? 'sell' : 'no'}`;
  typeEl.textContent = signal === 'BUY' ? 'BUY — ПОКУПКА' : signal === 'SELL' ? 'SELL — ПРОДАЖА' : 'НЕТ СИГНАЛА';
  scoreEl.textContent = `Score: ${sig.score || 0} | ${sig.verdict || ''}`;

  setText('signalEntry', sig.entry ? `$${sig.entry.toLocaleString()}` : '—');
  setText('signalSL', sig.sl ? `$${sig.sl.toLocaleString()}` : '—');
  setText('signalTP', sig.tp ? `$${sig.tp.toLocaleString()}` : '—');

  const reasonsEl = document.getElementById('signalReasons');
  if (sig.reasons && sig.reasons.length > 0) {
    reasonsEl.innerHTML = '<ul>' + sig.reasons.map(r => `<li>${escapeHtml(r)}</li>`).join('') + '</ul>';
  } else {
    reasonsEl.innerHTML = '';
  }
}

// ── Levels ──────────────────────────────────────────
function renderLevelsData(levels) {
  renderLevels(levels.resistance || [], 'resistance-list', false);
  renderLevels(levels.support || [], 'support-list', true);
}

function renderLevels(items, containerId, isSupport) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const strCls = { strong: 'str-strong', medium: 'str-medium', weak: 'str-weak' };
  const strRu = { strong: 'Сильный', medium: 'Средний', weak: 'Слабый' };

  container.innerHTML = items.map(lvl => `
    <div class="level-row">
      <span class="${isSupport ? 'level-dot-g' : 'level-dot-r'}"></span>
      <span class="level-price">$${Number(lvl.price || 0).toLocaleString(undefined, {minimumFractionDigits: 4, maximumFractionDigits: 4})}</span>
      <span class="str-pill ${strCls[lvl.strength] || 'str-medium'}">${strRu[lvl.strength] || 'Средний'}</span>
    </div>
  `).join('') || '<div style="font-size:11px;color:#444;padding:4px 0;">Нет данных</div>';
}

// ── Verdict ─────────────────────────────────────────
function renderVerdictFromSignal(signal, indicators) {
  const verdictMain = document.getElementById('verdict-main');
  const verdictConf = document.getElementById('verdict-conf');
  const verdictRegime = document.getElementById('verdict-regime');
  const verdictTrend = document.getElementById('verdict-trend');
  const confBar = document.getElementById('conf-bar');

  if (!signal || !verdictMain) return;

  const conf = signal.confidence || 0;
  const verdict = signal.verdict || '—';
  const isBull = signal.signal === 'BUY';
  const isBear = signal.signal === 'SELL';

  verdictMain.textContent = verdict;
  verdictMain.style.color = isBull ? '#a3e635' : isBear ? '#f87171' : '#facc15';
  verdictConf.textContent = `Confidence: ${conf.toFixed(1)}%`;
  confBar.style.width = clamp(conf, 0, 100) + '%';

  setText('verdict-regime', signal.regime || '—');
  setText('verdict-trend', indicators?.trend_is_strong ? 'Strong' : 'Weak');
}

// ── SMC ─────────────────────────────────────────────
function renderSMC(structure, liquidity) {
  const container = document.getElementById('smc-list');
  if (!container) return;

  const items = [];

  // BOS
  if (structure?.bos && structure.bos.type !== 'none') {
    items.push({
      iconCls: structure.bos.type === 'bullish' ? 'smc-icon-green' : 'smc-icon-red',
      icon: structure.bos.type === 'bullish' ? '↗' : '↘',
      name: 'Break of Structure',
      desc: `${structure.bos.type} @ $${(structure.bos.level || 0).toLocaleString()}`,
      badgeCls: structure.bos.type === 'bullish' ? 'smc-bull' : 'smc-target',
      badge: structure.bos.type === 'bullish' ? '+Bull' : '-Bear'
    });
  }

  // Order Blocks
  if (liquidity?.order_blocks) {
    liquidity.order_blocks.slice(0, 2).forEach(ob => {
      items.push({
        iconCls: 'smc-icon-blue', icon: '▣',
        name: 'Order Block',
        desc: `${ob.type} @ $${(ob.price || 0).toLocaleString()}`,
        badgeCls: 'smc-support', badge: 'Поддержка'
      });
    });
  }

  // FVG
  if (liquidity?.fvg) {
    liquidity.fvg.slice(0, 1).forEach(f => {
      items.push({
        iconCls: 'smc-icon-yellow', icon: '═',
        name: 'Fair Value Gap',
        desc: `$${(f.bottom || 0).toLocaleString()} — $${(f.top || 0).toLocaleString()}`,
        badgeCls: 'smc-magnet', badge: 'Магнит'
      });
    });
  }

  // Sweep
  if (liquidity?.sweep?.detected) {
    items.push({
      iconCls: 'smc-icon-red', icon: '⚠',
      name: 'Liquidity Sweep',
      desc: `${liquidity.sweep.type} sweep detected`,
      badgeCls: 'smc-target', badge: 'Цель'
    });
  }

  // Trend
  if (structure?.trend) {
    items.push({
      iconCls: structure.trend === 'bullish' ? 'smc-icon-green' : structure.trend === 'bearish' ? 'smc-icon-red' : 'smc-icon-yellow',
      icon: '◈',
      name: 'Market Trend',
      desc: structure.trend,
      badgeCls: structure.trend === 'bullish' ? 'smc-bull' : structure.trend === 'bearish' ? 'smc-target' : 'smc-magnet',
      badge: structure.trend
    });
  }

  container.innerHTML = items.map(it => `
    <div class="smc-item">
      <div class="smc-icon ${it.iconCls}">${it.icon}</div>
      <div>
        <div class="smc-name">${it.name}</div>
        <div class="smc-desc">${it.desc}</div>
      </div>
      <span class="smc-badge ${it.badgeCls}">${it.badge}</span>
    </div>
  `).join('') || '<div style="font-size:11px;color:#444;padding:4px 0;">Нет данных SMC</div>';
}

// ── Chart ───────────────────────────────────────────
function updatePriceChart(history) {
  const canvas = document.getElementById('priceChart');
  if (!canvas || !history || history.length === 0) return;

  const labels = history.map((_, i) => `H${i + 1}`);
  const prices = history.map(h => h.close);

  if (!priceChart) {
    const ctx = canvas.getContext('2d');
    priceChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          data: prices,
          borderColor: '#a3e635',
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.4,
          fill: true,
          backgroundColor: (ctx) => {
            const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, 110);
            g.addColorStop(0, 'rgba(163,230,53,0.15)');
            g.addColorStop(1, 'rgba(163,230,53,0)');
            return g;
          }
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: { label: c => '$' + c.raw.toLocaleString() },
            backgroundColor: '#1a1a1a', titleColor: '#888',
            bodyColor: '#e0e0e0', borderColor: '#2a2a2a', borderWidth: 1
          }
        },
        scales: {
          x: { ticks: { color: '#555', font: { size: 9 } }, grid: { color: '#1a1a1a' } },
          y: {
            ticks: { color: '#555', font: { size: 9 }, callback: v => '$' + (v/1000).toFixed(1) + 'k' },
            grid: { color: '#1e1e1e' }
          }
        }
      }
    });
  } else {
    priceChart.data.labels = labels;
    priceChart.data.datasets[0].data = prices;
    priceChart.update('none');
  }
}

// ── Open Interest ──────────────────────────────────
function renderOpenInterest(oi) {
  const value = oi.current || 0;
  const change = oi.change_pct || 0;
  const trend = oi.trend || 'none';

  setText('val-oi', value > 1000000 ? (value / 1000000).toFixed(2) + 'M' : value > 1000 ? (value / 1000).toFixed(1) + 'K' : value.toFixed(0));

  const changeEl = document.getElementById('oi-change');
  if (changeEl) {
    const sign = change >= 0 ? '+' : '';
    changeEl.textContent = `${sign}${change.toFixed(1)}%`;
    changeEl.className = `oi-change ${change > 0 ? 'bull' : change < 0 ? 'bear' : 'neu'}`;
  }

  const trendEl = document.getElementById('oi-trend');
  if (trendEl) {
    const trendMap = { increasing: 'Растёт', decreasing: 'Снижается', stable: 'Стабилен' };
    trendEl.textContent = trendMap[trend] || '—';
    trendEl.className = `oi-detail-value ${trend === 'increasing' ? 'bull' : trend === 'decreasing' ? 'bear' : 'neu'}`;
  }

  setText('oi-value-usd', oi.value_usd ? '$' + formatLargeNumber(oi.value_usd) : '—');

  const badge = document.getElementById('badge-oi');
  if (badge) {
    const badgeInfo = change > 5 ? { text: 'Рост', cls: 'badge-bull' }
      : change < -5 ? { text: 'Снижение', cls: 'badge-bear' }
      : { text: 'Стабильно', cls: 'badge-neu' };
    badge.textContent = badgeInfo.text;
    badge.className = `badge ${badgeInfo.cls}`;
  }

  const bar = document.getElementById('bar-oi');
  if (bar) {
    const pct = clamp(50 + change * 3, 0, 100);
    bar.className = `bar-fill ${change > 0 ? 'bar-green' : change < 0 ? 'bar-red' : 'bar-orange'}`;
    bar.style.width = pct + '%';
  }
}

// ── Volume Profile ─────────────────────────────────
function renderVolumeProfile(vp, currentPrice) {
  setText('vp-poc', vp.poc ? '$' + formatPrice(vp.poc) : '—');
  setText('vp-vah', vp.vah ? '$' + formatPrice(vp.vah) : '—');
  setText('vp-val', vp.val ? '$' + formatPrice(vp.val) : '—');

  const container = document.getElementById('vp-histogram');
  if (!container || !vp.profile || vp.profile.length === 0) return;

  const maxPct = Math.max(...vp.profile.map(p => p.pct), 1);
  const pocPrice = vp.poc || 0;

  container.innerHTML = vp.profile.slice().reverse().map(bar => {
    const isPoc = Math.abs(bar.price - pocPrice) / pocPrice < 0.001;
    const inVA = bar.price >= (vp.val || 0) && bar.price <= (vp.vah || Infinity);
    let cls = 'vp-bar';
    if (isPoc) cls += ' vp-bar-poc';
    else if (inVA) cls += ' vp-bar-va';
    else cls += ' vp-bar-outer';

    return `<div class="${cls}" style="width:${bar.pct}%" title="$${formatPrice(bar.price)}: ${bar.volume}"></div>`;
  }).join('');
}

// ── Book Anomalies ─────────────────────────────────
function renderBookAnomalies(book) {
  const bidVol = book.total_bid || 0;
  const askVol = book.total_ask || 0;
  const total = bidVol + askVol;

  setText('book-bid-vol', bidVol > 1000 ? (bidVol / 1000).toFixed(1) + 'K' : bidVol.toFixed(1));
  setText('book-ask-vol', askVol > 1000 ? (askVol / 1000).toFixed(1) + 'K' : askVol.toFixed(1));
  setText('book-spread', book.spread_pct ? book.spread_pct.toFixed(3) + '%' : '—');

  const bidPct = total > 0 ? (bidVol / total * 100) : 50;
  const bidBar = document.getElementById('bar-book-bid');
  if (bidBar) {
    bidBar.style.width = bidPct + '%';
    bidBar.className = `bar-fill ${bidPct > 60 ? 'bar-green' : bidPct < 40 ? 'bar-red' : 'bar-orange'}`;
  }

  const badge = document.getElementById('badge-book');
  if (badge) {
    const imbalance = book.imbalance || 0;
    const absImb = Math.abs(imbalance);
    if (absImb > 0.3) {
      badge.textContent = imbalance > 0 ? 'Bid доминирует' : 'Ask доминирует';
      badge.className = `badge ${imbalance > 0 ? 'badge-bull' : 'badge-bear'}`;
    } else {
      badge.textContent = 'Баланс';
      badge.className = 'badge badge-neu';
    }
  }

  const list = document.getElementById('book-anomaly-list');
  if (!list) return;

  if (book.anomalies && book.anomalies.length > 0) {
    list.innerHTML = book.anomalies.slice(0, 3).map(a => `
      <div class="book-anomaly-item">
        <span class="book-anomaly-side ${a.side}">${a.side.toUpperCase()}</span>
        <span class="book-anomaly-price">$${formatPrice(a.price)}</span>
        <span class="book-anomaly-vol">${a.volume.toFixed(1)} (${a.ratio}x)</span>
      </div>
    `).join('');
  } else {
    list.innerHTML = '<div class="book-no-anomalies">Нет аномалий</div>';
  }
}

// ── Elliott Wave ──────────────────────────────────────────
function renderWaves(waves, currentPrice) {
  const el = document.getElementById('wave-info');
  if (!el) return;

  if (!waves || !waves.primary) {
    el.innerHTML = '<div class="wave-empty">Wave: no count</div>';
    return;
  }

  const p = waves.primary;
  const dirEmoji = p.direction === 'impulse' ? '🟢' : '🔵';
  const confPct = Math.round(waves.confidence * 100);

  // Determine current wave label from points
  let currentLabel = '';
  if (currentPrice && p.points && p.points.length >= 2) {
    for (let i = 0; i < p.points.length - 1; i++) {
      const lo = Math.min(p.points[i].price, p.points[i + 1].price);
      const hi = Math.max(p.points[i].price, p.points[i + 1].price);
      if (currentPrice >= lo && currentPrice <= hi) {
        if (i === 0) currentLabel = p.points[i].label;
        else if (i === p.points.length - 2) currentLabel = p.points[i + 1].label;
        else currentLabel = `${p.points[i].label}-${p.points[i + 1].label}`;
        break;
      }
    }
    if (!currentLabel && p.points.length > 0) {
      currentLabel = p.points[p.points.length - 1].label;
    }
  }

  const curSet = new Set(currentLabel.split('-'));

  // Highlight points — mark current wave(s) with bold
  let pointsStr = p.points.map(pt => {
    if (curSet.has(pt.label)) return `<b>${pt.label}</b>`;
    return pt.label;
  }).join(' → ');

  // Also highlight label parentheses (e.g. "1-2-3-4-5")
  let highlightedLabel = p.label;
  if (p.label.includes('(')) {
    const labelParts = p.label.split('(');
    const wavesStr = labelParts[1].replace(')', '');
    const waves = wavesStr.split('-');
    const highlighted = waves.map(w => curSet.has(w) ? `<b>${w}</b>` : w).join('-');
    highlightedLabel = `${labelParts[0]}(${highlighted})`;
  }

  // Conflict details
  let conflictHtml = '';
  if (waves.conflict) {
    const details = waves.conflict_details || 'Разные варианты указывают разное направление';
    conflictHtml = `<div class="wave-conflict-block">⚠️ <span class="wave-conflict-title">Конфликт:</span> ${details}</div>`;
  }

  // Alternatives with direction info and target
  let altHtml = '';
  if (waves.alternatives.length > 0) {
    const altItems = waves.alternatives.map(a => {
      const aDirEmoji = a.direction === 'impulse' ? '🟢' : '🔵';
      const aConf = Math.round(a.confidence * 100);
      const aTarget = a.target ? formatPrice(a.target) : '—';
      return `${aDirEmoji} ${a.label} <span class="wave-alt-conf">(${aConf}%) → ${aTarget}</span>`;
    }).join('<br>');
    altHtml = `<div class="wave-alt-block"><span class="wave-alt-label">Альтернативы:</span><br>${altItems}</div>`;
  }

  el.innerHTML = `
    <div class="wave-header">${dirEmoji} ${highlightedLabel}</div>
    <div class="wave-detail">${pointsStr}</div>
    <div class="wave-confidence">Confidence: ${confPct}%</div>
    ${conflictHtml}
    ${altHtml}
  `;
}

// ── Utils для нового функционала ───────────────────
function formatLargeNumber(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return n.toFixed(0);
}

function formatPrice(p) {
  if (!p) return '0';
  if (p >= 1000) return Number(p).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
  if (p >= 1) return p.toFixed(4);
  return p.toFixed(6);
}

// ── Token picker ────────────────────────────────────
document.getElementById('tokenBtn')?.addEventListener('click', () => {
  const raw = document.getElementById('tokenInput')?.value.trim().toUpperCase();
  if (raw) subscribeToToken(raw);
});

document.querySelectorAll('.qtok').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.qtok').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    subscribeToToken(btn.dataset.symbol);
  });
});

function subscribeToToken(symbol) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'subscribe', symbol }));
    showLoader(`Загрузка ${symbol}...`);
    setTimeout(hideLoader, 2000);
  }
}

// ── Utils ───────────────────────────────────────────
function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? '—';
}

function clamp(v, min, max) {
  return Math.min(max, Math.max(min, v || 0));
}

function updateStatus(text) {
  const el = document.getElementById('statusText');
  if (el) el.textContent = text;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function showLoader(msg) {
  let overlay = document.getElementById('loadingOverlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'loadingOverlay';
    overlay.className = 'loading-overlay';
    overlay.innerHTML = `<div class="spinner"></div><span id="loaderMsg"></span>`;
    document.body.appendChild(overlay);
  }
  document.getElementById('loaderMsg').textContent = msg || 'Загрузка...';
  overlay.classList.add('visible');
}

function hideLoader() {
  document.getElementById('loadingOverlay')?.classList.remove('visible');
}

// ── Timeframe Picker ─────────────────────────────
function renderTimeframePicker(data) {
  const timeframes = data.timeframes || ['1h', '4h'];
  currentTimeframe = data.currentTimeframe || timeframes[0];
  const container = document.getElementById('tfList');
  if (!container) return;

  container.innerHTML = timeframes.map(tf => {
    const active = tf === currentTimeframe ? ' active' : '';
    return `<button class="tf-btn${active}" data-tf="${tf}">${tf.toUpperCase()}</button>`;
  }).join('');

  container.querySelectorAll('.tf-btn').forEach(btn => {
    btn.addEventListener('click', () => setTimeframe(btn.dataset.tf));
  });

  setText('chartTfLabel', currentTimeframe.toUpperCase());
}

function setTimeframe(tf) {
  if (tf === currentTimeframe) return;
  currentTimeframe = tf;

  document.querySelectorAll('.tf-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tf === tf);
  });
  setText('chartTfLabel', tf.toUpperCase());

  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'set_timeframe', timeframe: tf }));
  }
}

// ── Open Trades ──────────────────────────────────
function renderOpenTrades(trades) {
  const tbody = document.getElementById('tradesBody');
  const countEl = document.getElementById('tradesCount');
  if (!tbody) return;

  if (countEl) countEl.textContent = trades.length;

  if (!trades || trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="trades-empty">Нет открытых сделок</td></tr>';
    return;
  }

  tbody.innerHTML = trades.map((t, i) => {
    const signalCls = t.signal_type === 'BUY' ? 'trades-signal-buy' : 'trades-signal-sell';
    const sent = t.sent_at ? formatTradeTime(t.sent_at) : '—';
    return `<tr>
      <td>${i + 1}</td>
      <td class="${signalCls}">${t.signal_type}</td>
      <td class="trades-ticker">${escapeHtml(t.symbol)}</td>
      <td class="trades-tf">${escapeHtml(t.timeframe)}</td>
      <td class="trades-price">${formatPrice(t.entry)}</td>
      <td class="trades-price">${formatPrice(t.sl)}</td>
      <td class="trades-price">${formatPrice(t.tp)}</td>
      <td class="trades-sent">${sent}</td>
    </tr>`;
  }).join('');
}

function formatTradeTime(isoStr) {
  try {
    const d = new Date(isoStr);
    const day = d.getUTCDate().toString().padStart(2, '0');
    const month = (d.getUTCMonth() + 1).toString().padStart(2, '0');
    const hours = d.getUTCHours().toString().padStart(2, '0');
    const mins = d.getUTCMinutes().toString().padStart(2, '0');
    return `${day}.${month} ${hours}:${mins}`;
  } catch {
    return '—';
  }
}

async function fetchOpenTrades() {
  try {
    const res = await fetch('/api/open-trades');
    const data = await res.json();
    renderOpenTrades(data.trades || []);
  } catch (err) {
    console.error('Failed to load open trades:', err);
  }
}

// ── Tab switching ─────────────────────────────────
let currentTab = 'dashboard';
let footprintInited = false;
let sandboxInited = false;

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

function switchTab(tab) {
  if (tab === currentTab) return;
  currentTab = tab;

  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.getElementById('tab-dashboard')?.classList.toggle('hidden', tab !== 'dashboard');
  document.getElementById('tab-footprint')?.classList.toggle('hidden', tab !== 'footprint');
  document.getElementById('tab-sandbox')?.classList.toggle('hidden', tab !== 'sandbox');

  if (tab === 'footprint' && !footprintInited) {
    footprintInited = true;
    footprintChart.init();
  }
  if (tab === 'footprint') {
    footprintChart.draw();
  }
  if (tab === 'sandbox' && !sandboxInited) {
    sandboxInited = true;
    sandboxModule.init();
  }
}

// ── Footprint Chart ─────────────────────────────
const footprintChart = (() => {
  const COL_W = 92;
  const PAD_L = 64;
  const PAD_TOP = 14;
  const PAD_BOTTOM = 14;

  let canvas, ctx, chartWrap;
  let thresholdInput, minStackInput, thresholdValEl, minStackValEl;
  let bullCountEl, bearCountEl;
  let LEVEL_H = 20;
  let fpData = null;

  function computeImbalance(levels, thresholdPct) {
    for (let i = 0; i < levels.length; i++) {
      levels[i].buyImb = false;
      levels[i].sellImb = false;
    }
    for (let i = 1; i < levels.length; i++) {
      const ratioBuy = levels[i].ask / Math.max(0.0001, levels[i - 1].bid) * 100;
      if (ratioBuy >= thresholdPct) levels[i].buyImb = true;
    }
    for (let i = 0; i < levels.length - 1; i++) {
      const ratioSell = levels[i].bid / Math.max(0.0001, levels[i + 1].ask) * 100;
      if (ratioSell >= thresholdPct) levels[i].sellImb = true;
    }
  }

  function findStacks(levels, minStack) {
    const stacks = [];
    let i = 0;
    while (i < levels.length) {
      if (levels[i].buyImb) {
        let j = i; while (j < levels.length && levels[j].buyImb) j++;
        if (j - i >= minStack) stacks.push({ type: 'buy', from: i, to: j - 1 });
        i = j;
      } else if (levels[i].sellImb) {
        let j = i; while (j < levels.length && levels[j].sellImb) j++;
        if (j - i >= minStack) stacks.push({ type: 'sell', from: i, to: j - 1 });
        i = j;
      } else i++;
    }
    return stacks;
  }

  function layout(levels) {
    const thresholdPct = +thresholdInput.value;
    const minStack = +minStackInput.value;

    computeImbalance(levels, thresholdPct);
    const stacks = findStacks(levels, minStack);

    if (levels.length === 0) return { totalTicks: 0, width: 0, height: 0, stacks };

    const minP = levels[0].price;
    const maxP = levels[levels.length - 1].price;
    const tickSize = fpData?.tickSize || 0.01;
    const totalTicks = Math.round((maxP - minP) / tickSize) + 1;
    const availH = chartWrap.clientHeight - PAD_TOP - PAD_BOTTOM || 420;
    LEVEL_H = Math.max(14, Math.min(22, Math.floor(availH / Math.max(totalTicks, 8))));
    const width = PAD_L + COL_W + 20;
    const height = PAD_TOP + totalTicks * LEVEL_H + PAD_BOTTOM;
    canvas.width = width * devicePixelRatio;
    canvas.height = height * devicePixelRatio;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    return { minP, totalTicks, width, height, stacks, tickSize };
  }

  function draw() {
    if (!canvas || !fpData || !fpData.levels || fpData.levels.length === 0) return;

    const levels = fpData.levels;
    const { minP, totalTicks, width, height, stacks, tickSize } = layout(levels);
    if (totalTicks === 0) return;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#111';
    ctx.fillRect(0, 0, width, height);

    function yFor(price) {
      const ticksFromBottom = Math.round((price - minP) / tickSize);
      const rowFromTop = totalTicks - 1 - ticksFromBottom;
      return PAD_TOP + rowFromTop * LEVEL_H;
    }

    // grid + price axis
    ctx.strokeStyle = '#1a1a1a';
    ctx.lineWidth = 1;
    ctx.font = '10px ui-monospace, SFMono-Regular, Menlo, monospace';
    ctx.fillStyle = '#555';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    const step = LEVEL_H < 16 ? 8 : 4;
    for (let t = 0; t < totalTicks; t += step) {
      const price = minP + t * tickSize;
      const y = yFor(price) + LEVEL_H / 2;
      ctx.beginPath();
      ctx.moveTo(PAD_L - 6, y);
      ctx.lineTo(width, y);
      ctx.stroke();
      ctx.fillText(price.toFixed(2), PAD_L - 10, y);
    }

    // single bar
    const x = PAD_L;
    const barLevels = new Map();
    levels.forEach(lv => barLevels.set(lv.price, lv));

    levels.forEach(lv => {
      const y = yFor(lv.price);
      ctx.fillStyle = lv.ask >= lv.bid ? 'rgba(163,230,53,0.08)' : 'rgba(248,113,113,0.08)';
      ctx.fillRect(x + 2, y + 1, COL_W - 4, LEVEL_H - 2);

      ctx.strokeStyle = '#1e1e1e';
      ctx.beginPath();
      ctx.moveTo(x + COL_W / 2, y + 1);
      ctx.lineTo(x + COL_W / 2, y + LEVEL_H - 1);
      ctx.stroke();

      ctx.font = (LEVEL_H < 16 ? '9px' : '10.5px') + ' ui-monospace, SFMono-Regular, Menlo, monospace';
      ctx.textBaseline = 'middle';

      ctx.fillStyle = lv.sellImb ? '#f87171' : '#888';
      ctx.textAlign = 'right';
      ctx.fillText(formatVol(lv.bid), x + COL_W / 2 - 6, y + LEVEL_H / 2);

      ctx.fillStyle = lv.buyImb ? '#a3e635' : '#888';
      ctx.textAlign = 'left';
      ctx.fillText(formatVol(lv.ask), x + COL_W / 2 + 6, y + LEVEL_H / 2);
    });

    // stack frames
    stacks.forEach(s => {
      const top = levels[s.to];
      const bottom = levels[s.from];
      const yTop = yFor(top.price);
      const yBottom = yFor(bottom.price) + LEVEL_H;
      ctx.fillStyle = s.type === 'buy' ? 'rgba(163,230,53,0.08)' : 'rgba(248,113,113,0.08)';
      ctx.strokeStyle = '#facc15';
      ctx.lineWidth = 1.5;
      ctx.fillRect(x + 1, yTop, COL_W - 2, yBottom - yTop);
      ctx.strokeRect(x + 1, yTop, COL_W - 2, yBottom - yTop);
    });

    // counters
    let bull = 0, bear = 0;
    stacks.forEach(s => s.type === 'buy' ? bull++ : bear++);
    bullCountEl.textContent = bull;
    bearCountEl.textContent = bear;
  }

  function formatVol(v) {
    if (v >= 1000) return (v / 1000).toFixed(1) + 'K';
    if (v >= 1) return v.toFixed(1);
    return v.toFixed(4);
  }

  function updateFromData(data) {
    fpData = data;
    draw();
  }

  function init() {
    canvas = document.getElementById('fpChart');
    if (!canvas) return;
    ctx = canvas.getContext('2d');
    chartWrap = document.getElementById('fpChartWrap');
    thresholdInput = document.getElementById('fpThreshold');
    minStackInput = document.getElementById('fpMinStack');
    thresholdValEl = document.getElementById('fpThresholdVal');
    minStackValEl = document.getElementById('fpMinStackVal');
    bullCountEl = document.getElementById('fpBullCount');
    bearCountEl = document.getElementById('fpBearCount');

    thresholdInput.addEventListener('input', () => {
      thresholdValEl.textContent = thresholdInput.value + '%';
      draw();
    });
    minStackInput.addEventListener('input', () => {
      minStackValEl.textContent = minStackInput.value + ' уровня';
      draw();
    });

    window.addEventListener('resize', () => { if (currentTab === 'footprint') draw(); });
  }

  return { init, draw, updateFromData };
})();

// ── Sandbox: Signal Logic Visualization ────────────
const sandboxModule = (() => {
  let chart = null;
  let candleSeries = null;
  let overlayContainer = null;
  let zoneDivs = [];
  let currentTrace = null;

  function init() {
    document.getElementById('sandboxLoadBtn')?.addEventListener('click', loadSignals);
    document.getElementById('sandboxSymbol')?.addEventListener('change', loadSignals);
    document.getElementById('sandboxTf')?.addEventListener('change', loadSignals);

    loadSymbols();

    document.getElementById('zoneOpacity')?.addEventListener('input', (e) => {
      document.getElementById('zoneOpacityVal').textContent = e.target.value + '%';
      if (currentTrace) renderVisual(currentTrace);
    });

    ['showSweep','showMss','showBos','showOb','showFvg','showEntry'].forEach(id => {
      document.getElementById(id)?.addEventListener('change', () => {
        if (currentTrace) renderVisual(currentTrace);
      });
    });

    window.addEventListener('resize', () => {
      if (currentTab === 'sandbox' && chart) {
        const wrap = document.getElementById('sandboxChartWrap');
        if (wrap) chart.applyOptions({ width: wrap.clientWidth, height: wrap.clientHeight });
      }
    });
  }

  async function loadSymbols() {
    const select = document.getElementById('sandboxSymbol');
    if (!select) return;
    try {
      const res = await fetch('/api/sandbox/symbols');
      const data = await res.json();
      if (data.symbols && data.symbols.length > 0) {
        select.innerHTML = data.symbols.map(s => `<option value="${s}">${s}</option>`).join('');
        loadSignals();
      } else {
        select.innerHTML = '<option value="">Нет принятых сигналов</option>';
      }
    } catch (e) {
      select.innerHTML = '<option value="">Ошибка загрузки</option>';
    }
  }

  async function loadSignals() {
    const symbol = document.getElementById('sandboxSymbol')?.value;
    const tf = document.getElementById('sandboxTf')?.value || '';
    const list = document.getElementById('sandboxSignalList');
    if (!list) return;
    if (!symbol) {
      list.innerHTML = '<div class="sandbox-empty">Нет принятых сигналов</div>';
      return;
    }
    list.innerHTML = '<div class="sandbox-empty">Loading...</div>';

    try {
      let url = `/api/sandbox/signals?symbol=${encodeURIComponent(symbol)}&limit=20`;
      if (tf) url += `&timeframe=${encodeURIComponent(tf)}`;
      const res = await fetch(url);
      const data = await res.json();
      if (!data.signals || data.signals.length === 0) {
        list.innerHTML = '<div class="sandbox-empty">Нет сигналов</div>';
        return;
      }
      list.innerHTML = data.signals.map(s => {
        const cls = s.signal_type === 'BUY' ? 'sig-buy' : 'sig-sell';
        const time = s.created_at ? formatSandboxTime(s.created_at) : '—';
        return `<div class="sandbox-signal-row" data-id="${s.id}">
          <div class="sig-header"><span class="sig-dir ${cls}">${s.signal_type}</span><span class="sig-time">${time}</span></div>
          <div class="sig-prices">E: $${formatPrice(s.entry)} SL: $${formatPrice(s.sl)} TP: $${formatPrice(s.tp)}</div>
          <div class="sig-meta">TF: ${s.timeframe} | Score: ${s.score ?? '—'}</div>
        </div>`;
      }).join('');

      list.querySelectorAll('.sandbox-signal-row').forEach(row => {
        row.addEventListener('click', () => {
          list.querySelectorAll('.sandbox-signal-row').forEach(r => r.classList.remove('active'));
          row.classList.add('active');
          loadTrace(parseInt(row.dataset.id));
        });
      });
    } catch (e) {
      list.innerHTML = '<div class="sandbox-empty">Ошибка загрузки</div>';
      console.error('Sandbox load error:', e);
    }
  }

  async function loadTrace(signalId) {
    const title = document.getElementById('sandboxChartTitle');
    const info = document.getElementById('sandboxInfo');
    if (title) title.textContent = `Loading signal #${signalId}...`;

    try {
      const res = await fetch(`/api/sandbox/trace/${signalId}`);
      const trace = await res.json();
      if (trace.error) {
        if (title) title.textContent = trace.error;
        return;
      }
      currentTrace = trace;
      renderVisual(trace);

      const sig = trace.signal;
      if (title) title.textContent = `${sig.symbol} ${sig.direction} | ${sig.timeframe}`;
      if (info) {
        const outcome = sig.outcome ? ` | ${sig.outcome}` : '';
        info.innerHTML = `
          <div><b>Entry:</b> $${formatPrice(sig.entry)}</div>
          <div><b>SL:</b> $${formatPrice(sig.sl)}</div>
          <div><b>TP:</b> $${formatPrice(sig.tp)}</div>
          <div><b>Score:</b> ${sig.score ?? '—'}</div>
          <div><b>Confidence:</b> ${sig.confidence ? sig.confidence.toFixed(1) + '%' : '—'}</div>
          <div><b>Outcome:</b> ${sig.outcome || 'open'}${outcome}</div>
        `;
      }
    } catch (e) {
      if (title) title.textContent = 'Error loading trace';
      console.error('Trace load error:', e);
    }
  }

  function renderVisual(trace) {
    const wrap = document.getElementById('sandboxChartWrap');
    if (!wrap) return;

    // Clear previous
    if (chart) {
      chart.remove();
      chart = null;
    }
    zoneDivs.forEach(d => d.remove());
    zoneDivs = [];

    // Create overlay container
    overlayContainer = wrap;
    overlayContainer.style.position = 'relative';

    // Create chart
    const chartEl = document.getElementById('sandboxChart');
    chart = LightweightCharts.createChart(chartEl, {
      width: wrap.clientWidth,
      height: wrap.clientHeight || 450,
      layout: { background: { color: '#111' }, textColor: '#888' },
      grid: { vertLines: { color: '#1a1a1a' }, horzLines: { color: '#1a1a1a' } },
      timeScale: { timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });

    candleSeries = chart.addCandlestickSeries({
      upColor: '#a3e635',
      downColor: '#f87171',
      borderUpColor: '#a3e635',
      borderDownColor: '#f87171',
      wickUpColor: '#a3e635',
      wickDownColor: '#f87171',
    });

    if (!trace.candles || trace.candles.length === 0) return;
    candleSeries.setData(trace.candles);
    chart.timeScale().fitContent();

    const visual = trace.visual || {};
    const sig = trace.signal || {};

    // ── Markers ──
    const markers = [];

    if (document.getElementById('showSweep')?.checked && visual.sweep) {
      markers.push({
        time: visual.sweep.time,
        position: sig.direction === 'buy' ? 'belowBar' : 'aboveBar',
        color: '#ff9800',
        shape: 'circle',
        text: 'SWEEP',
      });
    }

    if (document.getElementById('showMss')?.checked && visual.mss) {
      markers.push({
        time: visual.mss.time,
        position: sig.direction === 'buy' ? 'aboveBar' : 'belowBar',
        color: '#f44336',
        shape: 'arrowDown',
        text: 'MSS',
      });
      // MSS level line
      candleSeries.createPriceLine({
        price: visual.mss.level,
        color: '#f44336',
        lineStyle: LightweightCharts.LineStyle.Dashed,
        lineWidth: 1,
        title: `MSS ${visual.mss.level}`,
      });
    }

    if (document.getElementById('showBos')?.checked && visual.bos) {
      markers.push({
        time: visual.bos.time,
        position: sig.direction === 'buy' ? 'aboveBar' : 'belowBar',
        color: '#2196f3',
        shape: 'arrowDown',
        text: 'BOS',
      });
      candleSeries.createPriceLine({
        price: visual.bos.level,
        color: '#2196f3',
        lineStyle: LightweightCharts.LineStyle.Dashed,
        lineWidth: 1,
        title: `BOS ${visual.bos.level}`,
      });
    }

    if (markers.length > 0) {
      markers.sort((a, b) => a.time - b.time);
      candleSeries.setMarkers(markers);
    }

    // ── Zones (overlay-div) ──
    const opacity = (parseInt(document.getElementById('zoneOpacity')?.value || '15') / 100).toFixed(2);

    if (document.getElementById('showOb')?.checked && visual.ob) {
      const obColor = document.getElementById('colorOb')?.value || '#ffc107';
      drawZone(visual.ob.time, visual.ob.high, visual.ob.low, obColor, opacity, 'OB');
    }

    if (document.getElementById('showFvg')?.checked && visual.fvg) {
      const fvgColor = document.getElementById('colorFvg')?.value || '#9c27b0';
      drawZone(visual.fvg.time, visual.fvg.top, visual.fvg.bottom, fvgColor, opacity, 'FVG');
    }

    // ── Entry / SL / TP lines ──
    if (document.getElementById('showEntry')?.checked) {
      if (sig.entry) candleSeries.createPriceLine({ price: sig.entry, color: '#2196f3', lineWidth: 1, title: 'Entry' });
      if (sig.sl) candleSeries.createPriceLine({ price: sig.sl, color: '#ef5350', lineWidth: 1, title: 'SL' });
      if (sig.tp) candleSeries.createPriceLine({ price: sig.tp, color: '#26a69a', lineWidth: 1, title: 'TP' });
    }
  }

  function drawZone(time, priceHigh, priceLow, color, opacity, label) {
    if (!chart || !candleSeries || !time) return;

    const div = document.createElement('div');
    div.className = 'sandbox-zone';
    div.style.background = hexToRgba(color, opacity);
    div.style.borderLeft = `2px solid ${color}`;
    div.title = label;
    overlayContainer.appendChild(div);
    zoneDivs.push(div);

    function update() {
      if (!chart || !candleSeries) return;
      const x = chart.timeScale().timeToCoordinate(time);
      const y1 = candleSeries.priceToCoordinate(priceHigh);
      const y2 = candleSeries.priceToCoordinate(priceLow);
      if (x == null || y1 == null || y2 == null) {
        div.style.display = 'none';
        return;
      }
      div.style.display = 'block';
      div.style.left = x + 'px';
      div.style.top = Math.min(y1, y2) + 'px';
      div.style.width = '2px';
      div.style.height = Math.abs(y2 - y1) + 'px';
    }

    chart.timeScale().subscribeVisibleTimeRangeChange(update);
    chart.subscribeCrosshairMove(update);
    update();
  }

  function hexToRgba(hex, alpha) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  function formatSandboxTime(isoStr) {
    try {
      const d = new Date(isoStr);
      const day = d.getUTCDate().toString().padStart(2, '0');
      const month = (d.getUTCMonth() + 1).toString().padStart(2, '0');
      const hours = d.getUTCHours().toString().padStart(2, '0');
      const mins = d.getUTCMinutes().toString().padStart(2, '0');
      return `${day}.${month} ${hours}:${mins}`;
    } catch {
      return '—';
    }
  }

  return { init };
})();

// ── Start ──────────────────────────────────────────
connect();
fetchOpenTrades();
