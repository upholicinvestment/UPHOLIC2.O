import axios from 'axios';
import dotenv from 'dotenv';
dotenv.config();

const config = {
  clientId: process.env.DHAN_CLIENT_ID,
  accessToken: process.env.DHAN_TOKEN_1,
  optionChainUrl: process.env.DHAN_OPTION_CHAIN_URL || 'https://api.dhan.co/v2/optionchain',
};

async function main() {
  const payload = {
    UnderlyingScrip: 13, // NIFTY 50
    UnderlyingSeg: 'IDX_I',
    Expiry: '2026-08-25'
  };

  const headers = {
    'access-token': config.accessToken,
    'client-id': config.clientId,
    'Content-Type': 'application/json'
  };

  try {
    const response = await axios.post(config.optionChainUrl, payload, { headers });
    console.log("NIFTY Status:", response.status);
    console.log("NIFTY Data:", JSON.stringify(response.data, null, 2));
  } catch (err) {
    console.error("NIFTY call failed:", err.message);
    if (err.response) {
      console.error("Error response data:", JSON.stringify(err.response.data, null, 2));
    }
  }
}

main();
