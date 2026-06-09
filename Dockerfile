FROM node:22 AS build
WORKDIR /app
COPY package.json package-lock.json ./
# danfojs-node → @tensorflow/tfjs-node ships prebuilt x86_64 Linux binaries.
# On Apple Silicon, build/run with: docker build --platform linux/amd64 ...
# Enable Rosetta in Docker Desktop (Settings → General) for best performance.
RUN npm ci
COPY . .
RUN npm run build
RUN npm prune --omit=dev

FROM node:22 AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8080
COPY package.json package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/out/server ./out/server
COPY --from=build /app/dist ./dist
COPY resources/db/taxonomy.db ./resources/db/taxonomy.db
EXPOSE 8080
CMD ["node", "out/server/index.js"]
