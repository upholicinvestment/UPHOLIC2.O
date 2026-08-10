import { MongoClient } from 'mongodb';
import dotenv from 'dotenv';
dotenv.config();

async function main() {
  const uri = process.env.MONGO_URI || 'mongodb://localhost:27017';
  const client = new MongoClient(uri);
  await client.connect();
  const db = client.db('Upholicfno');
  
  console.log("Connected to Upholicfno database.");
  
  const collections = await db.listCollections().toArray();
  console.log("Collections in Upholicfno:", collections.map(c => c.name));
  
  const col = db.collection('optstk_live');
  const doc = await col.findOne({ underlying_symbol: "360ONE" });
  if (doc) {
    console.log("optstk_live 360ONE underlying_symbol:", doc.underlying_symbol);
    console.log("optstk_live 360ONE ts:", doc.ts);
    console.log("optstk_live 360ONE ts_ist:", doc.ts_ist);
    console.log("optstk_live 360ONE strikes count:", doc.strikes ? doc.strikes.length : 0);
  }
  
  const docAbb = await col.findOne({ underlying_symbol: "ABB" });
  if (docAbb) {
    console.log("optstk_live ABB underlying_symbol:", docAbb.underlying_symbol);
    console.log("optstk_live ABB ts:", docAbb.ts);
    console.log("optstk_live ABB ts_ist:", docAbb.ts_ist);
    console.log("optstk_live ABB strikes count:", docAbb.strikes ? docAbb.strikes.length : 0);
  }

  await client.close();
}

main().catch(console.error);
