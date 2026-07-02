# 生产部署与 Docker 容器化说明

## 1. 当前服务器部署结论

你现在的情况是：

- 中间件已经单独部署在服务器上。
- 中间件是从 `C:\Users\30372\Desktop\docker-middleware` 迁移过去的。
- 业务服务和中间件在同一台服务器上。
- 当前只有一台服务器。

所以生产部署应该拆成两套 compose：

```text
中间件 compose：只负责 MySQL / Redis / ONLYOFFICE / 中间件 Nginx
业务 compose：只负责 backend / frontend
```

业务 compose 不应该再启动一套 MySQL、Redis、ONLYOFFICE。

原因：

- 避免端口冲突，例如 `3306`、`6379`、`8088` 已经被中间件占用。
- 避免数据分裂，例如一个 MySQL 在中间件 compose，一个 MySQL 在业务 compose。
- 避免后续维护两套中间件，排错会很乱。
- 中间件可以长期稳定运行，业务服务可以独立更新和重启。

## 2. 服务器当前中间件形态

从当前 `docker ps` 看，中间件容器是：

```text
middleware-mysql        mysql:8.0
middleware-redis        redis:latest
middleware-onlyoffice   onlyoffice/documentserver:latest
middleware-nginx        nginx:latest
```

端口映射是：

```text
MySQL       3306 -> 3306
Redis       6379 -> 6379
ONLYOFFICE  8088 -> 80
Nginx       8080 -> 80
Nginx       8443 -> 443
```

中间件所在 Docker 网络是：

```text
shared-middleware_default
```

因此业务后端只需要加入这个网络，就可以用容器名访问中间件：

```text
MYSQL_HOST=middleware-mysql
REDIS_HOST=middleware-redis
ONLYOFFICE_DOCUMENT_SERVER_INTERNAL_URL=http://middleware-onlyoffice
```

## 3. 业务 compose 现在负责什么

文件位置：`docker-compose.prod.yml`

现在只包含两个服务：

```text
kop-backend
kop-frontend
```

`kop-backend` 加入两个网络：

```text
kop_app
shared-middleware_default
```

用途：

- `kop_app`：业务前后端内部通信。
- `shared-middleware_default`：后端访问已有中间件。

`kop-frontend` 只加入：

```text
kop_app
```

用途：

- 前端 Nginx 通过 `http://backend:8000` 代理 `/api`。

## 4. 为什么 backend 要加入两个网络

业务前端访问后端：

```text
kop-frontend -> http://backend:8000
```

后端访问中间件：

```text
kop-backend -> middleware-mysql:3306
kop-backend -> middleware-redis:6379
kop-backend -> http://middleware-onlyoffice
```

所以 backend 需要同时在业务网络和中间件网络里。

frontend 不需要访问 MySQL、Redis、ONLYOFFICE，所以 frontend 不需要加入中间件网络。

## 5. 生产环境变量怎么填

模板文件：`.env.prod.example`

服务器部署时复制：

```bash
cp .env.prod.example .env.prod
```

然后编辑：

```bash
nano .env.prod
```

### 5.1 中间件连接配置

默认按你当前服务器上的容器名填写：

```text
MIDDLEWARE_DOCKER_NETWORK=shared-middleware_default
MYSQL_HOST=middleware-mysql
MYSQL_PORT=3306
REDIS_HOST=middleware-redis
REDIS_PORT=6379
ONLYOFFICE_DOCUMENT_SERVER_INTERNAL_URL=http://middleware-onlyoffice
```

如果服务器上的中间件 compose 改过项目名或容器名，只需要改这里。

### 5.2 MySQL 配置

如果你的中间件 MySQL 仍然使用本地开发那套 root 密码，可以先这样：

```text
MYSQL_DATABASE=KOP
MYSQL_USER=root
MYSQL_PASSWORD=root123
```

更推荐后续单独建一个应用账号，例如：

```text
MYSQL_DATABASE=KOP
MYSQL_USER=kop_app
MYSQL_PASSWORD=你的强密码
```

注意：

- `sql/KOP_v1_init.sql` 只负责初始化库表。
- 现在业务 compose 不再创建 MySQL 容器。
- 数据库初始化需要在中间件 MySQL 里执行。
- 如果中间件 MySQL 已经有 `KOP` 数据库和表，就不要重复从零初始化。

### 5.3 Redis 配置

如果中间件 Redis 没有密码：

```text
REDIS_PASSWORD=
```

如果 Redis 设置了密码，就填真实密码。

### 5.4 ONLYOFFICE 配置

浏览器访问 ONLYOFFICE 使用公网地址：

