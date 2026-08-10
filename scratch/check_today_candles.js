import { MongoClient } from 'mongodb';
const client = new MongoClient('mongodb://localhost:27017');
await client.connect();
const db = client.db('UPHOLIC2_O');

// Today's RELIANCE candles
const today = '2026-08-10';
const todayCandles = await db.collection('optstk_history_1m').find(
  { symbol: 'RELIANCE', ts_ist: { $regex: `^${today}` } }
).sort({ timestamp: 1 }).limit(15).toArray();
console.log('=== RELIANCE candles TODAY ===');
console.log('Count:', todayCandles.length);
todayCandles.forEach(d => console.log(JSON.stringify({ ts: d.ts_ist, o: d.open, h: d.high, l: d.low, c: d.close, vol: d.volume })));

// Last good historical
const lastGood = await db.collection('optstk_history_1m').find(
  { symbol: 'RELIANCE', ts_ist: { $lt: '2026-08-10' } }
).sort({ timestamp: -1 }).limit(3).toArray();
console.log('\n=== Last 3 candles BEFORE today ===');
lastGood.forEach(d => console.log(JSON.stringify({ ts: d.ts_ist, o: d.open, h: d.high, l: d.low, c: d.close, vol: d.volume })));

// How many total today vs all symbols
const todayTotal = await db.collection('optstk_history_1m').countDocuments({ ts_ist: { $regex: `^${today}` } });
const volZero = await db.collection('optstk_history_1m').countDocuments({ ts_ist: { $regex: `^${today}` }, volume: 0 });
console.log(`\nToday total candles: ${todayTotal}, volume=0: ${volZero} (${(volZero/todayTotal*100).toFixed(1)}%)`);

await client.close();
