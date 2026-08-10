FROM node:20-slim

WORKDIR /app

# Copy package configurations
COPY package*.json ./

# Install only production dependencies
RUN npm ci --omit=dev

# Copy project source files
COPY src/ ./src/
COPY symbols.json ./

EXPOSE 3000

ENV NODE_ENV=production

CMD ["node", "src/index.js"]