```text
ONLYOFFICE_DOCUMENT_SERVER_URL=http://服务器IP:8088
```

后端容器访问 ONLYOFFICE 使用内部地址：

```text
ONLYOFFICE_DOCUMENT_SERVER_INTERNAL_URL=http://middleware-onlyoffice
```

`ONLYOFFICE_JWT_SECRET` 必须和你现有 `middleware-onlyoffice` 容器里的 `JWT_SECRET` 一致。

否则会出现：

```text
ONLYOFFICE API script 能加载，但保存、命令服务或 JWT 校验异常
```

### 5.5 PUBLIC_BACKEND_URL 配置

因为 `kop-backend` 和 `middleware-onlyoffice` 在同一个中间件网络里，所以 ONLYOFFICE 下载文件和回调后端可以用：

```text
PUBLIC_BACKEND_URL=http://kop-backend:8000
```

这个地址不是给浏览器看的，是给 ONLYOFFICE 容器看的。

浏览器访问系统仍然是：

```text
http://服务器IP
```

或者后续域名：

```text
https://你的域名
```

## 6. 端口建议

当前中间件已经占用：

```text
3306
6379
8088
8080
8443
```

业务 compose 默认占用：

```text
80
```

后端 `8000` 默认只绑定服务器本机：

```text
127.0.0.1:8000
```

也就是说公网只需要访问前端端口。

如果服务器上 `80` 已经被占用，可以改 `.env.prod`：

```text
FRONTEND_HTTP_PORT=8090
```

然后访问：

```text
http://服务器IP:8090
```

## 7. 部署命令

进入业务项目目录：

```bash
cd /opt/knowledge-orchestration-platform
```

创建生产配置：

```bash
cp .env.prod.example .env.prod
nano .env.prod
```

启动业务服务：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

查看业务服务：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

查看后端日志：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f backend
```

查看前端日志：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f frontend
```

## 8. 部署前必须确认

### 8.1 中间件网络存在

业务 compose 依赖外部网络：

```text
shared-middleware_default
```

服务器上可以检查：

```bash
docker network ls
```

如果实际网络名不同，修改 `.env.prod`：

```text
MIDDLEWARE_DOCKER_NETWORK=实际网络名
```

### 8.2 中间件容器名正确

服务器上检查：

```bash
docker ps
```

确保存在：

```text
middleware-mysql
middleware-redis
middleware-onlyoffice
```

如果容器名不同，修改：

```text
MYSQL_HOST=实际 MySQL 容器名
REDIS_HOST=实际 Redis 容器名
ONLYOFFICE_DOCUMENT_SERVER_INTERNAL_URL=http://实际 ONLYOFFICE 容器名
```

### 8.3 MySQL 已经初始化 KOP

业务后端启动时不会自动创建数据库表。

如果中间件 MySQL 还没有 `KOP` 库，需要执行：

```bash
docker exec -i middleware-mysql mysql -uroot -p你的密码 < sql/KOP_v1_init.sql
```

如果已经有数据，执行前一定先备份。

### 8.4 ONLYOFFICE JWT 要一致

检查中间件 ONLYOFFICE 的 JWT：

```bash
docker inspect middleware-onlyoffice
```

找到 `JWT_SECRET`，然后填到业务 `.env.prod`：

```text
ONLYOFFICE_JWT_SECRET=同一个密钥
```

## 9. 数据保存在哪里

业务 compose 只保存应用自己的运行数据：

```text
app_data
```

包含：

- 用户上传文档。
- Chroma 向量库。
- 预览 PDF。

MySQL、Redis、ONLYOFFICE 的数据继续由中间件 compose 管理。

这就是拆分后的边界：

```text
业务数据文件 -> 业务 compose 的 app_data
结构化数据   -> 中间件 MySQL
缓存 / session -> 中间件 Redis
Office 服务数据 -> 中间件 ONLYOFFICE
```

## 10. 本地 data 不会被打进镜像

当前后端 `Dockerfile` 只会在镜像里创建空目录：

```text
/app/data/user_docs
/app/data/chroma_db
/app/data/preview_pdf
```

不会把你本机开发环境里的 `data/user_docs`、`data/chroma_db`、`data/preview_pdf` 打包进去。

原因：

- 本地测试文档不应该进入生产镜像。
- Chroma 数据可能很大，放进镜像会导致构建非常慢。
- 生产文件数据应该通过 `app_data` volume 持久化。
- 镜像负责运行代码，volume 负责保存数据。

## 11. 后续更新业务代码

更新业务代码后：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

只重启后端：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build backend
```

只重启前端：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build frontend
```

中间件不需要跟着重启。

