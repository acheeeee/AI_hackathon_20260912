FROM node:24-alpine AS build

WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
# The current lockfile contains an oxlint/eslint-plugin-oxlint peer-version
# mismatch. It does not affect the Vite production bundle, but a clean npm
# install rejects it unless legacy peer resolution is requested. Keep the
# repository package files untouched while making the container build explicit.
RUN npm ci --legacy-peer-deps

COPY frontend/ ./
RUN npm run build

FROM nginx:1.29-alpine

ARG APP_VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="AI Hackathon demo frontend" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

COPY deployment/nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /build/frontend/dist/ /usr/share/nginx/html/

RUN mkdir -p \
      /tmp/nginx/client_temp \
      /tmp/nginx/proxy_temp \
      /tmp/nginx/fastcgi_temp \
      /tmp/nginx/uwsgi_temp \
      /tmp/nginx/scgi_temp \
    && chown -R nginx:nginx /tmp/nginx /usr/share/nginx/html

USER nginx

EXPOSE 8080

ENTRYPOINT ["/bin/sh", "-c", "mkdir -p /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp && exec nginx -g 'daemon off;'"]
