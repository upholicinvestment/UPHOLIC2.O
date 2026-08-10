/**
 * GlobalRateLimiter — enforces a minimum wall-clock gap between ANY two requests.
 *
 * All Dhan tokens used here share the same account (dhanClientId), so Dhan
 * rate-limits per account, NOT per token. Rotating tokens provides zero benefit.
 * This limiter uses one primary token and enforces a single global delay so no
 * two requests ever fire closer together than minGapMs milliseconds.
 *
 * With DHAN_RATE_LIMIT_SECONDS=1.1 → max ~54 req/min, well under Dhan's limit.
 * 208 symbols × 1.1s = ~229s per cycle (~3.8 minutes).
 */
export class TokenRateLimiter {
  constructor(tokens, rateLimitSeconds = 1.1) {
    if (!tokens || tokens.length === 0) {
      throw new Error('TokenRateLimiter requires at least one token.');
    }
    // Use only the first token — all tokens share the same account rate limit
    this.token = tokens[0];
    this.minGapMs = rateLimitSeconds * 1000;
    this.lastRequestAt = 0; // epoch → first request fires immediately
  }

  /**
   * Waits until minGapMs has elapsed since the last request, then returns the token.
   */
  async acquire() {
    const now = Date.now();
    const elapsed = now - this.lastRequestAt;
    const wait = this.minGapMs - elapsed;

    if (wait > 0) {
      await new Promise((resolve) => setTimeout(resolve, wait));
    }

    this.lastRequestAt = Date.now();
    return this.token;
  }
}

