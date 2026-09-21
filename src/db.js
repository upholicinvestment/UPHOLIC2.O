import { MongoClient } from 'mongodb';
import config from './config.js';

let client = null;
let db = null;

export async function connectDB() {
  if (db) return { client, db };

  console.log(`[DB] Connecting to MongoDB at ${config.mongoUri.replace(/\/\/.*@/, '//***@')}...`);
  client = new MongoClient(config.mongoUri, {
    connectTimeoutMS: 10000,
    socketTimeoutMS: 45000,
  });

  await client.connect();
  db = client.db(config.mongoDb);
  console.log(`[DB] Successfully connected to database: ${config.mongoDb}`);

  await ensureSchemaAndIndexes();

  return { client, db };
}

async function ensureSchemaAndIndexes() {
  try {
    // 1. Check if snapshots collection exists
    const collections = await db.listCollections({ name: 'snapshots' }).toArray();
    if (collections.length === 0) {
      console.log('[DB] Creating time-series collection "snapshots"...');
      await db.createCollection('snapshots', {
        timeseries: {
          timeField: 'fetched_at',
          metaField: 'symbol',
          granularity: 'minutes',
        },
      });
      console.log('[DB] "snapshots" time-series collection created.');
    } else {
      console.log('[DB] "snapshots" collection already exists.');
    }

    // 2. Ensure index on snapshots: { symbol: 1, fetched_at: -1 }
    // Note: in time-series collections, we can index the metaField and timeField
    console.log('[DB] Ensuring index on "snapshots" (symbol: 1, fetched_at: -1)...');
    await db.collection('snapshots').createIndex({ symbol: 1, fetched_at: -1 });

    // 3. Ensure index on latest_snapshot: { symbol: 1 } (unique)
    console.log('[DB] Ensuring index on "latest_snapshot" (symbol: 1)...');
    await db.collection('latest_snapshot').createIndex({ symbol: 1 }, { unique: true });

    // 4. Ensure index on alerts: { timestamp: -1 }
    console.log('[DB] Ensuring index on "alerts" (timestamp: -1)...');
    await db.collection('alerts').createIndex({ timestamp: -1 });
    
    console.log('[DB] Database schema and indexes are verified and ready.');
  } catch (error) {
    console.error('[DB] Error verifying/creating database schema and indexes:', error);
    throw error;
  }
}

export function getDB() {
  if (!db) {
    throw new Error('[DB] Database connection not initialized. Call connectDB() first.');
  }
  return db;
}

/**
 * Retrieves the last snapshot of the symbol from latest_snapshot.
 */
export async function getPreviousSnapshot(symbol) {
  const database = getDB();
  return database.collection('latest_snapshot').findOne({ symbol });
}

/**
 * Inserts a breakout alert into alerts collection.
 */
export async function insertAlert(alertDoc) {
  const database = getDB();
  await database.collection('alerts').insertOne(alertDoc);
}

/**
 * Writes the fetched stock & option chain data to snapshots (insert) and latest_snapshot (upsert)
 * immediately. Operates with full try-catch isolation.
 */
export async function writeSnapshot(snapshotDoc) {
  const database = getDB();
  const symbol = snapshotDoc.symbol;

  // We perform writes sequentially. If one fails, it propagates up to the caller to log it.
  // We do not run them inside a session or transaction to keep it simple, fast, and robust.

  // 1. Insert into history time-series collection
  await database.collection('snapshots').insertOne(snapshotDoc);

  // 2. Upsert into latest_snapshot collection.
  // IMPORTANT: After insertOne(), MongoDB mutates snapshotDoc in-place by adding an _id field.
  // We must NEVER include _id in a $set operation — MongoDB rejects it as immutable.
  // Destructuring is the safest way to exclude it without mutating the original object.
  const { _id, ...snapshotWithoutId } = snapshotDoc;
  await database.collection('latest_snapshot').updateOne(
    { symbol },
    { $set: snapshotWithoutId },
    { upsert: true }
  );

  // 3. Append 1-minute candle of the spot price to optstk_history_1m
  const candleDoc = {
    symbol: symbol,
    timestamp: snapshotDoc.fetched_at,
    ts_ist: snapshotDoc.ts_ist,
    open: snapshotDoc.spot_price,
    high: snapshotDoc.spot_price,
    low: snapshotDoc.spot_price,
    close: snapshotDoc.spot_price,
    volume: 0
  };
  await database.collection('optstk_history_1m').insertOne(candleDoc);

  // 4. If there is a non-zero iv4_change_5m, insert it into the iv4_spikes collection
  if (snapshotDoc.iv4_change_5m && snapshotDoc.iv4_change_5m !== 0) {
    await database.collection('iv4_spikes').insertOne(snapshotWithoutId);
  }

  // 5. If there is a non-neutral edge signal, insert it into the breakoutscanner_alerts collection
  const edge = calculateIvEdge(snapshotDoc.options, snapshotDoc.spot_price);
  if (edge.edge_signal !== 'NEUTRAL') {
    const signalAlert = {
      symbol: symbol,
      security_id: snapshotDoc.security_id,
      spot_price: snapshotDoc.spot_price,
      expiry: snapshotDoc.expiry,
      fetched_at: snapshotDoc.fetched_at,
      ts_ist: snapshotDoc.ts_ist,
      edge_signal: edge.edge_signal,
      iv_ratio: Number(edge.iv_ratio.toFixed(3)),
      iv_skew: Number(edge.iv_skew.toFixed(2)),
      vw_iv_call: Number(edge.vw_iv_call.toFixed(2)),
      vw_iv_put: Number(edge.vw_iv_put.toFixed(2)),
      call_flow_net: Number(edge.call_flow_net.toFixed(2)),
      put_flow_net: Number(edge.put_flow_net.toFixed(2))
    };
    await database.collection('breakoutscanner_alerts').insertOne(signalAlert);
  }

  // 6. High-Conviction 3-Minute Price & OI Alert Trigger
  await checkAndLogPoiAlert(database, snapshotDoc);
}

