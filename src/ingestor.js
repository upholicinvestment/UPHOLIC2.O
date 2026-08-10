import fs from 'fs/promises';
import axios from 'axios';
import config from './config.js';
import { TokenRateLimiter } from './limiter.js';
import { writeSnapshot, getPreviousSnapshot, insertAlert } from './db.js';

// In-memory cache for contract expiry dates to optimize throughput
// Key: symbol, Value: { date: 'YYYY-MM-DD', fetchedAt: timestamp }
const expiryCache = {};

export function checkMarketOpen() {
  const now = new Date();
  
  // Format details in Asia/Kolkata
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone: config.marketTimezone,
    hour12: false,
    weekday: 'short', // Mon, Tue, etc.
    hour: '2-digit',
    minute: '2-digit',
  });
  
  const parts = formatter.formatToParts(now);
  const partsMap = Object.fromEntries(parts.map(p => [p.type, p.value]));
  
  const weekday = partsMap.weekday; // "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"
  const hour = parseInt(partsMap.hour, 10);
  const minute = parseInt(partsMap.minute, 10);
  
  // Gating on weekdays (Monday to Friday)
  const isWeekend = weekday === 'Sat' || weekday === 'Sun';
  if (isWeekend) {
    return { isOpen: false, reason: `Weekend (${weekday})`, time: `${partsMap.hour}:${partsMap.minute}`, weekday };
  }
  
  // Convert times to minutes from midnight for simple numeric comparison
  const currentMin = hour * 60 + minute;
  
  const [openHour, openMin] = config.marketOpenTime.split(':').map(Number);
  const [closeHour, closeMin] = config.marketCloseTime.split(':').map(Number);
  
  const openTimeMin = openHour * 60 + openMin;
  const closeTimeMin = closeHour * 60 + closeMin;
  
  const isOpen = currentMin >= openTimeMin && currentMin <= closeTimeMin;
  const reason = isOpen ? 'Inside market hours' : `Outside market hours (${partsMap.hour}:${partsMap.minute} IST)`;
  
  return { isOpen, reason, time: `${partsMap.hour}:${partsMap.minute}`, weekday };
}

/* ==================== Math Helpers & Black-Scholes Solver ==================== */

function toNum(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function toInt(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.trunc(n) : fallback;
}

function getTsIstString(date = new Date()) {
  const formatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });

  const parts = formatter.formatToParts(date);
  const get = (type) => parts.find((p) => p.type === type)?.value || '';

  const yyyy = get('year');
  const mm = get('month');
  const dd = get('day');
  const hh = get('hour');
  const min = get('minute');
  const ss = get('second');
  const ms = String(date.getMilliseconds()).padStart(3, '0');

  return `${yyyy}-${mm}-${dd} ${hh}:${min}:${ss}.${ms} IST`;
}

function normalizeIvPercent(value) {
  const iv = Number(value);
  if (!Number.isFinite(iv) || iv <= 0) return 0;
  return iv > 1 ? iv : iv * 100;
}

function iv4NormalCdf(x) {
  const sign = x < 0 ? -1 : 1;
  const z = Math.abs(x) / Math.sqrt(2);
  const t = 1 / (1 + 0.3275911 * z);
  const erf =
    1 -
    (
      0.254829592 * t -
      0.284496736 * t ** 2 +
      1.421413741 * t ** 3 -
      1.453152027 * t ** 4 +
      1.061405429 * t ** 5
    ) * Math.exp(-(z ** 2));

  return 0.5 * (1 + sign * erf);
}

function iv4BlackScholesPrice(opts) {
  const { side, spot, strike, timeYears, rate, dividendYield, sigma } = opts;

  if (
    !Number.isFinite(spot) ||
    !Number.isFinite(strike) ||
    !Number.isFinite(timeYears) ||
    !Number.isFinite(sigma) ||
    spot <= 0 ||
    strike <= 0 ||
    timeYears <= 0 ||
    sigma <= 0
  ) return 0;

  const sqrtT = Math.sqrt(timeYears);
  const sigmaSqrtT = sigma * sqrtT;
  if (sigmaSqrtT <= 0) return 0;

  const d1 =
    (Math.log(spot / strike) +
      (rate - dividendYield + 0.5 * sigma * sigma) * timeYears) /
    sigmaSqrtT;
  const d2 = d1 - sigmaSqrtT;

  const discountedSpot = spot * Math.exp(-dividendYield * timeYears);
  const discountedStrike = strike * Math.exp(-rate * timeYears);

  if (side === 'ce') {
    return discountedSpot * iv4NormalCdf(d1) - discountedStrike * iv4NormalCdf(d2);
  }
  return discountedStrike * iv4NormalCdf(-d2) - discountedSpot * iv4NormalCdf(-d1);
}

