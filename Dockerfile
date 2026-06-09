FROM node:22 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8080
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/out/server ./out/server
COPY --from=build /app/dist ./dist
COPY resources/db/taxonomy.db ./resources/db/taxonomy.db
EXPOSE 8080
CMD ["node", "out/server/index.js"]
