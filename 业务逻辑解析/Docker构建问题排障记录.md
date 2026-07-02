# Docker 构建问题排障记录

这份文档记录本项目在前后端 Docker 镜像构建过程中实际遇到的问题、原因、解决方式和验证命令。后续本地打包或服务器部署时，优先按这里排查。

当前已成功构建的镜像：

```text
kop-backend:latest   约 3.15GB
kop-frontend:latest  约 78.4MB
```

当前推荐构建命令：

```powershell
docker compose --progress=plain --env-file .env.prod -f docker-compose.prod.yml build --no-cache backend
```

构建全部镜像：

```powershell
docker compose --progress=plain --env-file .env.prod -f docker-compose.prod.yml build
```

## 1. Docker Hub 拉基础镜像失败

### 现象

构建刚开始就失败，日志类似：

```text
failed to fetch anonymous token
Get "https://auth.docker.io/token?...": timeout
load metadata for docker.io/library/python:3.11-slim-bookworm
load metadata for docker.io/library/node:20-alpine
load metadata for docker.io/library/nginx:1.27-alpine
```

也可能出现 IPv6 超时：

```text
dial tcp [IPv6地址]:443: connectex timeout
```

### 原因

Dockerfile 的 `FROM` 基础镜像来自 Docker Hub。真正访问 Docker Hub 的是 Docker Desktop Linux Engine，不是浏览器，也不一定跟随普通翻墙软件。

如果 Docker Desktop 没有正确走代理，就会在拉取：

```text
python:3.11-slim-bookworm
node:20-alpine
nginx:1.27-alpine
```

时失败。

### 解决

先不要直接 build，先单独拉基础镜像：

```powershell
docker pull --platform linux/amd64 python:3.11-slim-bookworm
docker pull node:20-alpine
docker pull nginx:1.27-alpine
```

如果失败，需要配置 Docker Desktop 代理。当前 Nano 端口是：

```text
65532
```

Docker Desktop 代理配置见：

```text
业务逻辑解析/Docker代理配置说明.md
```

核心配置：

```text
Docker Desktop -> Settings -> Resources -> Proxies
Docker Desktop proxy: Manual configuration
HTTP:  http://127.0.0.1:65532
HTTPS: http://127.0.0.1:65532
```

如果暂时不用代理，切回：

```text
No proxy
```

### 验证

```powershell
docker ps
docker pull --platform linux/amd64 python:3.11-slim-bookworm
```

`docker pull` 成功后再执行 compose build。

## 2. Docker Desktop Engine 500 或 docker ps 卡住

### 现象

```text
request returned 500 Internal Server Error
http://%2F%2F.%2Fpipe%2FdockerDesktopLinuxEngine/_ping
```

或者：

```powershell
docker ps
```

长时间无响应，最后超时。

### 原因

Docker Desktop 的 Linux Engine 卡住或崩溃。这个阶段构建还没真正开始，不是项目配置、Dockerfile 或 `.env.prod` 的问题。

### 解决

先执行：

```powershell
wsl --shutdown
```

然后退出并重新打开 Docker Desktop。

如果还不恢复，再执行：

```powershell
Stop-Process -Name "Docker Desktop" -Force
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
```

不要点 Docker Desktop 的 `Reset to factory defaults`，否则可能清掉本地镜像、容器和 volume。

### 验证

```powershell
docker version
docker ps
```

能正常输出后再继续构建。

## 3. pip 安装依赖时 hash mismatch

### 现象

后端构建时 `pip install -r requirements.txt` 失败：

```text
ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE
unknown package:
    Expected sha256 ...
         Got        ...
```

实际出现过的包包括：

```text
yarl-1.24.2
```

并且每次重试 `Expected/Got` 可能变化。

### 原因

`requirements.txt` 本身没有写死 hash。这个问题更像是 PyPI/CDN/代理链路不稳定，下载到的 wheel 文件和索引声明的 sha256 对不上。pip 为了安全中断安装。

### 解决

后端 Dockerfile 已支持可配置 PyPI 源，并增加重试和超时。当前 `.env.prod` / `.env.example` 使用：