// In-memory cooldown tracking: symbol -> lastAlertTimeMs
const poiAlertCooldowns = new Map();

async function checkAndLogPoiAlert(database, snapshotDoc) {
  try {
    const symbol = snapshotDoc.symbol;
    const nowMs = new Date(snapshotDoc.fetched_at || Date.now()).getTime();

    // 30-minute cooldown per symbol to ensure top-quality alerts (~15-25/day)
    const lastAlertTime = poiAlertCooldowns.get(symbol) || 0;
    if (nowMs - lastAlertTime < 30 * 60 * 1000) {
      return;
    }

    // Get previous snapshot from history
    const prevSnap = await database.collection('snapshots')
      .find({ symbol })
      .sort({ fetched_at: -1 })
      .skip(1)
      .limit(1)
      .toArray();

    if (!prevSnap || prevSnap.length === 0) return;
    const prevDoc = prevSnap[0];

    const prevTimeMs = new Date(prevDoc.fetched_at || 0).getTime();
    // Must be within continuous intraday trading (gap <= 10 mins), ignoring overnight gaps
    if (nowMs - prevTimeMs > 10 * 60 * 1000 || nowMs - prevTimeMs < 60 * 1000) {
      return;
    }

    const currentSpot = Number(snapshotDoc.spot_price || 0);
    const prevSpot = Number(prevDoc.spot_price || 0);
    if (!currentSpot || !prevSpot || prevSpot <= 0) return;

    const priceChangePct = ((currentSpot - prevSpot) / prevSpot) * 100;
    const priceChange = currentSpot - prevSpot;

    const currentOptions = Array.isArray(snapshotDoc.options) ? snapshotDoc.options : [];
    const prevOptions = Array.isArray(prevDoc.options) ? prevDoc.options : [];

    let currentTotalOi = 0;
    let callOi = 0;
    let putOi = 0;
    let topStrike = '—';
    let maxStrikeDiff = 0;

    for (const opt of currentOptions) {
      const oi = Number(opt.oi || 0);
      const pOi = Number(opt.previous_oi || 0);
      currentTotalOi += oi;
      if (opt.type === 'CE') callOi += oi;
      else putOi += oi;

      const diff = oi - pOi;
      if (Math.abs(diff) > Math.abs(maxStrikeDiff)) {
        maxStrikeDiff = diff;
        topStrike = `${opt.strike} ${opt.type} (${diff > 0 ? '+' : ''}${Math.round(diff)})`;
      }
    }

    let prevTotalOi = 0;
    for (const opt of prevOptions) {
      prevTotalOi += Number(opt.oi || 0);
    }

    if (prevTotalOi <= 0) return;

    const oiChange = currentTotalOi - prevTotalOi;
    const oiChangePct = (oiChange / prevTotalOi) * 100;

    // Strict Institutional Quality Filters:
    // 1. Min 0.60% price momentum in 3-minute candle
    // 2. Min 1.00% OI surge/drop
    // 3. Min 40,000 contracts absolute Total OI change
    // 4. Min 15,000 contracts on the dominant driver strike
    const isPriceSignificant = Math.abs(priceChangePct) >= 0.60;
    const isOiSignificant = Math.abs(oiChangePct) >= 1.00 && Math.abs(oiChange) >= 40000;
    const isStrikeSignificant = Math.abs(maxStrikeDiff) >= 15000;

    if (!isPriceSignificant || !isOiSignificant || !isStrikeSignificant) {
      return;
    }

    let quadrant, label, badgeClass, icon, color;
    if (priceChangePct >= 0 && oiChangePct >= 0) {
      quadrant = 'LONG_BUILDUP';
      label = 'Long Buildup';
      badgeClass = 'badge-long-buildup';
      icon = 'fa-arrow-trend-up';
      color = '#10b981';
    } else if (priceChangePct >= 0 && oiChangePct < 0) {
      quadrant = 'SHORT_COVERING';
      label = 'Short Covering';
      badgeClass = 'badge-short-covering';
      icon = 'fa-rocket';
      color = '#06b6d4';
    } else if (priceChangePct < 0 && oiChangePct >= 0) {
      quadrant = 'SHORT_BUILDUP';
      label = 'Short Buildup';
      badgeClass = 'badge-short-buildup';
      icon = 'fa-arrow-trend-down';
      color = '#ef4444';
    } else {
      quadrant = 'LONG_UNWINDING';
      label = 'Long Unwinding';
      badgeClass = 'badge-long-unwinding';
      icon = 'fa-triangle-exclamation';
      color = '#f59e0b';
    }

    const pcr = callOi > 0 ? Number((putOi / callOi).toFixed(2)) : 0;

    const alertRecord = {
      symbol,
      spot_price: currentSpot,
      price_change: Number(priceChange.toFixed(2)),
      price_change_pct: Number(priceChangePct.toFixed(2)),
      total_oi: currentTotalOi,
      oi_change: oiChange,
      oi_change_pct: Number(oiChangePct.toFixed(2)),
      call_oi: callOi,
      put_oi: putOi,
      pcr,
      quadrant,
      label,
      badge_class: badgeClass,
      icon,
      color,
      top_strike: topStrike,
      timestamp: new Date(snapshotDoc.fetched_at || Date.now()),
      ts_ist: snapshotDoc.ts_ist
    };

    await database.collection('poi_scanner_alerts').insertOne(alertRecord);
    poiAlertCooldowns.set(symbol, nowMs);
    console.log(`[POI ALERT] ${snapshotDoc.ts_ist} -> ${symbol} ${label} (Price: ${priceChangePct.toFixed(2)}%, OI: ${oiChangePct.toFixed(2)}%)`);
  } catch (err) {
    console.error('[POI ALERT] Error checking alert:', err);
  }
}

