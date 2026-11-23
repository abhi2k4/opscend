# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
# The /api rewrite target is resolved at build time.
ARG OPSCEND_API_URL=http://api:8000
# 1 = this build fronts the public demo: the landing page says "Try the live demo".
ARG OPSCEND_PUBLIC_DEMO=0
ENV OPSCEND_API_URL=$OPSCEND_API_URL OPSCEND_PUBLIC_DEMO=$OPSCEND_PUBLIC_DEMO NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
