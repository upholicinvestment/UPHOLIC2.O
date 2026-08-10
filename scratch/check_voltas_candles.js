import { MongoClient } from 'mongodb';
const client = new MongoClient('mongodb://localhost:27017');
await client.connect();
const db = client.db('UPHOLIC2_O');

const count = await db.collection('optstk_history_1m').countDocuments({ symbol: 'VOLTAS', ts_ist: { $regex: '^2026-08-10' } });
console.log('Total Voltas candles today:', count);

const sample = await db.collection('optstk_history_1m').find({ symbol: 'VOLTAS', ts_ist: { $regex: '^2026-08-10' } }).sort({ timestamp: 1 }).limit(10).toArray();
sample.forEach(c => console.log(JSON.stringify(c)));

await client.close();
