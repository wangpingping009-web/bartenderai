# 前端镜像（M6 完整 Docker 栈）：Node 构建 → Nginx 托管
# 构建: docker build -f frontend/Dockerfile -t bartenderai-frontend frontend
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
