import { MongoClient } from 'mongodb';
const client = new MongoClient('mongodb://localhost:27017');
await client.connect();
const db = client.db('UPHOLIC2_O');

// Find documents in optstk_history_1m around 10:16:11
const docs = await db.collection('optstk_history_1m').find({
  symbol: 'VOLTAS',
  timestamp: {
    $gte: new Date('2026-08-10T04:40:00Z'),
    $lte: new Date('2026-08-10T04:50:00Z')
  }
}).toArray();

console.log('Docs:', JSON.stringify(docs, null, 2));

await client.close();
