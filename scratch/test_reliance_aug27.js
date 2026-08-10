import axios from 'axios';
import dotenv from 'dotenv';
dotenv.config();

const config = {
  clientId: process.env.DHAN_CLIENT_ID,
  accessToken: process.env.DHAN_TOKEN_1,
  optionChainUrl: process.env.DHAN_OPTION_CHAIN_URL || 'https://api.dhan.co/v2/optionchain',
};

async function testExpiry(expiry) {
  const payload = {
    UnderlyingScrip: 2885, // RELIANCE
    UnderlyingSeg: 'NSE_FNO',
    Expiry: expiry
  };

  const headers = {
    'access-token': config.accessToken,
    'client-id': config.clientId,
    'Content-Type': 'application/json'
  };

  try {
    const response = await axios.post(config.optionChainUrl, payload, { headers });
    const strikes = response.data?.data?.strikes ? Object.keys(response.data.data.strikes) : [];
    console.log(`RELIANCE Expiry: ${expiry} -> status: ${response.data?.status}, strikes: ${strikes.length}, ltp: ${response.data?.data?.last_price || 0}`);
    if (response.data?.remarks) {
      console.log(`  Remarks: ${response.data.remarks}`);
    }
  } catch (err) {
    console.error(`  Failed for expiry ${expiry}:`, err.message);
  }
}

async function main() {
  await testExpiry('2026-08-27');
  await new Promise(resolve => setTimeout(resolve, 3100));
  await testExpiry('2026-08-25');
}

main();