function calculateIvEdge(options, spot_price, otm_threshold_pct = 1.5) {
  if (!options || !Array.isArray(options) || options.length === 0 || !spot_price) {
    return {
      vw_iv_call: 0,
      vw_iv_put: 0,
      iv_ratio: 0,
      iv_skew: 0,
      call_flow_net: 0,
      put_flow_net: 0,
      edge_signal: 'NEUTRAL'
    };
  }

  const otm_call_strike = spot_price * (1 + (otm_threshold_pct / 100));
  const otm_put_strike = spot_price * (1 - (otm_threshold_pct / 100));

  let call_iv_weighted_sum = 0;
  let call_volume_sum = 0;
  let put_iv_weighted_sum = 0;
  let put_volume_sum = 0;

  let call_flow_momentum = 0;
  let put_flow_momentum = 0;

  for (const opt of options) {
    const strike = Number(opt.strike);
    const type = opt.type;
    const iv = Number(opt.iv || 0);
    const volume = Number(opt.volume || 0);
    const oi = Number(opt.oi || 0);
    const prev_oi = Number(opt.previous_oi || 0);
    const last_price = Number(opt.ltp || 0);
    const prev_close = Number(opt.previous_close_price || 0);

    const oi_change = oi - prev_oi;
    const premium_change = last_price - prev_close;
    const net_flow = oi_change * premium_change;

    if (type === 'CE') {
      if (strike >= otm_call_strike) {
        call_iv_weighted_sum += iv * volume;
        call_volume_sum += volume;
        call_flow_momentum += net_flow;
      }
    } else if (type === 'PE') {
      if (strike <= otm_put_strike) {
        put_iv_weighted_sum += iv * volume;
        put_volume_sum += volume;
        put_flow_momentum += net_flow;
      }
    }
  }

  const vw_iv_call = call_volume_sum > 0 ? (call_iv_weighted_sum / call_volume_sum) : 0;
  const vw_iv_put = put_volume_sum > 0 ? (put_iv_weighted_sum / put_volume_sum) : 0;

  const iv_ratio = vw_iv_put > 0 ? (vw_iv_call / vw_iv_put) : 0;
  const iv_skew = vw_iv_put - vw_iv_call;

  let signal = 'NEUTRAL';
  if (iv_ratio > 1.2 && call_flow_momentum > 0) {
    signal = 'BULLISH DIVERGENCE (Call IV Expanding + Premium Build)';
  } else if (iv_ratio < 0.8 && put_flow_momentum > 0) {
    signal = 'BEARISH DIVERGENCE (Put IV Expanding + Put Premium Build)';
  } else if (iv_ratio > 1.2 && call_flow_momentum < 0) {
    signal = 'CALL SHORT-COVERING SQUEEZE (Call IV Expanding + Premium Unwind)';
  } else if (iv_ratio < 0.8 && put_flow_momentum < 0) {
    signal = 'PUT SHORT-COVERING (Put IV Expanding + Put Premium Unwind)';
  }

  return {
    vw_iv_call,
    vw_iv_put,
    iv_ratio,
    iv_skew,
    call_flow_net: call_flow_momentum,
    put_flow_net: put_flow_momentum,
    edge_signal: signal
  };
}
