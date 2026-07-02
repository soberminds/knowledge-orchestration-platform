# Docker Desktop 代理配置说明

这份文档记录以后需要通过代理拉 Docker 镜像或构建镜像时的操作。当前如果不使用代理，可以先不配置；只有遇到 Docker Hub、PyTorch 等国外源下载失败时再开启。

## 1. 什么时候需要开代理

通常这些场景建议开代理：

- `docker pull python:3.11-slim-bookworm` 失败
- `docker pull node:20-alpine` 失败
- `docker pull nginx:1.27-alpine` 失败
- 构建时出现 `auth.docker.io/token` 超时
- 构建时出现 `registry-1.docker.io` 连接失败
- 构建时 `download.pytorch.org` 下载 CPU 版 PyTorch 失败

如果只是使用已经存在的本地镜像和容器，一般不需要开代理。

## 2. 当前代理信息

当前本机代理软件是 Nano，本地端口是：

```text
65532
```

优先按 HTTP 代理使用：

```text
http://127.0.0.1:65532
```

如果后续验证发现 HTTP 方式不可用，再尝试 SOCKS5：

```text
socks5://127.0.0.1:65532
```

## 3. 开代理前先验证端口

先打开 Nano，再在 PowerShell 执行：

```powershell
Test-NetConnection 127.0.0.1 -Port 65532
```

看到下面结果才说明本地代理端口可用：

```text
TcpTestSucceeded : True
```

如果是 `False`，Docker Desktop 配了代理也不能用，需要先确认 Nano 已启动、端口是否仍然是 `65532`。

## 4. Docker Desktop 配置方式

打开：

```text
Docker Desktop -> Settings -> Resources -> Proxies
```

### 4.1 Docker Desktop Proxy

这一块控制 Docker Desktop 自己访问外网，主要影响：

- 拉基础镜像
- 登录 Docker Hub
- 推送镜像
- 访问 Docker Hub 授权服务

配置方式：

```text
Proxy mode: Manual configuration
Web Server (HTTP): http://127.0.0.1:65532
Secure Web Server (HTTPS): http://127.0.0.1:65532
Bypass proxy settings: 留空
```

如果 HTTP 方式不通，改成：

```text
Web Server (HTTP): socks5://127.0.0.1:65532
Secure Web Server (HTTPS): socks5://127.0.0.1:65532
Bypass proxy settings: 留空
```

### 4.2 Containers Proxy

这一块控制运行中容器和构建容器访问外网，主要影响 Dockerfile 里的：

- `apt-get install`
- `pip install`
- `download.pytorch.org` 下载 PyTorch

推荐先选：

```text
Same as host proxy
```

如果后续构建时容器内部仍然访问不了国外源，再改成：

```text
Proxy mode: Manual configuration
Web Server (HTTP): http://host.docker.internal:65532
Secure Web Server (HTTPS): http://host.docker.internal:65532
Bypass proxy settings: 留空
```

如果需要 SOCKS5，则填：

```text
Web Server (HTTP): socks5://host.docker.internal:65532
Secure Web Server (HTTPS): socks5://host.docker.internal:65532
Bypass proxy settings: 留空
```

这里不能写 `127.0.0.1`，因为容器里的 `127.0.0.1` 指的是容器自己，不是 Windows 主机。

## 5. 应用配置

填完后点击：

```text
Apply
```

Docker Desktop 可能会重启。等左下角显示：

```text
Engine running
```

再继续操作。

## 6. 验证 Docker 是否真的走代理

先检查 Docker Engine 正常：

```powershell
docker ps
```

再单独拉基础镜像，不要直接 build：

```powershell
docker pull --platform linux/amd64 python:3.11-slim-bookworm
```

继续验证前端基础镜像：

```powershell
docker pull node:20-alpine
docker pull nginx:1.27-alpine
```

这三个都能成功，说明 Docker Desktop 访问 Docker Hub 已经正常。

## 7. 再构建业务镜像

基础镜像拉通后，再回到项目根目录执行：

```powershell
docker compose --progress=plain --env-file .env.prod -f docker-compose.prod.yml build --no-cache backend
```

后端成功后再构建全部：

```powershell
docker compose --progress=plain --env-file .env.prod -f docker-compose.prod.yml build
```

## 8. 如果暂时不用代理

如果 Nano 没开，但 Docker Desktop 仍配置了手动代理，Docker 拉镜像时一般不会自动降级直连，通常会直接失败。

所以不用代理时有两种选择：

### 方案 A：保持代理配置，但每次拉镜像前先开 Nano

适合经常需要拉 Docker Hub 镜像的情况。

操作前先确认：

```powershell
Test-NetConnection 127.0.0.1 -Port 65532
```

### 方案 B：切回 No proxy

适合长期不使用代理的情况。

路径：

```text
Docker Desktop -> Settings -> Resources -> Proxies
```

把 Docker Desktop proxy 改成：

```text
No proxy
```

Containers proxy 也可以改成：

```text
No proxy
```

然后点击 `Apply`。

## 9. 常见错误判断

### 9.1 Docker Hub 授权失败

错误类似：

```text
failed to fetch anonymous token
Get https://auth.docker.io/token timeout
```

说明 Docker Desktop 自己访问 Docker Hub 失败。优先检查 Docker Desktop Proxy。

### 9.2 Docker Engine 没响应

错误类似：

```text
request returned 500 Internal Server Error
_dockerDesktopLinuxEngine/_ping
```

说明 Docker Desktop 引擎卡住，不是项目配置问题。处理：

```powershell
wsl --shutdown
```

然后重启 Docker Desktop。

### 9.3 容器内部下载失败

如果基础镜像能拉，但构建中 `pip install` 或 `download.pytorch.org` 失败，优先检查 Containers proxy。

## 10. 推荐默认策略

当前项目推荐策略：

```text
Docker Hub 基础镜像：需要时走 Docker Desktop 代理
Debian apt：继续使用阿里云源
普通 Python 依赖：继续使用清华 PyPI 源
CPU PyTorch：优先用 Docker 代理访问 download.pytorch.org
```

核心原则：

```text
不要一会儿开代理、一会儿关代理反复构建。
构建前先确定网络路径，然后再执行 docker pull / docker compose build。
```