```env
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
PIP_TRUSTED_HOST=
```

如果以后网络稳定，也可以改回官方源：

```env
PIP_INDEX_URL=https://pypi.org/simple
PIP_TRUSTED_HOST=
```

然后重新构建后端：

```powershell
docker compose --progress=plain --env-file .env.prod -f docker-compose.prod.yml build --no-cache backend
```

### 说明

清华 PyPI 镜像不是 PyPI 官方域名，但国内构建稳定性更好。严格生产环境建议后续使用内部制品库或锁定依赖版本。

## 4. apt 下载 LibreOffice / 中文字体时 EOF

### 现象

后端构建卡在 Debian 系统包下载，日志类似：

```text
apt-get install
libreoffice-writer-nogui
libreoffice-calc-nogui
libreoffice-impress-nogui
fonts-noto-cjk
failed to solve: Unavailable: error reading from server: EOF
```

### 原因

后端镜像需要安装 LibreOffice 和中文字体，用于 Office 转 PDF、文档预览和旧版 Office 解析兜底。这些包体积较大，使用默认 `deb.debian.org` 时国内网络容易中断。

### 解决

Dockerfile 已做如下调整：

```dockerfile
FROM python:3.11-slim-bookworm
```

固定 Debian `bookworm`，避免 `python:3.11-slim` 漂移到新的 Debian 版本。

`.env.prod` 中使用阿里云 Debian 源：

```env
APT_MIRROR=http://mirrors.aliyun.com/debian
APT_SECURITY_MIRROR=http://mirrors.aliyun.com/debian-security
```

Dockerfile 中 `apt-get` 已增加：

```text
Acquire::Retries=8
Acquire::http::Timeout=120
Acquire::https::Timeout=120
```

### 如果仍然卡在 fonts-noto-cjk

`fonts-noto-cjk` 字体完整度好，但包比较大。必要时可临时换成更轻的字体：

```dockerfile
fonts-wqy-zenhei \
fonts-wqy-microhei
```

代价是字体完整度不如 `fonts-noto-cjk`。

## 5. torch 默认拉 CUDA / NVIDIA 大包

### 现象

后端构建时 `pip install` 出现大量 GPU/CUDA 依赖：

```text
nvidia-cublas
nvidia-cudnn
nvidia-cusolver
nvidia-nccl
nvidia-nvtx
cuda-toolkit
cuda-bindings
triton
```

安装时间很长，镜像体积明显膨胀。

### 原因

`sentence-transformers` 依赖 `torch`。Linux 下如果不限制，pip 可能解析到带 CUDA 依赖的 PyTorch 版本。生产 CPU 服务器不需要这些 GPU 运行时。

### 解决

后端 Dockerfile 已在安装 `requirements.txt` 前预安装 CPU 版 PyTorch，并用 constraints 锁住：

```env
TORCH_VERSION=2.3.1+cpu
TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
```

对应 Dockerfile 逻辑：

```dockerfile
pip install --extra-index-url "$TORCH_INDEX_URL" -c /tmp/torch-cpu-constraints.txt "torch==$TORCH_VERSION"
pip install --extra-index-url "$TORCH_INDEX_URL" -c /tmp/torch-cpu-constraints.txt -r requirements.txt
```

### 验证

```powershell
docker run --rm kop-backend:latest python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

预期：

```text
2.3.1+cpu
False
```

如果看到 `cuda` 或 `True`，说明 CPU 版没有锁住。

## 6. .env 行尾注释导致 Compose 读取错误

### 现象

某些空值配置本来应该为空，但 Docker Compose 可能把行尾注释也当成值，例如：

```env
VITE_API_BASE_URL= # 前端构建时使用的 API 地址
```

可能被解析成：

```text
"# 前端构建时使用的 API 地址"
```

### 原因

Compose 的 env 文件解析对行尾注释容易产生歧义，尤其是空值后面跟注释时。

### 解决

不要写行尾注释。统一改成注释放上一行：

```env
# 前端构建时使用的 API 地址；生产同源反向代理时留空
VITE_API_BASE_URL=
```

当前 `.env`、`.env.example`、`.env.prod`、`.env.prod.example` 已按这种方式整理。

### 验证

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml config
```

