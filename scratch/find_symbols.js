import fs from 'fs';
import path from 'path';

async function main() {
  const symbols = JSON.parse(fs.readFileSync('symbols.json', 'utf8'));
  const targets = ['RELIANCE', 'TCS', 'INFY', 'SBIN', 'ICICIBANK'];
  
  const found = symbols.filter(s => targets.includes(s.symbol));
  console.log("Found target symbols in symbols.json:", found);
}

main().catch(console.error);
