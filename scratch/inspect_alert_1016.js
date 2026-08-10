import { MongoClient } from 'mongodb';
const client = new MongoClient('mongodb://localhost:27017');
await client.connect();
const db = client.db('UPHOLIC2_O');

// Find the alert at 10:16:11.692
const alert = await db.collection('v1_scanner_alerts').findOne({ ts_ist: '2026-08-10 10:16:11.692 IST' });
console.log('Alert:', JSON.stringify(alert, null, 2));

if (alert) {
  // Let's find candles for VOLTAS around 10:16
  const candles = await db.collection('optstk_history_1m').find({
    symbol: alert.symbol,
    ts_ist: { $regex: '^2026-08-10 10:1' }
  }).toArray();
  console.log(`\n=== Candles for ${alert.symbol} around 10:16 ===`);
  candles.forEach(c => console.log(JSON.stringify({ ts: c.ts_ist, o: c.open, h: c.high, l: c.low, c: c.close, vol: c.volume })));
}

await client.close();
