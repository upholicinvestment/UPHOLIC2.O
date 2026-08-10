import assert from 'assert';
import { connectDB, getDB, writeSnapshot, getPreviousSnapshot, insertAlert } from '../src/db.js';
import config from '../src/config.js';
import { TokenRateLimiter } from '../src/limiter.js';
import { checkMarketOpen } from '../src/ingestor.js';
import {
  iv4NormalCdf,
  iv4BlackScholesPrice,
  solveIv4,
  computeIv4FromStrikeChain,
  mapResponseToDocument
} from '../src/ingestor.js';

// Mock Dhan response matching the REAL Dhan API structure:
const mockDhanData = {
  last_price: 1642.50,
  strikes: [
    {
      strike: 1600,
      ce: {
        last_price: 52.3,
        oi: 100000,
        volume: 4210,
        greeks: { implied_volatility: 18.2, gamma: 0.002, delta: 0.65, theta: -0.5, vega: 0.8 }
      },
      pe: {
        last_price: 8.1,
        oi: 80000,
        volume: 3011,
        greeks: { implied_volatility: 21.5, gamma: 0.001, delta: -0.35, theta: -0.3, vega: 0.6 }
      }
    },
    {
      strike: 1650,
      ce: {
        last_price: 21.4,
        oi: 50000,
        volume: 1200,
        greeks: { implied_volatility: 17.5, gamma: 0.003, delta: 0.50, theta: -0.4, vega: 0.7 }
      },
      pe: {
        last_price: 27.5,
        oi: 60000,
        volume: 1800,
        greeks: { implied_volatility: 19.8, gamma: 0.002, delta: -0.45, theta: -0.35, vega: 0.65 }
      }
    }
  ]
};

