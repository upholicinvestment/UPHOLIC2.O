import { MongoClient } from 'mongodb';
const client = new MongoClient('mongodb://localhost:27017');
await client.connect();
const db = client.db('UPHOLIC2_O');

// Find a doc in optstk_history_1m
const doc = await db.collection('optstk_history_1m').findOne({ symbol: 'VOLTAS' });
console.log('Document:', JSON.stringify(doc, null, 2));
console.log('Type of timestamp:', typeof doc.timestamp, 'Is Date:', doc.timestamp instanceof Date);

// Find a doc in snapshots
const docSnap = await db.collection('snapshots').findOne({ symbol: 'VOLTAS' });
console.log('\nSnapshot Document:', JSON.stringify(docSnap, null, 2));
console.log('Type of fetched_at:', typeof docSnap.fetched_at, 'Is Date:', docSnap.fetched_at instanceof Date);

await client.close();
