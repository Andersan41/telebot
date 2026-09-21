// =====================================================
// Trading Signal Bot — Dashboard Frontend
// =====================================================

const WS_URL = `ws://${location.host}/ws`;
let socket = null;
let priceChart = null;
let reconnectTimer = null;
let currentTimeframe = null;

// CVD chart (Lightweight Charts)
let cvdChart = null;
let cvdSeries = null;

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
  const { indicators, structure, liquidity, levels, signal, priceHistory, price, symbol, error, openInterest, volumeProfile, bookAnomalies, cvd, fundingRate, candleHistory, waveOverlay, breakoutQuality } = data;

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
  if (priceHistory || candleHistory) updatePriceChart(priceHistory, candleHistory);
  if (openInterest) renderOpenInterest(openInterest);
  if (fundingRate != null) renderFundingRate(fundingRate);
  if (volumeProfile) renderVolumeProfile(volumeProfile, price);
  if (bookAnomalies) renderBookAnomalies(bookAnomalies);
  if (cvd) renderCVD(cvd);
  if (breakoutQuality) renderBreakoutQuality(breakoutQuality);

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
  const adxLabel = ind.trend_is_strong ? `Тренд (${ind.dmi_plus?.toFixed(1)} / ${ind.dmi_minus?.toFixed(1)})` : `Боковой (${ind.adx?.toFixed(1)})`;
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
  verdictConf.textContent = `Уверенность: ${conf.toFixed(1)}%`;
  confBar.style.width = clamp(conf, 0, 100) + '%';

  const regimeLabels = { trending: 'Трендовый', ranging: 'Боковой', volatile: 'Волатильный' };
  setText('verdict-regime', regimeLabels[signal.regime] || signal.regime || '—');
  setText('verdict-trend', indicators?.trend_is_strong ? 'Сильный' : 'Слабый');
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
      name: 'Break of Structure (смена структуры)',
      desc: `${structure.bos.type === 'bullish' ? 'Бычий' : 'Медвежий'} @ $${(structure.bos.level || 0).toLocaleString()}`,
      badgeCls: structure.bos.type === 'bullish' ? 'smc-bull' : 'smc-target',
      badge: structure.bos.type === 'bullish' ? '+Bull' : '-Bear'
    });
  }

  // Order Blocks
  if (liquidity?.order_blocks) {
    liquidity.order_blocks.slice(0, 2).forEach(ob => {
      items.push({
        iconCls: 'smc-icon-blue', icon: '▣',
        name: 'Order Block (ордер блок)',
        desc: `${ob.type === 'bullish' ? 'Бычий' : 'Медвежий'} @ $${(ob.price || 0).toLocaleString()}`,
        badgeCls: 'smc-support', badge: 'Поддержка'
      });
    });
  }

  // FVG
  if (liquidity?.fvg) {
    liquidity.fvg.slice(0, 1).forEach(f => {
      items.push({
        iconCls: 'smc-icon-yellow', icon: '═',
        name: 'Fair Value Gap (честный разрыв)',
        desc: `$${(f.bottom || 0).toLocaleString()} — $${(f.top || 0).toLocaleString()}`,
        badgeCls: 'smc-magnet', badge: 'Магнит'
      });
    });
  }

  // Sweep
  if (liquidity?.sweep?.detected) {
    items.push({
      iconCls: 'smc-icon-red', icon: '⚠',
      name: 'Liquidity Sweep (смыв ликвидности)',
      desc: `${liquidity.sweep.type === 'bullish' ? 'Бычий' : 'Медвежий'} sweep detected`,
      badgeCls: 'smc-target', badge: 'Цель'
    });
  }

  // Trend
  if (structure?.trend) {
    items.push({
      iconCls: structure.trend === 'bullish' ? 'smc-icon-green' : structure.trend === 'bearish' ? 'smc-icon-red' : 'smc-icon-yellow',
      icon: '◈',
      name: 'Market Trend (тренд рынка)',
      desc: structure.trend === 'bullish' ? 'Бычий' : structure.trend === 'bearish' ? 'Медвежий' : 'Боковой',
      badgeCls: structure.trend === 'bullish' ? 'smc-bull' : structure.trend === 'bearish' ? 'smc-target' : 'smc-magnet',
      badge: structure.trend === 'bullish' ? 'Бычий' : structure.trend === 'bearish' ? 'Медвежий' : 'Боковой'
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
let mainCandleSeries = null;
let currentPriceLine = null;

function updatePriceChart(history, candleHistory) {
  const el = document.getElementById('priceChart');
  if (!el) return;
  const wrap = el.parentElement;
  if (!wrap) return;

  const candles = candleHistory && candleHistory.length > 0 ? candleHistory : null;
  if (!candles) return;

  if (!priceChart) {
    priceChart = LightweightCharts.createChart(el, {
      width: wrap.clientWidth,
      height: 160,
      layout: { background: { color: '#111' }, textColor: '#555' },
      grid: { vertLines: { color: '#1a1a1a' }, horzLines: { color: '#1a1a1a' } },
      rightPriceScale: { borderColor: '#222', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { timeVisible: false, borderColor: '#222' },
      crosshair: { mode: 0 },
    });
    mainCandleSeries = priceChart.addCandlestickSeries({
      upColor: '#a3e635',
      downColor: '#f87171',
      borderUpColor: '#a3e635',
      borderDownColor: '#f87171',
      wickUpColor: '#a3e635',
      wickDownColor: '#f87171',
    });
    new ResizeObserver(() => {
      if (priceChart) priceChart.applyOptions({ width: wrap.clientWidth });
    }).observe(wrap);
  }

  mainCandleSeries.setData(candles);

  // Update current price line (remove old one first)
  const lastCandle = candles[candles.length - 1];
  if (lastCandle) {
    if (currentPriceLine) {
      try { mainCandleSeries.removePriceLine(currentPriceLine); } catch {}
    }
    currentPriceLine = mainCandleSeries.createPriceLine({
      price: lastCandle.close,
      color: '#60a5fa',
      lineWidth: 1,
      lineStyle: 0,
      axisLabelVisible: true,
      title: '',
    });
  }

  priceChart.timeScale().fitContent();
}

// ── Open Interest (compact) ────────────────────────
function renderOpenInterest(oi) {
  const val = oi.value || oi.current || 0;
  const delta = oi.delta_pct || oi.change_pct || 0;
  const el = document.getElementById('oiValue');
  if (el) {
    const formatted = val > 1e6 ? (val / 1e6).toFixed(2) + 'M' : val > 1e3 ? (val / 1e3).toFixed(1) + 'K' : val.toFixed(2);
    el.textContent = formatted;
  }
  const deltaEl = document.getElementById('oiDelta');
  if (deltaEl && delta !== 0) {
    const sign = delta > 0 ? '+' : '';
    deltaEl.textContent = `${sign}${delta.toFixed(1)}%`;
    deltaEl.className = `deriv-delta ${delta > 0 ? 'bull' : 'bear'}`;
  }
}

// ── Funding Rate (compact) ────────────────────────
function renderFundingRate(rate) {
  const el = document.getElementById('frValue');
  if (el) {
    const pct = typeof rate === 'number' ? rate : parseFloat(rate);
    el.textContent = isNaN(pct) ? '—' : pct.toFixed(4) + '%';
    el.className = 'deriv-value ' + (pct > 0.01 ? 'bear' : pct < -0.01 ? 'bull' : '');
  }
}

// ── Volume Profile ─────────────────────────────────
function renderVolumeProfile(vp, currentPrice) {
  setText('vp-poc', vp.poc ? '$' + formatPrice(vp.poc) : '—');
  setText('vp-vah', vp.vah ? '$' + formatPrice(vp.vah) : '—');
  setText('vp-val', vp.val ? '$' + formatPrice(vp.val) : '—');
  setText('vp-in-va', vp.price_in_va ? 'Да' : 'Нет');

  const container = document.getElementById('vp-histogram');
  if (!container || !vp.profile || vp.profile.length === 0) return;

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

// ── Breakout Quality ───────────────────────────────
function renderBreakoutQuality(bq) {
  const verdictColors = { real: '#4caf50', fake: '#f44336', ambiguous: '#ff9800' };
  const verdictLabels = { real: 'Реальный', fake: 'Ложный', ambiguous: 'Неопределённый' };
  setText('bq-verdict', verdictLabels[bq.verdict] || '—');
  const verdictEl = document.getElementById('bq-verdict');
  if (verdictEl && bq.verdict) {
    verdictEl.style.color = verdictColors[bq.verdict] || '#fff';
  }
  setText('bq-direction', bq.direction === 'buy' ? 'Покупка' : bq.direction === 'sell' ? 'Продажа' : '—');
  setText('bq-score', bq.score != null ? bq.score.toFixed(1) : '—');
  setText('bq-body', bq.body_pct != null ? bq.body_pct.toFixed(1) + '%' : '—');
  setText('bq-retention', bq.retention != null ? bq.retention + ' баров' : '—');
  setText('bq-volume', bq.volume_ratio != null ? bq.volume_ratio.toFixed(1) + 'x' : '—');
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

// ── CVD (Cumulative Volume Delta) ──────────────────
function renderCVD(cvd) {
  if (!cvd) return;
  const trendColors = { bullish: '#4caf50', bearish: '#f44336', neutral: '#888' };
  const trendLabels = { bullish: 'Bullish', bearish: 'Bearish', neutral: 'Neutral' };
  setText('cvd-current', cvd.current != null ? formatLargeNumber(cvd.current) : '—');
  setText('cvd-trend-text', trendLabels[cvd.trend] || '—');
  setText('cvd-trend', trendLabels[cvd.trend] || '—');
  const trendEl = document.getElementById('cvd-trend');
  if (trendEl && cvd.trend) trendEl.style.color = trendColors[cvd.trend] || '#fff';
  const cvdCurrentEl = document.getElementById('cvd-current');
  if (cvdCurrentEl && cvd.current != null) cvdCurrentEl.style.color = cvd.current >= 0 ? '#4caf50' : '#f44336';

  const el = document.getElementById('cvdChart');
  const wrap = el && el.parentElement;
  if (!el || !wrap) return;
  if (!cvdChart) {
    cvdChart = LightweightCharts.createChart(el, {
      width: wrap.clientWidth, height: 120,
      layout: { background: { color: '#1a1a2e' }, textColor: '#888' },
      grid: { vertLines: { color: '#2a2a3e' }, horzLines: { color: '#2a2a3e' } },
      rightPriceScale: { borderColor: '#333' },
      timeScale: { timeVisible: false, borderColor: '#333' },
      crosshair: { mode: 0 },
    });
    cvdSeries = cvdChart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'right' });
    new ResizeObserver(() => { if (cvdChart) cvdChart.applyOptions({ width: wrap.clientWidth }); }).observe(wrap);
  }
  if (cvd.timestamps && cvd.deltas) {
    const data = cvd.timestamps.map((ts, i) => ({
      time: Math.floor(ts / 1000),
      value: cvd.deltas[i],
      color: cvd.deltas[i] >= 0 ? 'rgba(76,175,80,0.7)' : 'rgba(244,67,54,0.7)',
    }));
    cvdSeries.setData(data);
    cvdChart.timeScale().fitContent();
  }
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
let sandboxInited = false;

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

function switchTab(tab) {
  if (tab === currentTab) return;
  currentTab = tab;

  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.getElementById('tab-dashboard')?.classList.toggle('hidden', tab !== 'dashboard');
  document.getElementById('tab-scan')?.classList.toggle('hidden', tab !== 'scan');
  document.getElementById('tab-sandbox')?.classList.toggle('hidden', tab !== 'sandbox');

  if (tab === 'scan') {
    loadScanStats();
  }
  if (tab === 'sandbox' && !sandboxInited) {
    sandboxInited = true;
    sandboxModule.init();
  }
}

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

  // ── Scan Engine ─────────────────────────────────────────────
  async function loadScanStats() {
    const hours = document.getElementById('scanHours')?.value || 24;
    try {
      const resp = await fetch(`/api/scan-stats?hours=${hours}`);
      const data = await resp.json();
      renderScanStats(data);
    } catch (e) {
      console.error('Scan stats error:', e);
    }
  }

  function renderScanStats(data) {
    const totalEl = document.getElementById('scanTotal');
    const sentEl = document.getElementById('scanSent');
    const lastEl = document.getElementById('scanLastTs');
    const verEl = document.getElementById('scanConfigVer');
    const funnelEl = document.getElementById('scanFunnel');
    const reasonsEl = document.getElementById('scanReasons');

    if (totalEl) totalEl.textContent = data.total_entries ?? '—';
    if (verEl) verEl.textContent = data.config_version ?? '—';

    // Find "sent" from stage data (passed=TRUE at final stage)
    const stages = data.stages || {};
    let sentCount = 0;
    if (stages['pipeline']) sentCount = stages['pipeline'].passed || 0;
    else if (stages['risk_engine']) sentCount = stages['risk_engine'].passed || 0;
    if (sentEl) sentEl.textContent = sentCount;

    // Last scan
    if (lastEl) {
      if (data.last_scan_ts) {
        const d = new Date(data.last_scan_ts);
        const now = new Date();
        const diffMin = Math.round((now - d) / 60000);
        lastEl.textContent = diffMin < 1 ? 'just now' : diffMin < 60 ? `${diffMin}m ago` : `${Math.round(diffMin/60)}h ago`;
      } else {
        lastEl.textContent = 'no scans';
      }
    }

    // Funnel
    if (funnelEl) {
      const stageOrder = [
        'cooldown', 'portfolio_risk', 'daily_limits', 'position_limits',
        'indicators', 'volatility_filter', 'pattern_engine', 'score_gate',
        'displacement_gate', 'mss_gate', 'bos_gate', 'confirmation_score',
        'htf_bias', 'trade_plan', 'entry_trigger', 'probability_engine',
        'risk_engine', 'dedup', 'spread', 'depth', 'correlated_entry',
      ];
      const stageLabels = {
        cooldown: 'Кулдаун', portfolio_risk: 'Риск портфеля', daily_limits: 'Дневные лимиты',
        position_limits: 'Лимиты позиций', indicators: 'Индикаторы', volatility_filter: 'Волатильность',
        pattern_engine: 'Движок паттернов', score_gate: 'Порог оценки',
        displacement_gate: 'Дисплейсмент', mss_gate: 'MSS', bos_gate: 'BOS',
        confirmation_score: 'Подтверждение', htf_bias: 'HTF Bias', trade_plan: 'Торговый план',
        entry_trigger: 'Триггер входа', probability_engine: 'Вероятностный движок',
        risk_engine: 'Движок риска', dedup: 'Дедупликация', spread: 'Спред',
        depth: 'Глубина', correlated_entry: 'Корреляция',
      };

      // Only show stages that have data
      const activeStages = stageOrder.filter(s => stages[s]);
      if (activeStages.length === 0) {
        funnelEl.innerHTML = '<div class="scan-funnel-empty">Нет данных аудита за этот период</div>';
      } else {
        const maxTotal = Math.max(...activeStages.map(s => {
          const st = stages[s];
          return (st.passed || 0) + (st.blocked || 0);
        }), 1);

        funnelEl.innerHTML = activeStages.map(stage => {
          const st = stages[stage];
          const pass = st.passed || 0;
          const block = st.blocked || 0;
          const total = pass + block;
          const passPct = (pass / maxTotal * 100).toFixed(1);
          const blockPct = (block / maxTotal * 100).toFixed(1);
          const label = stageLabels[stage] || stage;
          return `<div class="scan-funnel-row">
            <div class="scan-funnel-label">${label}</div>
            <div class="scan-funnel-bar-wrap">
              <div class="scan-funnel-bar-pass" style="width:${passPct}%"></div>
              <div class="scan-funnel-bar-block" style="width:${blockPct}%"></div>
            </div>
            <div class="scan-funnel-count"><span class="pass">${pass}</span> / <span class="block">${block}</span></div>
          </div>`;
        }).join('');
      }
    }

    // Top rejection reasons
    if (reasonsEl) {
      const reasons = data.top_rejection_reasons || [];
      if (reasons.length === 0) {
        reasonsEl.innerHTML = '<div class="scan-funnel-empty">Нет отказов</div>';
      } else {
        const maxCount = Math.max(...reasons.map(r => r.count), 1);
        reasonsEl.innerHTML = `<div class="scan-reasons-list">${reasons.map(r => {
          const pct = (r.count / maxCount * 100).toFixed(0);
          return `<div class="scan-reason-row">
            <div class="scan-reason-code" title="${r.reason}">${r.reason}</div>
            <div class="scan-reason-bar"><div class="scan-reason-bar-fill" style="width:${pct}%"></div></div>
            <div class="scan-reason-count">${r.count}</div>
          </div>`;
        }).join('')}</div>`;
      }
    }
  }

  // Bind refresh button
  document.getElementById('scanRefreshBtn')?.addEventListener('click', loadScanStats);
  document.getElementById('scanHours')?.addEventListener('change', loadScanStats);

  return { init };
})();

// ── Start ──────────────────────────────────────────
connect();
fetchOpenTrades();
