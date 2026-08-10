import { MongoClient } from 'mongodb';
const client = new MongoClient('mongodb://localhost:27017');
await client.connect();
const db = client.db('UPHOLIC2_O');

const docs = await db.collection('optstk_history_1m').find({
  timestamp: {
    $gte: new Date('2026-08-10T04:44:00Z'),
    $lte: new Date('2026-08-10T04:48:00Z')
  }
}).toArray();

console.log('Docs around 10:16:', docs.length);
if (docs.length > 0) {
  console.log('Sample docs:', docs.slice(0, 5).map(d => ({ symbol: d.symbol, ts: d.ts_ist, o: d.open, c: d.close })));
}

await client.close();
