/**
 * common.js — shared helpers + cross-tab symbol state.
 * Must be loaded BEFORE app.js and token-analysis.js.
 *
 * AppState is the single source of truth for the selected symbol,
 * shared by the Dashboard (WS, live) and Token Analysis (report) tabs.
 * Picking a token on either side keeps both in sync via the
 * 'app:symbol-change' event; tabs are notified of their activation
 * via 'app:tab-shown' (used for lazy auto-load of the report).
 */
window.Common = (function () {
  'use strict';

  const SYMBOL_EVENT = 'app:symbol-change';
  const TAB_EVENT = 'app:tab-shown';

  function normSymbol(s) {
    return String(s || '').toUpperCase().replace(/\/USDT$/, '');
  }

  const AppState = {
    symbol: null,
    source: null,

    /** silent=true — update state only, without notifying other tabs */
    set(symbol, source, silent) {
      if (!symbol) return;
      this.symbol = symbol;
      this.source = source;
      if (!silent) {
        document.dispatchEvent(new CustomEvent(SYMBOL_EVENT, { detail: { symbol, source } }));
      }
    },

    onSymbolChange(cb) {
      document.addEventListener(SYMBOL_EVENT, (e) => cb(e.detail));
    },

    onTabShown(cb) {
      document.addEventListener(TAB_EVENT, (e) => cb(e.detail));
    },

    emitTab(tab) {
      document.dispatchEvent(new CustomEvent(TAB_EVENT, { detail: { tab } }));
    },
  };

  /**
   * Symbol-appropriate numeric precision without a currency sign.
   * Unified replacement for the 3 previous price formatters
   * (app.js formatPrice, alertsModule.fmtPrice, token-analysis fmtPrice).
   */
  function priceNumber(p) {
    if (!p && p !== 0) return '0';
    if (p === 0) return '0';
    if (p < 0.001) return p.toFixed(8);
    if (p < 0.1) return p.toFixed(6);
    if (p < 1) return p.toFixed(4);
    if (p < 100) return p.toFixed(2);
    // en-US explicitly — locale-independent output ('65,000', not '65 000')
    return Number(p).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function fmtPrice(p) {
    if (p === null || p === undefined || Number.isNaN(p)) return '—';
    return '$' + priceNumber(p);
  }

  function fmtVol(v) {
    if (v === null || v === undefined || v <= 0) return null;
    if (v >= 1e9) return '$' + (v / 1e9).toFixed(1) + 'B';
    if (v >= 1e6) return '$' + (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return '$' + (v / 1e3).toFixed(1) + 'K';
    return '$' + v.toFixed(0);
  }

  function escapeHtml(str) {
    return String(str ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  return { AppState, normSymbol, priceNumber, fmtPrice, fmtVol, escapeHtml };
})();
