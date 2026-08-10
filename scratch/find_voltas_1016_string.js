import { MongoClient } from 'mongodb';
const client = new MongoClient('mongodb://localhost:27017');
await client.connect();
const db = client.db('UPHOLIC2_O');

const docs = await db.collection('optstk_history_1m').find({
  symbol: 'VOLTAS',
  timestamp: {
    $gte: '2026-08-10T04:40:00',
    $lte: '2026-08-10T04:50:00'
  }
}).toArray();

console.log('Docs with string timestamp range:', JSON.stringify(docs, null, 2));

// Find ANY docs for VOLTAS with timestamp starting with 2026-08-10T04:4
const docs2 = await db.collection('optstk_history_1m').find({
  symbol: 'VOLTAS',
  timestamp: { $regex: '^2026-08-10T04:4' }
}).toArray();
console.log('Docs with regex:', JSON.stringify(docs2, null, 2));

await client.close();
