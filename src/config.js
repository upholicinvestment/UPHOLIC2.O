import dotenv from 'dotenv';
import path from 'path';

// Load .env
dotenv.config();

function extractClientIdFromToken(token) {
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length === 3) {
      // Decode JWT payload
      const payloadJson = Buffer.from(parts[1], 'base64').toString('utf8');
      const payload = JSON.parse(payloadJson);
      return payload.dhanClientId || null;
    }
  } catch (e) {
    console.warn(`[Config] Failed to extract client-id from token payload: ${e.message}`);
  }
  return null;
}

const config = {
  tokens: [
    process.env.DHAN_TOKEN,
  ].filter(Boolean),

  optionChainUrl: process.env.DHAN_OPTION_CHAIN_URL || 'https://api.dhan.co/v2/optionchain',
  expiryListUrl: process.env.DHAN_EXPIRY_LIST_URL || 'https://api.dhan.co/v2/optionchain/expirylist',

  clientId: process.env.DHAN_CLIENT_ID || null,
  rateLimitSeconds: parseFloat(process.env.DHAN_RATE_LIMIT_SECONDS || '3'),

  marketOpenTime: process.env.MARKET_OPEN_TIME || '09:15',
  marketCloseTime: process.env.MARKET_CLOSE_TIME || '15:40',
  marketTimezone: process.env.MARKET_TIMEZONE || 'Asia/Kolkata',

  mongoUri: process.env.MONGO_URI || 'mongodb://localhost:27017',
  mongoDb: process.env.MONGO_DB || 'dhan_market_data',

  totalSymbols: parseInt(process.env.TOTAL_SYMBOLS || '208', 10),
  port: parseInt(process.env.PORT || '3000', 10),
  marketExpiryDate: process.env.MARKET_EXPIRY_DATE || null,

  riskFreeRate: parseFloat(process.env.RISK_FREE_RATE || '0.07'),
  dividendYield: parseFloat(process.env.DIVIDEND_YIELD || '0'),
};

if (config.tokens.length === 0) {
  throw new Error('DHAN_TOKEN must be specified in the environment.');
}

// Auto-extract client-id if not provided explicitly
if (!config.clientId) {
  config.clientId = extractClientIdFromToken(config.tokens[0]);
  if (config.clientId) {
    console.log(`[Config] Automatically extracted client ID: ${config.clientId}`);
  } else {
    throw new Error('Dhan Client ID is missing. Set DHAN_CLIENT_ID or provide a valid Dhan JWT token.');
  }
}

// Validate MARKET_EXPIRY_DATE — required, must be a valid future date
if (!config.marketExpiryDate) {
  throw new Error(
    '[Config] MARKET_EXPIRY_DATE is required. Set it in .env (e.g. MARKET_EXPIRY_DATE=2026-08-28).'
  );
}

// Check if the provided expiry date has already passed (compare date-only in IST)
const expiryMs = new Date(config.marketExpiryDate + 'T15:30:00+05:30').getTime();
if (Date.now() > expiryMs) {
  throw new Error(
    `[Config] MARKET_EXPIRY_DATE "${config.marketExpiryDate}" has already expired. ` +
    `Please update it in .env to the next expiry date.`
  );
}

console.log(`[Config] Using expiry date from env: ${config.marketExpiryDate}`);

export default config;
