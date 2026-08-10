import { MongoClient } from 'mongodb';
import dotenv from 'dotenv';
dotenv.config();

async function main() {
  const uri = process.env.MONGO_URI || 'mongodb://localhost:27017';
  const client = new MongoClient(uri);
  await client.connect();
  const db = client.db(process.env.MONGO_DB || 'UPHOLIC2_O');
  
  // Find instruments for ABB on NSE
  const results = await db.collection('instruments').find({
    underlying_symbol: "ABB",
    exch_id: "NSE"
  }).limit(5).toArray();
  
  console.log("NSE ABB Instruments in DB:", JSON.stringify(results, null, 2));
  
  // Find instrument for NIFTY
  const nifty = await db.collection('instruments').findOne({
    underlying_symbol: "NIFTY",
    exch_id: "NSE"
  });
  console.log("NSE NIFTY Instrument in DB:", JSON.stringify(nifty, null, 2));

  await client.close();
}

main().catch(console.error);
