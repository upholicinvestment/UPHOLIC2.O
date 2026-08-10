import { MongoClient } from 'mongodb';

const client = new MongoClient('mongodb://localhost:27017');
await client.connect();
const db = client.db('UPHOLIC2_O');

// Get first 10 RELIANCE candles to check shape
console.log('=== RELIANCE first 10 candles ===');
const docs = await db.collection('optstk_history_1m').find({symbol: 'RELIANCE'}).sort({timestamp: 1}).limit(10).toArray();
docs.forEach(d => console.log(JSON.stringify({ts: d.ts_ist, o: d.open, h: d.high, l: d.low, c: d.close, vol: d.volume})));

// Check with volume > 0
console.log('\n=== Volume stats for RELIANCE ===');
const total = await db.collection('optstk_history_1m').countDocuments({symbol: 'RELIANCE'});
const withVolume = await db.collection('optstk_history_1m').countDocuments({symbol: 'RELIANCE', volume: {$gt: 0}});
const varied = await db.collection('optstk_history_1m').countDocuments({symbol: 'RELIANCE', $where: 'this.open != this.close'});
console.log('Total:', total, '| Volume>0:', withVolume, '| open!=close:', varied);

// Check for any non-flat candles
console.log('\n=== Sample of candles with movement (high != low) ===');
const moving = await db.collection('optstk_history_1m').find({symbol: 'RELIANCE', $where: 'this.high != this.low'}).limit(5).toArray();
if (moving.length === 0) {
  console.log('NONE — all candles are perfectly flat (open=high=low=close=spot_price)!');
} else {
  moving.forEach(d => console.log({ts: d.ts_ist, o: d.open, h: d.high, l: d.low, c: d.close}));
}

await client.close();
