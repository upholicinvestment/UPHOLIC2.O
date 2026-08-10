import axios from 'axios';
import dotenv from 'dotenv';
dotenv.config();

const config = {
  clientId: process.env.DHAN_CLIENT_ID,
  accessToken: process.env.DHAN_TOKEN_1,
  expiryListUrl: process.env.DHAN_EXPIRY_LIST_URL || 'https://api.dhan.co/v2/optionchain/expirylist',
  clientIdHeader: 'client-id',
  accessTokenHeader: 'access-token',
};

async function main() {
  console.log("Client ID:", config.clientId);
  console.log("Expiry List URL:", config.expiryListUrl);

  const payload = {
    UnderlyingScrip: 13, // ABB (F&O stock)
    UnderlyingSeg: 'NSE_EQ'
  };

  const headers = {
    'access-token': config.accessToken,
    'client-id': config.clientId,
    'Content-Type': 'application/json'
  };

  try {
    const response = await axios.post(config.expiryListUrl, payload, { headers });
    console.log("API Response Status:", response.status);
    console.log("API Response Data:", JSON.stringify(response.data, null, 2));
  } catch (err) {
    console.error("API call failed:", err.message);
    if (err.response) {
      console.error("Response data:", err.response.data);
    }
  }
}

main();
