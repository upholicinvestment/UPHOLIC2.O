import axios from 'axios';
import dotenv from 'dotenv';
dotenv.config();

const config = {
  clientId: process.env.DHAN_CLIENT_ID,
  accessToken: process.env.DHAN_TOKEN_1,
  optionChainUrl: process.env.DHAN_OPTION_CHAIN_URL || 'https://api.dhan.co/v2/optionchain',
};

async function main() {
  console.log("Client ID:", config.clientId);
  console.log("Option Chain URL:", config.optionChainUrl);

  const payload = {
    UnderlyingScrip: 13, // ABB (F&O stock)
    UnderlyingSeg: 'NSE_EQ',
    Expiry: '2026-08-25'
  };

  const headers = {
    'access-token': config.accessToken,
    'client-id': config.clientId,
    'Content-Type': 'application/json'
  };

  try {
    const response = await axios.post(config.optionChainUrl, payload, { headers });
    console.log("API Response Status:", response.status);
    console.log("API Response Data Status:", response.data ? response.data.status : 'no data');
    console.log("API Response Data Keys:", response.data ? Object.keys(response.data) : 'no data');
    if (response.data && response.data.data) {
      console.log("last_price:", response.data.data.last_price);
      console.log("strikes count:", response.data.data.strikes ? response.data.data.strikes.length : 0);
      if (response.data.data.strikes && response.data.data.strikes.length > 0) {
        console.log("Sample strike details:", JSON.stringify(response.data.data.strikes[0], null, 2));
      }
    }
  } catch (err) {
    console.error("API call failed:", err.message);
    if (err.response) {
      console.error("Response data:", err.response.data);
    }
  }
}

main();