注意：这个命令会打印部分环境变量，生产环境不要随便把完整输出发给别人。

## 7. --progress 参数位置提示

### 现象

```text
--progress is a global compose flag, better use `docker compose --progress xx build ...`
```

### 原因

`--progress` 是 `docker compose` 的全局参数，应该放在 `compose` 后面，而不是 `build` 后面。

### 正确命令

```powershell
docker compose --progress=plain --env-file .env.prod -f docker-compose.prod.yml build --no-cache backend
```

不是：

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml build --no-cache --progress=plain backend
```

这个只是提示，不是构建失败原因。

## 8. 前端镜像构建相关问题

### 当前情况

前端镜像已成功构建：

```text
kop-frontend:latest  约 78.4MB
```

前端 Dockerfile 使用：

```text
node:20-alpine
nginx:1.27-alpine
```

前端主要风险不是业务构建，而是基础镜像拉取失败。处理方式同第 1 节，先单独拉镜像：

```powershell
docker pull node:20-alpine
docker pull nginx:1.27-alpine
```

### 前端 API 地址说明

生产同源部署时：

```env
VITE_API_BASE_URL=
```

前端 Nginx 会代理：

```text
/api -> kop-backend:8000
```

如果修改了 `VITE_API_BASE_URL`，必须重新构建前端，因为 Vite 环境变量是构建时写入静态文件的：

```powershell
docker compose --progress=plain --env-file .env.prod -f docker-compose.prod.yml build --no-cache frontend
```

## 9. 构建成功后的验证命令

检查镜像：

```powershell
docker images | Select-String "kop-"
```

验证后端 Python 依赖：

```powershell
docker run --rm kop-backend:latest python -c "import fastapi, chromadb, sentence_transformers; print('python deps ok')"
```

验证 PyTorch CPU：

```powershell
docker run --rm kop-backend:latest python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

验证 LibreOffice：

```powershell
docker run --rm kop-backend:latest soffice --version
```

导出镜像：

```powershell
docker save kop-backend:latest kop-frontend:latest -o kop-images.tar
```

## 10. 当前 Docker 构建相关配置清单

`.env.prod` / `.env.example` 中与构建稳定性相关的配置：

```env
APT_MIRROR=http://mirrors.aliyun.com/debian
APT_SECURITY_MIRROR=http://mirrors.aliyun.com/debian-security
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
PIP_TRUSTED_HOST=
TORCH_VERSION=2.3.1+cpu
TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
```

`docker-compose.prod.yml` 中后端 build args 会把这些变量传给 Dockerfile：

```yaml
args:
  APT_MIRROR: ${APT_MIRROR:-http://mirrors.aliyun.com/debian}
  APT_SECURITY_MIRROR: ${APT_SECURITY_MIRROR:-http://mirrors.aliyun.com/debian-security}
  PIP_INDEX_URL: ${PIP_INDEX_URL:-https://pypi.org/simple}
  PIP_TRUSTED_HOST: ${PIP_TRUSTED_HOST:-}
  TORCH_VERSION: ${TORCH_VERSION:-2.3.1+cpu}
  TORCH_INDEX_URL: ${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}
```

## 11. 推荐排障顺序

后续如果 Docker 构建失败，按这个顺序排查：

1. `docker ps` 是否正常，确认 Docker Desktop Engine 没卡住。
2. 单独 `docker pull` 基础镜像，确认 Docker Hub 链路正常。
3. 后端构建失败时，看失败位置是 `apt-get`、`pip install`，还是 `torch`。
4. `apt-get` 失败，检查 `APT_MIRROR`。
5. `pip install` 普通包失败，检查 `PIP_INDEX_URL`。
6. 出现 `nvidia-*` / `cuda-*`，检查 `TORCH_VERSION=2.3.1+cpu` 是否生效。
7. 构建成功后运行第 9 节验证命令。

核心原则：

```text
先拉通基础镜像，再构建业务镜像。
先判断失败发生在哪一层，再改对应配置。
不要反复无目的地切换代理和镜像源。
```