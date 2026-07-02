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

## 11. 镜像上传服务器后的启动问题

本节记录 2026-07-02 本地构建镜像、上传服务器、服务器 `docker load` 后启动业务容器时遇到的问题。

### 11.1 上传到 `/opt` 目录 Permission denied

### 现象

Windows PowerShell 执行：

```powershell
scp -i "C:\Users\30372\.ssh\jackysource1.pem" .\kop-images.tar ubuntu@服务器公网IP:/opt/knowledge-orchestration-platform/
```

报错：

```text
remote mkdir "/opt/knowledge-orchestration-platform/": Permission denied
```

### 原因

`ubuntu` 用户没有权限直接在 `/opt` 下创建目录。`scp` 不能自动使用 `sudo` 创建远端目录。

### 解决方案

先用 SSH 登录服务器执行目录创建和授权：

```powershell
ssh -i "C:\Users\30372\.ssh\jackysource1.pem" ubuntu@服务器公网IP "sudo mkdir -p /opt/knowledge-orchestration-platform && sudo chown -R ubuntu:ubuntu /opt/knowledge-orchestration-platform"
```

再重新上传：

```powershell
scp -i "C:\Users\30372\.ssh\jackysource1.pem" .\kop-images.tar ubuntu@服务器公网IP:/opt/knowledge-orchestration-platform/
```

### 11.2 Compose 找不到 `.env.prod`

### 现象

服务器执行：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml config
```

报错：

```text
Couldn't find env file: /opt/knowledge-orchestration-platform/.env.prod
```

### 原因

服务器目录里只上传了 `kop-images.tar` 或 compose 文件，但没有上传 `.env.prod`。

启动业务容器至少需要：

```text
/opt/knowledge-orchestration-platform/.env.prod
/opt/knowledge-orchestration-platform/docker-compose.prod.yml
```

如果是本地镜像上传部署，还需要已经执行过：

```bash
docker load -i kop-images.tar
```

### 解决方案

从本地 PowerShell 上传 `.env.prod` 和 `docker-compose.prod.yml`：

```powershell
scp -i "C:\Users\30372\.ssh\jackysource1.pem" .\.env.prod ubuntu@服务器公网IP:/opt/knowledge-orchestration-platform/.env.prod
scp -i "C:\Users\30372\.ssh\jackysource1.pem" .\docker-compose.prod.yml ubuntu@服务器公网IP:/opt/knowledge-orchestration-platform/docker-compose.prod.yml
```

服务器检查文件：

```bash
cd /opt/knowledge-orchestration-platform
ls -la
```

应看到：

```text
.env.prod
docker-compose.prod.yml
kop-images.tar
```

收紧 `.env.prod` 权限：

```bash
chmod 600 .env.prod
```

### 11.3 不要把完整 `docker compose config` 输出外发

### 原因

`docker compose config` 会把 compose 配置渲染出来，可能包含环境变量。生产 `.env.prod` 里有 API Key、SMTP 授权码、数据库密码等敏感信息。

### 推荐命令

只做静默校验：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml config --quiet
```

结果判断：

```text
无输出、无报错 = 配置解析通过
有报错 = 按错误信息修配置
```

### 11.4 已经 `docker load` 后启动不要重新构建

### 场景

本次部署路径是：

```text
本地构建镜像 -> docker save 导出 tar -> scp 上传服务器 -> docker load 加载镜像 -> compose 启动
```

这种场景服务器已经有：

```text
kop-backend:latest
kop-frontend:latest
```

启动时应使用：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --no-build
```

不要使用：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

否则服务器会尝试重新构建镜像，失去本地构建上传的意义，也可能再次遇到 Docker Hub、apt、pip 网络问题。

### 11.5 本次成功结果记录

服务器镜像加载后检查：

```bash
docker images | grep kop-
```

实际结果：

```text
kop-backend   latest   2.25GB
kop-frontend  latest   52MB
```

配置检查：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml config --quiet
```

结果：

```text
无输出、无报错
```

