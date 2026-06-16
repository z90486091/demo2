FROM node:alpine
WORKDIR /app
COPY proxy.js .
RUN pnpm init -y && pnpm add https-proxy-agent node-fetch
EXPOSE 7860
CMD ["node", "proxy.js"]
