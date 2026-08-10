import axios from 'axios';
import dotenv from 'dotenv';
dotenv.config();

const config = {
  clientId: process.env.DHAN_CLIENT_ID,
  accessToken: process.env.DHAN_TOKEN_1,
  expiryListUrl: process.env.DHAN_EXPIRY_LIST_URL || 'https://api.dhan.co/v2/optionchain/expirylist',
  optionChainUrl: process.env.DHAN_OPTION_CHAIN_URL || 'https://api.dhan.co/v2/optionchain',
};

async function main() {
  const headers = {
    'access-token': config.accessToken,
    'client-id': config.clientId,
    'Content-Type': 'application/json'
  };

  // 1. Fetch expiries for RELIANCE (2885)
  console.log("Fetching expiries for RELIANCE...");
  let expiries = [];
  try {
    const response = await axios.post(config.expiryListUrl, {
      UnderlyingScrip: 2885,
      UnderlyingSeg: 'NSE_FNO'
    }, { headers });
    expiries = response.data?.data || [];
    console.log("Expiries returned:", expiries);
  } catch (err) {
    console.error("Failed to fetch expiries:", err.message);
    return;
  }

  // 2. Loop through each expiry and fetch option chain
  for (const expiry of expiries) {
    console.log(`Fetching option chain for RELIANCE expiry: ${expiry}...`);
    try {
      const response = await axios.post(config.optionChainUrl, {
        UnderlyingScrip: 2885,
        UnderlyingSeg: 'NSE_FNO',
        Expiry: expiry
      }, { headers });
      const strikes = response.data?.data?.strikes ? Object.keys(response.data.data.strikes) : [];
      console.log(`  Expiry: ${expiry} -> status: ${response.data?.status}, strikes: ${strikes.length}, ltp: ${response.data?.data?.last_price}`);
    } catch (err) {
      console.error(`  Failed for expiry ${expiry}:`, err.message);
    }
    // delay to respect rate limits
    await new Promise(resolve => setTimeout(resolve, 3100));
  }
}

main();