function iv4TimeToExpiryYears(expiry, observationTime) {
  const expiryDate = String(expiry || '').slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(expiryDate)) return 0;

  // Stock options expire at 15:30 IST.
  const expiryMs = new Date(`${expiryDate}T15:30:00.000+05:30`).getTime();
  const observationMs = new Date(observationTime).getTime();

  if (
    !Number.isFinite(expiryMs) ||
    !Number.isFinite(observationMs) ||
    expiryMs <= observationMs
  ) return 0;

  return (expiryMs - observationMs) / (365 * 24 * 60 * 60 * 1000);
}

function iv4OptionPrice(leg) {
  const bid = Number(leg?.top_bid_price);
  const ask = Number(leg?.top_ask_price);
  const last = Number(leg?.last_price);

  if (Number.isFinite(bid) && Number.isFinite(ask) && bid > 0 && ask >= bid) {
    return (bid + ask) / 2;
  }
  if (Number.isFinite(last) && last > 0) return last;
  if (Number.isFinite(bid) && bid > 0) return bid;
  if (Number.isFinite(ask) && ask > 0) return ask;
  return 0;
}

function solveIv4(opts) {
  const { side, optionPrice, spot, strike, timeYears, rate, dividendYield } = opts;

  if (
    !Number.isFinite(optionPrice) ||
    !Number.isFinite(spot) ||
    !Number.isFinite(strike) ||
    !Number.isFinite(timeYears) ||
    optionPrice <= 0 || spot <= 0 || strike <= 0 || timeYears <= 0
  ) return 0;

  const discountedSpot = spot * Math.exp(-dividendYield * timeYears);
  const discountedStrike = strike * Math.exp(-rate * timeYears);
  const lowerBound = side === 'ce'
    ? Math.max(0, discountedSpot - discountedStrike)
    : Math.max(0, discountedStrike - discountedSpot);
  const upperBound = side === 'ce' ? discountedSpot : discountedStrike;
  const tolerance = 0.5;

  if (optionPrice < lowerBound - tolerance || optionPrice > upperBound + tolerance) return 0;

  let lowSigma = 0.0001;
  let highSigma = 5.0;

  const lowPrice = iv4BlackScholesPrice({
    side, spot, strike, timeYears, rate, dividendYield, sigma: lowSigma,
  });
  const highPrice = iv4BlackScholesPrice({
    side, spot, strike, timeYears, rate, dividendYield, sigma: highSigma,
  });
  if (optionPrice < lowPrice || optionPrice > highPrice) return 0;

  for (let i = 0; i < 80; i++) {
    const midSigma = (lowSigma + highSigma) / 2;
    const modelPrice = iv4BlackScholesPrice({
      side, spot, strike, timeYears, rate, dividendYield, sigma: midSigma,
    });
    if (Math.abs(modelPrice - optionPrice) < 0.0001) return midSigma;
    if (modelPrice > optionPrice) highSigma = midSigma;
    else lowSigma = midSigma;
  }
  return (lowSigma + highSigma) / 2;
}

function iv4LegPercent(opts) {
  const { leg, side, spot, strike, timeYears, rate, dividendYield } = opts;

  const vendorIv = normalizeIvPercent(
    leg?.greeks?.implied_volatility ??
    leg?.implied_volatility ??
    leg?.impliedVolatility ??
    leg?.iv
  );
  if (vendorIv > 0) return vendorIv;

  const optionPrice = iv4OptionPrice(leg);
  if (optionPrice <= 0) return 0;

  const solved = solveIv4({
    side, optionPrice, spot, strike, timeYears, rate, dividendYield,
  });
  return solved > 0 ? solved * 100 : 0;
}

