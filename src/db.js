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
