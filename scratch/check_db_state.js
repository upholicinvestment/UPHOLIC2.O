import { MongoClient } from 'mongodb';
import dotenv from 'dotenv';
dotenv.config();

async function main() {
  const uri = process.env.MONGO_URI || 'mongodb://localhost:27017';
  const dbName = process.env.MONGO_DB || 'UPHOLIC2_O';
  
  console.log(`Connecting to ${uri}, database: ${dbName}...`);
  const client = new MongoClient(uri);
  await client.connect();
  const db = client.db(dbName);
  
  const snapCount = await db.collection('snapshots').countDocuments();
  const latestCount = await db.collection('latest_snapshot').countDocuments();
  console.log(`Snapshots count: ${snapCount}`);
  console.log(`Latest snapshots count: ${latestCount}`);
  
  const abbInstruments = await db.collection('instruments').find({ underlying_symbol: "ABB" }).limit(5).toArray();
  console.log("ABB Instruments in DB:", JSON.stringify(abbInstruments, null, 2));
  
  await client.close();
}

main().catch(console.error);