启动命令：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --no-build
```

启动结果：

```text
Network kop_app created
Volume knowledge-orchestration-platform_app_data created
Container kop-backend started
Container kop-frontend started
```

容器状态：

```text
kop-backend   Up   127.0.0.1:8000->8000/tcp
kop-frontend  Up   0.0.0.0:80->80/tcp
```

后端日志关键结果：

```text
Initial index build skipped because REBUILD_INDEX_ON_STARTUP=false.
Application startup complete.
Uvicorn running on http://0.0.0.0:8000
```

前端日志关键结果：

```text
nginx/1.27.5
Configuration complete; ready for start up
start worker processes
```

结论：业务容器已经成功启动，前端暴露 `80` 端口，后端仅绑定服务器本机 `127.0.0.1:8000`，由前端 Nginx 代理 `/api` 访问后端。

## 12. 线上上传 / 重建索引卡在 Hugging Face 模型下载

### 现象

生产环境上传小文件、加载文档或重建索引很慢，后端日志出现类似内容：

```text
HEAD https://huggingface.co/BAAI/bge-small-zh-v1.5/resolve/main/config.json
Retrying in 2s
Network is unreachable
```

前端表现通常是上传或文档加载一直转圈，刷新后文件记录可能已经存在，但索引没有及时完成。

### 原因

后端首次执行向量化时会加载 embedding 模型：

```env
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
```

如果模型没有缓存，`sentence-transformers` 会从 Hugging Face 下载模型文件。国内服务器访问 `huggingface.co` 不稳定时，会导致上传、解析、索引链路被模型下载阻塞。

如果缓存目录没有放进 Docker volume，容器重建后还会重复下载。

### 解决

当前 env 已增加模型缓存目录：

```env
HF_HOME=data/huggingface
SENTENCE_TRANSFORMERS_HOME=data/sentence-transformers
```

代码使用点：

```text
app/core/settings.py        读取并解析 HF_HOME / SENTENCE_TRANSFORMERS_HOME
app/services/embeddings.py  创建缓存目录，并把 SENTENCE_TRANSFORMERS_HOME 显式传给 SentenceTransformer(cache_folder=...)
```

生产 compose 已挂载：

```yaml
volumes:
  - app_data:/app/data
```

后端容器工作目录是 `/app`，所以这两个相对路径实际会落到：

```text
/app/data/huggingface
/app/data/sentence-transformers
```

这两个目录位于 `app_data` volume 中，容器重建后仍然保留。

如果服务器访问 Hugging Face 慢，可以在服务器 `.env.prod` 中临时把镜像站作为主地址：

```env
HF_ENDPOINT=https://hf-mirror.com
HF_FALLBACK_ENDPOINT=https://huggingface.co
```

修改服务器 `.env.prod` 后重建后端容器，让新环境变量生效：

```bash
cd /opt/knowledge-orchestration-platform
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --force-recreate --no-build backend
```

### 验证

确认应用解析后的缓存路径：

```bash
docker exec -it kop-backend python -c "from app.core.settings import settings; print('hf_endpoint=', settings.hf_endpoint); print('hf_home=', settings.hf_home); print('sentence_transformers_home=', settings.sentence_transformers_home)"
```

测试镜像站是否能访问：

```bash
docker exec -it kop-backend python -c "import urllib.request; print(urllib.request.urlopen('https://hf-mirror.com', timeout=10).status)"
```

预下载 embedding 模型：

```bash
docker exec -it kop-backend python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5', device='cpu'); print('embedding model ready')"
```

确认模型缓存已经写入持久卷：

```bash
docker exec -it kop-backend sh -lc "du -sh /app/data/huggingface /app/data/sentence-transformers 2>/dev/null || find /app/data -maxdepth 3 -type d | grep -Ei 'huggingface|sentence'"
```

再次上传文件或重建索引时，后端日志不应继续反复出现：

```text
huggingface.co
Network is unreachable
Retrying in ...
```

## 13. 推荐排障顺序

后续如果 Docker 构建失败，按这个顺序排查：

1. `docker ps` 是否正常，确认 Docker Desktop Engine 没卡住。
2. 单独 `docker pull` 基础镜像，确认 Docker Hub 链路正常。
3. 后端构建失败时，看失败位置是 `apt-get`、`pip install`，还是 `torch`。
4. `apt-get` 失败，检查 `APT_MIRROR`。
5. `pip install` 普通包失败，检查 `PIP_INDEX_URL`。
6. 出现 `nvidia-*` / `cuda-*`，检查 `TORCH_VERSION=2.3.1+cpu` 是否生效。
7. 构建成功后运行第 9 节验证命令。
8. 上传服务器失败，先检查 `/opt/knowledge-orchestration-platform` 目录是否存在且属于 `ubuntu` 用户。
9. `config` 提示找不到 `.env.prod`，上传 `.env.prod` 和 `docker-compose.prod.yml`。
10. 已经 `docker load` 的部署方式，启动必须用 `up -d --no-build`。
11. 上传、解析或重建索引长时间转圈，检查第 12 节的 Hugging Face 模型下载和缓存目录。

核心原则：

```text
先拉通基础镜像，再构建业务镜像。
先判断失败发生在哪一层，再改对应配置。
不要反复无目的地切换代理和镜像源。
本地镜像上传部署时，不要在服务器重复构建。
```
