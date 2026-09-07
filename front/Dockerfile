# ---- dev: what docker-compose.yml actually runs locally ---------------------
# Bind-mounts the source tree (see docker-compose.yml's `volumes:` for
# frontend) and serves through Vite's own dev server with HMR.
FROM node:20-alpine AS dev

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]

# ---- build: compiles the static SPA bundle ----------------------------------
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

# Vite inlines import.meta.env.* into the bundle at build time, not at
# container start — so unlike the dev image (where this is a plain runtime
# env var), a production build needs it as a build ARG.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

# ---- production: static bundle served by nginx, non-root -------------------
FROM nginxinc/nginx-unprivileged:1.27-alpine AS production

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
