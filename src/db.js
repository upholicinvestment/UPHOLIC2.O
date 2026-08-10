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

  // 2. Upsert into latest_snapshot collection
  await database.collection('latest_snapshot').updateOne(
    { symbol },
    { $set: snapshotDoc },
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
}