async function runTests() {
  console.log('=== STARTING UNIT & INTEGRATION TESTS (INDEPENDENT PHASE 2) ===');

  // Test 1: Cumulative Normal Distribution (Normal CDF)
  console.log('\n[Test 1] Validating Cumulative Normal Distribution (Normal CDF)...');
  const cdfZero = iv4NormalCdf(0);
  console.log(`CDF(0) = ${cdfZero} (Expected: ~0.5)`);
  assert.ok(Math.abs(cdfZero - 0.5) < 0.001);

  const cdfPos = iv4NormalCdf(1.96);
  console.log(`CDF(1.96) = ${cdfPos} (Expected: ~0.975)`);
  assert.ok(Math.abs(cdfPos - 0.975) < 0.005);
  console.log('✔ Normal CDF test passed.');

  // Test 2: Black-Scholes Formula Pricing
  console.log('\n[Test 2] Validating Black-Scholes Formula Pricing...');
  const priceCall = iv4BlackScholesPrice({
    side: 'ce',
    spot: 100,
    strike: 100,
    timeYears: 1,
    rate: 0.05,
    dividendYield: 0,
    sigma: 0.20
  });
  console.log(`BS Call Price: ₹${priceCall.toFixed(4)} (Expected: ~10.45)`);
  assert.ok(Math.abs(priceCall - 10.4506) < 0.01);
  console.log('✔ Black-Scholes pricing test passed.');

  // Test 3: Numerical Implied Volatility Solver (solveIv4)
  console.log('\n[Test 3] Validating Numerical Implied Volatility Solver (solveIv4)...');
  const solvedCallIv = solveIv4({
    side: 'ce',
    optionPrice: 10.45,
    spot: 100,
    strike: 100,
    timeYears: 1,
    rate: 0.05,
    dividendYield: 0
  });
  const solvedCallIvPct = solvedCallIv * 100;
  console.log(`Solved Call IV: ${solvedCallIvPct.toFixed(2)}% (Expected: ~20.00%)`);
  assert.ok(Math.abs(solvedCallIvPct - 20.00) < 0.1);
  console.log('✔ Numerical IV solver test passed.');

  // Test 4: Weighted IV4 Calculations
  console.log('\n[Test 4] Validating Weighted IV4 calculations from strikes chain...');
  const strikesInput = [
    {
      strike: 1600,
      ce: { oi: 100000, implied_volatility: 18.2, greeks: { implied_volatility: 18.2 } },
      pe: { oi: 80000, implied_volatility: 21.5, greeks: { implied_volatility: 21.5 } }
    },
    {
      strike: 1650,
      ce: { oi: 50000, implied_volatility: 17.5, greeks: { implied_volatility: 17.5 } },
      pe: { oi: 60000, implied_volatility: 19.8, greeks: { implied_volatility: 19.8 } }
    }
  ];

  const metrics = computeIv4FromStrikeChain({
    strikes: strikesInput,
    spot: 1642.50,
    expiry: '2026-08-25',
    observationTime: new Date()
  });

  console.log('Computed Weighted Metrics:', JSON.stringify(metrics, null, 2));
  assert.ok(Math.abs(metrics.ce_iv_oi_weighted - 17.9667) < 0.01);
  assert.ok(Math.abs(metrics.pe_iv_oi_weighted - 20.7714) < 0.01);
  assert.ok(Math.abs(metrics.iv_skew - 2.8047) < 0.01);
  assert.ok(Math.abs(metrics.iv_ratio - 1.1561) < 0.01);
  assert.ok(Math.abs(metrics.iv4 - 19.3207) < 0.01);
  console.log('✔ Weighted IV4 calculations test passed.');

  // Test 5: Response Mapping & Previous Snapshot Merge
  console.log('\n[Test 5] Validating Option Chain mapping with previous snapshots...');
  const symbolObj = { symbol: 'HDFC', security_id: '1330', exchange_segment: 'NSE_EQ' };
  
  const previousSnapshot = {
    symbol: 'HDFC',
    spot_price: 1640.0,
    iv4: 19.10,
    Flip_strike: 1600,
    options: [
      { strike: 1600, type: 'CE', ltp: 50.0, oi: 95000, volume: 4000, greeks: { implied_volatility: 18.0 } },
      { strike: 1600, type: 'PE', ltp: 8.5, oi: 78000, volume: 2900, greeks: { implied_volatility: 21.0 } }
    ]
  };

  const now = new Date();
  const doc = mapResponseToDocument(symbolObj, mockDhanData, previousSnapshot, '2026-08-25', now);

  console.log('Mapped Document Summary:');
  console.log(`Symbol: ${doc.symbol}, Spot: ${doc.spot_price}, IV4: ${doc.iv4}, Skew: ${doc.iv_skew}, Ratio: ${doc.iv_ratio}, Flip: ${doc.Flip_strike}`);
  
  // Verify flat options mapped
  assert.strictEqual(doc.options.length, 4); // 2 strikes, each has CE and PE
  
  const ce1600 = doc.options.find(o => o.strike === 1600 && o.type === 'CE');
  assert.ok(ce1600);
  assert.strictEqual(ce1600.ltp, 52.3);
  assert.strictEqual(ce1600.oi, 100000);
  
  // Verify previous mapped
  assert.strictEqual(ce1600.previous_close_price, 50.0);
  assert.strictEqual(ce1600.previous_oi, 95000);
  assert.strictEqual(ce1600.previous_volume, 4000);

  // Verify change calculations
  assert.ok(doc.iv4_change_5m > 0);
  console.log(`iv4_change_5m = ${doc.iv4_change_5m}`);

  // OTM checks: Call OTM threshold is 1642.50 * 1.015 = 1667.13. So CE 1650 is NOT OTM.
  // Put OTM threshold is 1642.50 * 0.985 = 1617.86. So PE 1600 is OTM.
  // PE 1600: oi_change = 80000 - 78000 = 2000. premium_change = 8.1 - 8.5 = -0.4.
  // put_net_flow = 2000 * -0.4 = -800
  assert.strictEqual(doc.put_net_flow, -800);
  console.log('✔ Response mapping and comparisons test passed.');

  // Test 6: Database integration setup
  console.log('\n[Test 6] Validating Database connection and indexes...');
  try {
    const { db } = await connectDB();
    console.log('Successfully connected to DB');

    const snapshotsCol = db.collection('snapshots');
    const latestCol = db.collection('latest_snapshot');
    const alertsCol = db.collection('alerts');

    // Index verification
    const latestIndexes = await latestCol.listIndexes().toArray();
    const uniqueIndexExists = latestIndexes.some(idx => idx.key.symbol === 1 && idx.unique);
    assert.ok(uniqueIndexExists, 'latest_snapshot should have a unique index on symbol');
    console.log('✔ Unique index on symbol verified.');

    // Save test documents
    console.log('Writing snapshot document...');
    await writeSnapshot(doc);

    // Verify snapshot written
    const savedLatest = await latestCol.findOne({ symbol: 'HDFC' });
    assert.ok(savedLatest);
    assert.strictEqual(savedLatest.spot_price, 1642.50);

    const savedCandle = await db.collection('optstk_history_1m').findOne({ symbol: 'HDFC' });
    assert.ok(savedCandle);
    assert.strictEqual(savedCandle.close, 1642.50);
    console.log('✔ Live 1-minute candle insertion verified.');

    // Test alert inserts
    console.log('Writing mock alert...');
    const alertDoc = {
      timestamp: now,
      ts_ist: doc.ts_ist,
      symbol: 'HDFC',
      direction: 'BULLISH',
      spot: 1645.0,
      details: 'Mock bullish crossing breakout'
    };
    await insertAlert(alertDoc);

    const savedAlert = await alertsCol.findOne({ symbol: 'HDFC' });
    assert.ok(savedAlert);
    assert.strictEqual(savedAlert.direction, 'BULLISH');
    console.log('✔ Alert insertion verified.');

    // Cleanup mock data
    console.log('Cleaning up mock data...');
    await snapshotsCol.deleteMany({ symbol: 'HDFC' });
    await latestCol.deleteOne({ symbol: 'HDFC' });
    await alertsCol.deleteMany({ symbol: 'HDFC' });
    await db.collection('optstk_history_1m').deleteMany({ symbol: 'HDFC' });
    console.log('✔ Cleanup complete.');

    console.log('✔ Database integration test passed.');
  } catch (err) {
    console.error('❌ Database integration test failed:', err);
    throw err;
  }

  console.log('\n=== ALL TESTS PASSED SUCCESSFULLY! ===');
  process.exit(0);
}

runTests().catch((e) => {
  console.error(e);
  process.exit(1);
});
