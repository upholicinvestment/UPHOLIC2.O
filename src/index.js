import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import config from './config.js';
import { connectDB, getDB } from './db.js';
import { startIngestionLoop, checkMarketOpen } from './ingestor.js';

const app = express();

// Set up security & middleware
app.use(helmet());
app.use(cors());
app.use(express.json());

// Expose health check endpoint (essential for Azure deployments)
app.get('/health', async (req, res) => {
  try {
    const db = getDB();
    // Perform simple ping to verify DB connection
    await db.command({ ping: 1 });
    return res.status(200).json({
      status: 'UP',
      database: 'CONNECTED',
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    return res.status(503).json({
      status: 'DOWN',
      database: 'DISCONNECTED',
      error: error.message,
      timestamp: new Date().toISOString(),
    });
  }
});

// Expose detailed status endpoint for scanning loop metadata
app.get('/status', (req, res) => {
  const marketState = checkMarketOpen();
  
  return res.status(200).json({
    timestamp: new Date().toISOString(),
    market: {
      openConfig: config.marketOpenTime,
      closeConfig: config.marketCloseTime,
      timezone: config.marketTimezone,
      currentTime: marketState.time,
      currentWeekday: marketState.weekday,
      isOpen: marketState.isOpen,
      reason: marketState.reason,
    },
    ingestor: global.ingestionStatus || { running: false },
    config: {
      rateLimitSeconds: config.rateLimitSeconds,
      tokensConfigured: config.tokens.length,
      totalSymbols: config.totalSymbols,
    }
  });
});

async function main() {
  try {
    // 1. Connect to MongoDB and set up time-series collection & indexes
    const { client } = await connectDB();

    // 2. Start Express Web Server
    const server = app.listen(config.port, () => {
      console.log(`[Server] Listening on port ${config.port}`);
      console.log(`[Server] Health endpoint: http://localhost:${config.port}/health`);
      console.log(`[Server] Status endpoint: http://localhost:${config.port}/status`);
    });

    // 3. Launch the background ingestion worker loop (un-awaited)
    startIngestionLoop().catch((err) => {
      console.error('[Main] Fatal error occurred in background ingestion loop:', err);
    });

    // 4. Handle graceful shutdown
    const shutdown = async (signal) => {
      console.log(`[Shutdown] Received ${signal}. Starting graceful shutdown...`);
      server.close(() => {
        console.log('[Shutdown] Express server closed.');
      });

      try {
        await client.close();
        console.log('[Shutdown] MongoDB connection closed.');
      } catch (err) {
        console.error('[Shutdown] Error closing MongoDB connection:', err);
      }

      console.log('[Shutdown] Process exiting.');
      process.exit(0);
    };

    process.on('SIGTERM', () => shutdown('SIGTERM'));
    process.on('SIGINT', () => shutdown('SIGINT'));

  } catch (error) {
    console.error('[Main] Failed to start service:', error);
    process.exit(1);
  }
}

main();