function computeIv4FromStrikeChain(opts) {
  const { strikes, spot, expiry, observationTime } = opts;
  const emptyResult = {
    ce_iv_oi_weighted: 0,
    pe_iv_oi_weighted: 0,
    iv_skew: 0,
    iv_ratio: 0,
    iv4: 0,
  };

  if (!Array.isArray(strikes) || !strikes.length || !Number.isFinite(spot) || spot <= 0) {
    return emptyResult;
  }

  const timeYears = iv4TimeToExpiryYears(expiry, observationTime);
  if (timeYears <= 0) return emptyResult;

  const rate = config.riskFreeRate;
  const dividendYield = config.dividendYield;

  let ceIvOiValue = 0;
  let ceIvOiWeight = 0;
  let peIvOiValue = 0;
  let peIvOiWeight = 0;

  for (const sr of strikes) {
    const strike = Number(sr?.strike);
    if (!Number.isFinite(strike) || strike <= 0) continue;

    const ceOi = Number(sr?.ce?.oi ?? 0);
    const peOi = Number(sr?.pe?.oi ?? 0);
    const ceIv = iv4LegPercent({
      leg: sr?.ce, side: 'ce', spot, strike, timeYears, rate, dividendYield,
    });
    const peIv = iv4LegPercent({
      leg: sr?.pe, side: 'pe', spot, strike, timeYears, rate, dividendYield,
    });

    if (sr.ce) {
      sr.ce.greeks = sr.ce.greeks || {};
      sr.ce.greeks.implied_volatility = Number(ceIv.toFixed(4));
    }
    if (sr.pe) {
      sr.pe.greeks = sr.pe.greeks || {};
      sr.pe.greeks.implied_volatility = Number(peIv.toFixed(4));
    }

    if (Number.isFinite(ceOi) && ceOi > 0 && Number.isFinite(ceIv) && ceIv > 0) {
      ceIvOiValue += ceIv * ceOi;
      ceIvOiWeight += ceOi;
    }
    if (Number.isFinite(peOi) && peOi > 0 && Number.isFinite(peIv) && peIv > 0) {
      peIvOiValue += peIv * peOi;
      peIvOiWeight += peOi;
    }
  }

  const ce_iv_oi_weighted = ceIvOiWeight > 0
    ? Number((ceIvOiValue / ceIvOiWeight).toFixed(4)) : 0;
  const pe_iv_oi_weighted = peIvOiWeight > 0
    ? Number((peIvOiValue / peIvOiWeight).toFixed(4)) : 0;
  const iv_skew = ce_iv_oi_weighted > 0 && pe_iv_oi_weighted > 0
    ? Number((pe_iv_oi_weighted - ce_iv_oi_weighted).toFixed(4)) : 0;
  const iv_ratio = ce_iv_oi_weighted > 0 && pe_iv_oi_weighted > 0
    ? Number((pe_iv_oi_weighted / ce_iv_oi_weighted).toFixed(4)) : 0;

  const iv4 = (ceIvOiWeight + peIvOiWeight) > 0
    ? Number(((ceIvOiValue + peIvOiValue) / (ceIvOiWeight + peIvOiWeight)).toFixed(4))
    : 0;

  return { ce_iv_oi_weighted, pe_iv_oi_weighted, iv_skew, iv_ratio, iv4 };
}

/* ==================== Core Ingestion Helpers ==================== */

async function getExpiryDate(symbolObj, token) {
  if (config.marketExpiryDate) {
    return config.marketExpiryDate;
  }
  const symbol = symbolObj.symbol;
  const cacheEntry = expiryCache[symbol];
  
  // Cache expiry dates for 12 hours
  const cacheTTL = 12 * 60 * 60 * 1000; 
  if (cacheEntry && (Date.now() - cacheEntry.fetchedAt < cacheTTL)) {
    return cacheEntry.date;
  }
  
  // Cache miss or expired: fetch it
  const payload = {
    UnderlyingScrip: parseInt(symbolObj.security_id, 10),
    UnderlyingSeg: symbolObj.exchange_segment
  };
  
  const headers = {
    'access-token': token,
    'client-id': config.clientId,
    'Content-Type': 'application/json'
  };
  
  const response = await axios.post(config.expiryListUrl, payload, {
    headers,
    timeout: 10000
  });
  
  if (response.data && response.data.status === 'success' && Array.isArray(response.data.data) && response.data.data.length > 0) {
    const nearestExpiry = response.data.data[0];
    expiryCache[symbol] = {
      date: nearestExpiry,
      fetchedAt: Date.now()
    };
    return nearestExpiry;
  }
  
  throw new Error(`Failed to fetch expiry list: ${JSON.stringify(response.data)}`);
}

