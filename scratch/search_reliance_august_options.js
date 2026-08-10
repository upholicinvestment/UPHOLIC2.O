import { MongoClient } from 'mongodb';
import dotenv from 'dotenv';
dotenv.config();

async function main() {
  const uri = process.env.MONGO_URI || 'mongodb://localhost:27017';
  const client = new MongoClient(uri);
  await client.connect();
  const db = client.db(process.env.MONGO_DB || 'UPHOLIC2_O');
  
  const count = await db.collection('instruments').countDocuments({
    underlying_symbol: "RELIANCE",
    exch_id: "NSE",
    expiry_date: "2026-08-25"
  });
  
  console.log(`Number of RELIANCE options expiring on 2026-08-25 in DB: ${count}`);

  const sample = await db.collection('instruments').findOne({
    underlying_symbol: "RELIANCE",
    exch_id: "NSE",
    expiry_date: "2026-08-25"
  });
  console.log("Sample option contract in DB:", sample);

  await client.close();
}

main().catch(console.error);
