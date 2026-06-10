FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install

# We mount or copy the source code in docker-compose.
# For production we'd COPY . . and npm run build
CMD ["npm", "run", "dev", "--", "--host"]
