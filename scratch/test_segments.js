import axios from 'axios';
import dotenv from 'dotenv';
dotenv.config();

const config = {
  clientId: process.env.DHAN_CLIENT_ID,
  accessToken: process.env.DHAN_TOKEN_1,
  optionChainUrl: process.env.DHAN_OPTION_CHAIN_URL || 'https://api.dhan.co/v2/optionchain',
};

async function testSegment(segment) {
  const payload = {
    UnderlyingScrip: 13, // ABB
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
    console.log(`Segment: ${segment} -> Status: ${response.status}, Data Status: ${response.data ? response.data.status : 'none'}, strikes count: ${response.data?.data?.strikes ? response.data.data.strikes.length : 0}`);
    if (response.data?.remarks) {
      console.log(`  Remarks: ${response.data.remarks}`);
    }
  } catch (err) {
    console.log(`Segment: ${segment} -> Failed: ${err.message}`);
  }
}

async function main() {
  const segments = ['NSE_EQ', 'NSE_FNO', 'IDX_I', 'BSE_EQ', 'BSE_FNO'];
  for (const seg of segments) {
    await testSegment(seg);
    // delay to avoid rate limit
    await new Promise(resolve => setTimeout(resolve, 3100));
  }
}

main();