async function fetchOptionChain(symbolObj, expiryDate, token) {
  const payload = {
    UnderlyingScrip: parseInt(symbolObj.security_id, 10),
    UnderlyingSeg: symbolObj.exchange_segment,
    Expiry: expiryDate
  };
  
  const headers = {
    'access-token': token,
    'client-id': config.clientId,
    'Content-Type': 'application/json'
  };
  
  const response = await axios.post(config.optionChainUrl, payload, {
    headers,
    timeout: 10000
  });
  
  return response.data;
}

function parseLegData(strike, side, leg, prevIvMap) {
  if (!leg) return null;
  const g = leg.greeks || {};
  return {
    average_price: toNum(leg.average_price),
    greeks: {
      implied_volatility: leg.implied_volatility != null ? toNum(leg.implied_volatility) : null,
      gamma: toNum(g.gamma),
      delta: toNum(g.delta),
      theta: toNum(g.theta),
      vega: toNum(g.vega),
    },
    last_price: toNum(leg.last_price),
    oi: toNum(leg.oi),
    previous_close_price: toNum(prevIvMap[`${strike}_${side.toLowerCase()}_close`] || leg.previous_close_price),
    previous_oi: toNum(prevIvMap[`${strike}_${side.toLowerCase()}_oi`] || leg.previous_oi),
    previous_volume: toNum(prevIvMap[`${strike}_${side.toLowerCase()}_vol`] || leg.previous_volume),
    security_id: toNum(leg.security_id),
    top_ask_price: toNum(leg.top_ask_price),
    top_ask_quantity: toNum(leg.top_ask_quantity),
    top_bid_price: toNum(leg.top_bid_price),
    top_bid_quantity: toNum(leg.top_bid_quantity),
    volume: toNum(leg.volume),
  };
}

