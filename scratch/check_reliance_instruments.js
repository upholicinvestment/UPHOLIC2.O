import { MongoClient } from 'mongodb';
import dotenv from 'dotenv';
dotenv.config();

async function main() {
  const uri = process.env.MONGO_URI || 'mongodb://localhost:27017';
  const client = new MongoClient(uri);
  await client.connect();
  const db = client.db(process.env.MONGO_DB || 'UPHOLIC2_O');
  
  const results = await db.collection('instruments').find({
    underlying_symbol: "RELIANCE",
    exch_id: "NSE"
  }).limit(5).toArray();
  
  console.log("RELIANCE Instruments in DB:", JSON.stringify(results, null, 2));

  await client.close();
}

main().catch(console.error);
