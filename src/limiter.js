/**
 * Staggers calls across N Dhan access tokens so that:
 *   - Each individual token is never used more than once per rateLimitSeconds (e.g. 3s).
 *   - The overall effective throughput is N requests per rateLimitSeconds (e.g. ~1 request/sec for 3 tokens).
 */
export class TokenRateLimiter {
  constructor(tokens, rateLimitSeconds = 3.0) {
    if (!tokens || tokens.length === 0) {
      throw new Error('TokenRateLimiter requires at least one token.');
    }
    this.tokens = tokens;
    this.minIntervalMs = rateLimitSeconds * 1000;
    
    // Track the last time (timestamp in ms) each token was used
    this.lastUsed = {};
    for (const token of tokens) {
      this.lastUsed[token] = 0;
    }
    
    this.nextTokenIndex = 0;
  }

  /**
   * Blocks (via Promise/setTimeout) until the next token is legally usable,
   * then updates its timestamp and returns it.
   */
  async acquire() {
    const token = this.tokens[this.nextTokenIndex];
    // Rotate to the next token index for the next call
    this.nextTokenIndex = (this.nextTokenIndex + 1) % this.tokens.length;

    const now = Date.now();
    const elapsed = now - this.lastUsed[token];
    const waitTime = this.minIntervalMs - elapsed;

    if (waitTime > 0) {
      await new Promise((resolve) => setTimeout(resolve, waitTime));
    }

    this.lastUsed[token] = Date.now();
    return token;
  }
}
