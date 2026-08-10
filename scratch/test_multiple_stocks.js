import axios from 'axios';
import dotenv from 'dotenv';
dotenv.config();

const config = {
  clientId: process.env.DHAN_CLIENT_ID,
  accessToken: process.env.DHAN_TOKEN_1,
  optionChainUrl: process.env.DHAN_OPTION_CHAIN_URL || 'https://api.dhan.co/v2/optionchain',
};

const stocks = [
  { symbol: 'RELIANCE', id: 2885 },
  { symbol: 'TCS', id: 11536 },
  { symbol: 'INFY', id: 1594 },
  { symbol: 'SBIN', id: 3045 },
  { symbol: 'ICICIBANK', id: 4963 },
];

async function testStock(symbol, id, segment) {
  const payload = {
    UnderlyingScrip: id,
    UnderlyingSeg: segment,
    Expiry: '2026-08-25'
  };

  const headers = {
    'access-token': config.accessToken,
    'client-id': config.clientId,
    'Content-Type': 'application/json'
  };

  try {
    const response = await axios.post(config.optionChainUrl, payload, { headers });
    const strikes = response.data?.data?.strikes ? Object.keys(response.data.data.strikes) : [];
    console.log(`Stock: ${symbol} (${id}) | Seg: ${segment} -> Status: ${response.status}, Data Status: ${response.data?.status || 'none'}, strikes count: ${strikes.length}, ltp: ${response.data?.data?.last_price || 0}`);
  } catch (err) {
    console.log(`Stock: ${symbol} (${id}) | Seg: ${segment} -> Failed: ${err.message}`);
    if (err.response) {
      console.log(`  Response:`, err.response.data);
    }
  }
}

async function main() {
  for (const stock of stocks) {
    for (const seg of ['NSE_EQ', 'NSE_FNO']) {
      await testStock(stock.symbol, stock.id, seg);
      await new Promise(resolve => setTimeout(resolve, 3100)); // rate limit delay
    }
  }
}

main();
