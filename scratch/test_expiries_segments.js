import axios from 'axios';
import dotenv from 'dotenv';
dotenv.config();

const config = {
  clientId: process.env.DHAN_CLIENT_ID,
  accessToken: process.env.DHAN_TOKEN_1,
  expiryListUrl: process.env.DHAN_EXPIRY_LIST_URL || 'https://api.dhan.co/v2/optionchain/expirylist',
};

async function testExpirySegment(segment) {
  const payload = {
    UnderlyingScrip: 13, // ABB
    UnderlyingSeg: segment
  };

  const headers = {
    'access-token': config.accessToken,
    'client-id': config.clientId,
    'Content-Type': 'application/json'
  };

  try {
    const response = await axios.post(config.expiryListUrl, payload, { headers });
    console.log(`Segment: ${segment} -> Status: ${response.status}, Data:`, response.data);
  } catch (err) {
    console.log(`Segment: ${segment} -> Failed: ${err.message}`);
    if (err.response) {
      console.log(`  Response:`, err.response.data);
    }
  }
}

async function main() {
  const segments = ['NSE_EQ', 'NSE_FNO', 'IDX_I'];
  for (const seg of segments) {
    await testExpirySegment(seg);
    await new Promise(resolve => setTimeout(resolve, 3100));
  }
}

main();
