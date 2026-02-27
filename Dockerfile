FROM node:22-alpine

WORKDIR /app

COPY package.json ./
COPY src ./src

ENV HOST=0.0.0.0
ENV PORT=3000
ENV MAX_BODY_BYTES=1048576
ENV CORE_API_BASE_URL=http://core-api:8080
ENV CORE_API_TIMEOUT_MS=10000

EXPOSE 3000

CMD ["node", "src/server.js"]
