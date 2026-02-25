# Build static assets
FROM node:18-alpine AS builder
WORKDIR /app

COPY package*.json ./
RUN npm ci --include=dev

COPY . .

# Allow API base override at build time for static bundle
ARG VITE_API_BASE=http://localhost:8000/api/v1
ENV VITE_API_BASE=${VITE_API_BASE}

RUN npm run build

# Serve with nginx
FROM 495849799931.dkr.ecr.us-east-1.amazonaws.com/base-nginx:alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