function mapResponseToDocument(symbolObj, data, previousSnapshot, expiryDate, now) {
  const spot_price = data.last_price || 0;
  const strikes = data.strikes || [];
  const options = [];

  const tsIst = getTsIstString(now);

  // Map previous options to a lookup map
  const prevIvMap = {};
  if (previousSnapshot && Array.isArray(previousSnapshot.options)) {
    for (const prevOpt of previousSnapshot.options) {
      const strike = prevOpt.strike;
      const type = prevOpt.type.toLowerCase();
      if (prevOpt.greeks?.implied_volatility) {
        prevIvMap[`${strike}_${type}_iv`] = prevOpt.greeks.implied_volatility;
      }
      if (prevOpt.oi) {
        prevIvMap[`${strike}_${type}_oi`] = prevOpt.oi;
      }
      if (prevOpt.ltp) {
        prevIvMap[`${strike}_${type}_close`] = prevOpt.ltp;
      }
      if (prevOpt.volume) {
        prevIvMap[`${strike}_${type}_vol`] = prevOpt.volume;
      }
    }
  }
  const oldIv4 = previousSnapshot ? Number(previousSnapshot.iv4 || 0) : 0;

  // Format flat list of options legs while computing previous variables
  for (const strikeData of strikes) {
    const strike = strikeData.strike;
    if (!strike) continue;

    if (strikeData.ce) {
      options.push({
        strike,
        type: 'CE',
        ltp: strikeData.ce.last_price || 0,
        oi: strikeData.ce.oi || 0,
        iv: strikeData.ce.greeks?.implied_volatility || 0,
        volume: strikeData.ce.volume || 0,
        greeks: {
          gamma: strikeData.ce.greeks?.gamma || 0,
          delta: strikeData.ce.greeks?.delta || 0,
          theta: strikeData.ce.greeks?.theta || 0,
          vega: strikeData.ce.greeks?.vega || 0
        },
        previous_close_price: toNum(prevIvMap[`${strike}_ce_close`] || strikeData.ce.previous_close_price),
        previous_oi: toNum(prevIvMap[`${strike}_ce_oi`] || strikeData.ce.previous_oi),
        previous_volume: toNum(prevIvMap[`${strike}_ce_vol`] || strikeData.ce.previous_volume),
      });
    }

    if (strikeData.pe) {
      options.push({
        strike,
        type: 'PE',
        ltp: strikeData.pe.last_price || 0,
        oi: strikeData.pe.oi || 0,
        iv: strikeData.pe.greeks?.implied_volatility || 0,
        volume: strikeData.pe.volume || 0,
        greeks: {
          gamma: strikeData.pe.greeks?.gamma || 0,
          delta: strikeData.pe.greeks?.delta || 0,
          theta: strikeData.pe.greeks?.theta || 0,
          vega: strikeData.pe.greeks?.vega || 0
        },
        previous_close_price: toNum(prevIvMap[`${strike}_pe_close`] || strikeData.pe.previous_close_price),
        previous_oi: toNum(prevIvMap[`${strike}_pe_oi`] || strikeData.pe.previous_oi),
        previous_volume: toNum(prevIvMap[`${strike}_pe_vol`] || strikeData.pe.previous_volume),
      });
    }
  }

  // Adapter for computeIv4FromStrikeChain: group options by strike
  const strikesMap = {};
  for (const opt of options) {
    if (!strikesMap[opt.strike]) {
      strikesMap[opt.strike] = { strike: opt.strike };
    }
    const legParsed = {
      implied_volatility: opt.iv,
      oi: opt.oi,
      volume: opt.volume,
      top_bid_price: opt.top_bid_price || 0,
      top_ask_price: opt.top_ask_price || 0,
      last_price: opt.ltp,
      greeks: opt.greeks
    };
    if (opt.type === 'CE') strikesMap[opt.strike].ce = legParsed;
    else strikesMap[opt.strike].pe = legParsed;
  }
  const strikesChain = Object.values(strikesMap).sort((a, b) => a.strike - b.strike);

  // Compute IV4 metrics
  const iv4Metrics = computeIv4FromStrikeChain({
    strikes: strikesChain,
    spot: spot_price,
    expiry: expiryDate,
    observationTime: now
  });

  let iv4Change5m = 0;
  if (oldIv4 > 0 && iv4Metrics.iv4 > 0) {
    iv4Change5m = Number((iv4Metrics.iv4 - oldIv4).toFixed(4));
  }

  // Filter to ATM ± 3 strikes (top 7 strikes sorted by distance to spot)
  const sortedByDistance = strikesChain.sort(
    (a, b) => Math.abs(a.strike - spot_price) - Math.abs(b.strike - spot_price)
  );
  const nearStrikes = sortedByDistance.slice(0, 7);
  const nearStrikesMap = new Set(nearStrikes.map((s) => s.strike));

  let topStrikeIvChange5m = null;
  let maxAbsChange = -1;

  let callNetFlow = 0;
  let putNetFlow = 0;

  for (const opt of options) {
    const strike = opt.strike;

    // OTM calls: strike >= spot * 1.015
    const isOtmCall = strike >= spot_price * 1.015;
    // OTM puts: strike <= spot * 0.985
    const isOtmPut = strike <= spot_price * 0.985;

    if (opt.type === 'CE' && isOtmCall) {
      const oiChange = (opt.oi || 0) - (opt.previous_oi || 0);
      const premiumChange = (opt.ltp || 0) - (opt.previous_close_price || 0);
      callNetFlow += oiChange * premiumChange;
    }
    if (opt.type === 'PE' && isOtmPut) {
      const oiChange = (opt.oi || 0) - (opt.previous_oi || 0);
      const premiumChange = (opt.ltp || 0) - (opt.previous_close_price || 0);
      putNetFlow += oiChange * premiumChange;
    }

    if (!nearStrikesMap.has(strike)) continue;

    const newIv = opt.iv;
    const oldIv = prevIvMap[`${strike}_${opt.type.toLowerCase()}_iv`];
    if (oldIv > 0) {
      const change = Number((newIv - oldIv).toFixed(4));
      const absChange = Math.abs(change);
      if (absChange > maxAbsChange) {
        maxAbsChange = absChange;
        topStrikeIvChange5m = {
          strike,
          side: opt.type,
          old_iv: oldIv,
          new_iv: newIv,
          change: change,
        };
      }
    }
  }

  const atmStrike = nearStrikes[0]?.strike || spot_price;

  return {
    symbol: symbolObj.symbol,
    security_id: symbolObj.security_id,
    spot_price,
    expiry: expiryDate,
    fetched_at: now,
    ts_ist: tsIst,
    options,
    // Calculations metrics
    iv4: iv4Metrics.iv4,
    iv4_change_5m: iv4Change5m,
    top_strike_iv_change_5m: topStrikeIvChange5m,
    ce_iv_oi_weighted: iv4Metrics.ce_iv_oi_weighted,
    pe_iv_oi_weighted: iv4Metrics.pe_iv_oi_weighted,
    iv_skew: iv4Metrics.iv_skew,
    iv_ratio: iv4Metrics.iv_ratio,
    call_net_flow: Number(callNetFlow.toFixed(4)),
    put_net_flow: Number(putNetFlow.toFixed(4)),
    Flip_strike: atmStrike,
  };
}

