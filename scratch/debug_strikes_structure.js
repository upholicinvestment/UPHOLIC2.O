import axios from 'axios';
import dotenv from 'dotenv';
dotenv.config();

const config = {
  clientId: process.env.DHAN_CLIENT_ID,
  accessToken: process.env.DHAN_TOKEN_1,
  optionChainUrl: process.env.DHAN_OPTION_CHAIN_URL || 'https://api.dhan.co/v2/optionchain',
};

async function main() {
  // Use ABCAPITAL which we saw succeed with spot_price in the logs
  const payload = {
    UnderlyingScrip: 21614,
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
    const data = response.data?.data;
    console.log("Top-level data keys:", Object.keys(data || {}));
    console.log("last_price:", data?.last_price);
    console.log("Type of 'strikes':", typeof data?.strikes);
    console.log("Is array?", Array.isArray(data?.strikes));

    if (data?.strikes) {
      if (Array.isArray(data.strikes)) {
        console.log("strikes is ARRAY, length:", data.strikes.length);
        if (data.strikes.length > 0) {
          console.log("Sample strike[0]:", JSON.stringify(data.strikes[0], null, 2));
        }
      } else {
        console.log("strikes is OBJECT, keys:", Object.keys(data.strikes).slice(0, 5));
        const firstKey = Object.keys(data.strikes)[0];
        console.log(`Sample strikes["${firstKey}"]:`, JSON.stringify(data.strikes[firstKey], null, 2));
      }
    } else {
      console.log("No 'strikes' field. Full data:", JSON.stringify(data, null, 2).slice(0, 1000));
    }
  } catch (err) {
    console.error("Failed:", err.message);
    if (err.response) console.error("Response:", err.response.data);
  }
}

main();