export async function startIngestionLoop() {
  const limiter = new TokenRateLimiter(config.tokens, config.rateLimitSeconds);
  
  // Load symbols from JSON file
  const symbolsPath = new URL('../symbols.json', import.meta.url);
  const symbols = JSON.parse(await fs.readFile(symbolsPath, 'utf-8'));
  
  console.log(`[Ingestor] Loaded ${symbols.length} symbols. Initializing ingestion daemon loop.`);
  
  let cycleCount = 0;
  
  // Expose global status object for Express health check
  global.ingestionStatus = {
    running: true,
    cycleCount: 0,
    marketOpen: false,
    lastCycleDuration: 0,
    lastCycleStats: { success: 0, fail: 0 },
    currentSymbol: null,
    lastActive: new Date().toISOString(),
    error: null
  };
  
  while (true) {
    try {
      const gate = checkMarketOpen();
      global.ingestionStatus.lastActive = new Date().toISOString();
      
      if (!gate.isOpen) {
        global.ingestionStatus.marketOpen = false;
        console.log(`[Ingestor] Market is closed. Reason: ${gate.reason}. Checking again in 60 seconds.`);
        await new Promise(resolve => setTimeout(resolve, 60000));
        continue;
      }
      
      global.ingestionStatus.marketOpen = true;
      cycleCount++;
      global.ingestionStatus.cycleCount = cycleCount;
      console.log(`[Ingestor] Starting ingestion cycle #${cycleCount} over ${symbols.length} symbols...`);
      
      const cycleStart = Date.now();
      let successCount = 0;
      let failCount = 0;
      
      for (const symbolObj of symbols) {
        global.ingestionStatus.currentSymbol = symbolObj.symbol;
        global.ingestionStatus.lastActive = new Date().toISOString();
        
        // Acquire token (respects Dhan's rate limit cooldown)
        const token = await limiter.acquire();
        
        try {
          // 1. Get expiry date (cached or API-fetched)
          const expiryDate = await getExpiryDate(symbolObj, token);
          if (!expiryDate) {
            throw new Error('No expiry dates returned by Dhan API');
          }
          
          // 2. Fetch Option Chain
          const rawResponse = await fetchOptionChain(symbolObj, expiryDate, token);
          if (!rawResponse || rawResponse.status !== 'success' || !rawResponse.data) {
            // Invalidate cached expiry date to recover if it was an expiry mismatch error
            delete expiryCache[symbolObj.symbol];
            
            const apiError = rawResponse?.data?.['808'] || rawResponse?.data?.['810'] || rawResponse?.remarks || 'API failure';
            throw new Error(`Dhan API Error: ${apiError}`);
          }
          
          const now = new Date();

          // 3. Fetch previous snapshot from DB (from latest_snapshot)
          const previousSnapshot = await getPreviousSnapshot(symbolObj.symbol);

          // 4. Parse and structure option chain + calculate IV4 metrics
          const snapshotDoc = mapResponseToDocument(symbolObj, rawResponse.data, previousSnapshot, expiryDate, now);
          
          // 5. Write immediately to MongoDB
          await writeSnapshot(snapshotDoc);
          
          successCount++;
          console.log(JSON.stringify({
            level: 'INFO',
            timestamp: now.toISOString(),
            event: 'symbol_ingestion_success',
            symbol: symbolObj.symbol,
            security_id: symbolObj.security_id,
            spot_price: snapshotDoc.spot_price,
            optionsCount: snapshotDoc.options.length,
            expiry: expiryDate,
            iv4: snapshotDoc.iv4
          }));

          // 6. Evaluate crossovers and raise alerts immediately
          if (previousSnapshot) {
            const prevSpot = Number(previousSnapshot.last_price || previousSnapshot.spot_price) || 0;
            const prevFlip = Number(previousSnapshot.Flip_strike) || 0;
            const currentSpot = snapshotDoc.spot_price;
            const currentFlip = snapshotDoc.Flip_strike;

            // Crossovers
            const priceCrossedUp = prevSpot < prevFlip && currentSpot >= currentFlip;
            const bullishFlow = snapshotDoc.call_net_flow > 0 && snapshotDoc.put_net_flow < 0 && snapshotDoc.iv_ratio > 1.15;

            const priceCrossedDown = prevSpot > prevFlip && currentSpot <= currentFlip;
            const bearishFlow = snapshotDoc.put_net_flow > 0 && snapshotDoc.call_net_flow < 0 && snapshotDoc.iv_ratio < (1 / 1.15);

            if (priceCrossedUp && bullishFlow) {
              const alertDoc = {
                timestamp: now,
                ts_ist: snapshotDoc.ts_ist,
                symbol: symbolObj.symbol,
                direction: 'BULLISH',
                spot: currentSpot,
                details: `Crossed Gamma Flip. IV Ratio: ${snapshotDoc.iv_ratio.toFixed(2)} | Call Flow: +ve`
              };
              await insertAlert(alertDoc).catch((e) => {
                console.error(`[Ingestor] Failed to save bullish alert for ${symbolObj.symbol}:`, e.message);
              });
              console.log(`🚨 [Ingestor ALERT] ${symbolObj.symbol} BULLISH BREAKOUT! Spot crossed Flip at ₹${currentSpot}`);
            }

            if (priceCrossedDown && bearishFlow) {
              const alertDoc = {
                timestamp: now,
                ts_ist: snapshotDoc.ts_ist,
                symbol: symbolObj.symbol,
                direction: 'BEARISH',
                spot: currentSpot,
                details: `Dropped below Gamma Flip. IV Ratio: ${snapshotDoc.iv_ratio.toFixed(2)} | Put Flow: +ve`
              };
              await insertAlert(alertDoc).catch((e) => {
                console.error(`[Ingestor] Failed to save bearish alert for ${symbolObj.symbol}:`, e.message);
              });
              console.log(`🚨 [Ingestor ALERT] ${symbolObj.symbol} BEARISH BREAKDOWN! Spot dropped below Flip at ₹${currentSpot}`);
            }
          }
        } catch (err) {
          failCount++;
          // Invalidate cache on errors to trigger fresh resolution in the next cycle
          delete expiryCache[symbolObj.symbol];
          
          console.error(JSON.stringify({
            level: 'ERROR',
            timestamp: new Date().toISOString(),
            event: 'symbol_ingestion_failed',
            symbol: symbolObj.symbol,
            security_id: symbolObj.security_id,
            error: err.message
          }));
        }
      }
      
      const duration = (Date.now() - cycleStart) / 1000;
      global.ingestionStatus.lastCycleDuration = duration;
      global.ingestionStatus.lastCycleStats = { success: successCount, fail: failCount };
      global.ingestionStatus.currentSymbol = null;
      
      console.log(`[Ingestor] Cycle #${cycleCount} completed in ${duration.toFixed(1)}s. Success: ${successCount}, Fail: ${failCount}.`);
      
      // Delay briefly between cycles
      await new Promise(resolve => setTimeout(resolve, 5000));
    } catch (cycleError) {
      console.error('[Ingestor] Error in master ingestion loop:', cycleError);
      global.ingestionStatus.error = cycleError.message;
      await new Promise(resolve => setTimeout(resolve, 10000));
    }
  }
}

export {
  iv4NormalCdf,
  iv4BlackScholesPrice,
  solveIv4,
  computeIv4FromStrikeChain,
  mapResponseToDocument
};
