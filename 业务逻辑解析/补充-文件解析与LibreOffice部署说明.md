# 补充：文件解析与 LibreOffice 部署说明

这份补充文档专门回答两个问题：

1. 后端到底能不能直接解析各种文件
2. LibreOffice 在本地和 Docker 部署里应该装在哪里、怎么配

## 1. 后端能不能直接解析？

可以，但要分文件类型看，不是所有 Office 格式都完全一样。

### 1.1 可以直接解析的类型

这些类型当前后端可以直接读取或直接抽取结构化内容：

- `.txt` / `.md` / `.json` / `.yaml` / `.yml` / `.ini` / `.cfg` / `.toml` / `.sql` / 代码类文本文件
  - 方式：直接读文本内容
- `.csv` / `.tsv`
  - 方式：后端用表格解析逻辑读取，再统一输出为表格或文本结构
- `.xlsx` / `.xlsm`
  - 方式：后端直接解析工作表内容
- `.xls`
  - 方式：后端直接解析旧版 Excel 内容
- `.pdf`
  - 方式：后端直接按页抽取 PDF 文本
- `.docx`
  - 方式：后端直接抽取正文和表格内容
- `.pptx`
  - 方式：后端直接抽取每页幻灯片文本

这里的“直接解析”指的是：

- 不需要先借助 LibreOffice 做格式转换
- 后端进程本身就能把文件内容读出来并组织成统一的数据结构

## 2. 哪些类型不能完全直接解析？

### 2.1 旧版 `.ppt`

旧版 `.ppt` 当前**不能直接按现有代码路径解析**。

现在的实现是：

1. 先找到 `soffice`
2. 用 LibreOffice 把 `.ppt` 转成 `.pptx`
3. 再按 `.pptx` 方式抽取每页文字

所以：

- 如果你要支持旧版 `.ppt` 的文本抽取
- 就需要可用的 LibreOffice `soffice`

### 2.2 旧版 `.doc`

旧版 `.doc` 不是高保真直接解析，而是“尽力提取文本”。

当前后端会尝试一些文本提取方式，把 `.doc` 里的文字读出来用于：

- 轻量预览兜底
- 建索引

但如果你追求高保真排版或更稳的转换效果，`.docx` 明显更好。

## 3. 这些“后端解析”主要用在哪儿？

主要用在两条链路，不要和 ONLYOFFICE 查看混在一起。

### 3.1 轻量预览链路

非 Office 主查看链路，或者某些兼容兜底分支，会让后端返回：

- 文本内容
- 页码 / sheet / slide 信息
- 表格结构
- 格式类型：`plain` / `markdown` / `table`

这个接口是给前端预览器用的，不是给向量索引直接用的。

### 3.2 索引建立链路

上传文件、手动重建索引、ONLYOFFICE 保存后自动更新索引时，后端会先把文件转成可检索文本，再切片建索引。

也就是说：

- 文件抽取是建索引的前置步骤
- 抽取不到文本，就没法正常切片和入库

## 4. 所以是不是必须安装 LibreOffice？

结论分两种情况。

### 4.1 如果你要完整支持当前项目声明的旧格式能力

建议安装。

因为当前代码里，LibreOffice 主要还负责：

- 旧版 `.ppt` -> 转 `.pptx` -> 再抽取文本
- 某些 `.doc/.docx/.ppt/.pptx` 的 PDF 预览兜底

如果你不装 LibreOffice：

- `.ppt` 抽取会失败
- 某些旧的 Office->PDF 兼容预览能力会失效

### 4.2 如果你只用现代格式，并且主流程只走 ONLYOFFICE

可以不把 LibreOffice 当成绝对强依赖，但要接受能力降级。

比如：

- 你只处理 `.docx` / `.xlsx` / `.pptx`
- 查看和编辑都走 ONLYOFFICE
- 不要求旧版 `.ppt` 参与索引

那你可以暂时不依赖 LibreOffice。  
但要明确：这意味着你实际上放弃了当前代码里对某些旧格式的完整支持。

## 5. 本地安装时，装在哪里？

如果后端是直接跑在你本机 Windows 上，那就装在本机即可。

常见路径：

```env
SOFFICE_BIN=C:\Program Files\LibreOffice\program\soffice.exe
```

当前配置读取位置在：

- `app/core/settings.py`

配置名是：

- `SOFFICE_BIN`

如果你不填，代码也会尝试去系统默认路径找 `soffice`。

## 6. Docker 部署时，装在哪里？

**要装在后端容器里，不是 ONLYOFFICE 容器里。**

原因很重要：

- `.ppt` 抽取和兼容预览转换，是后端 Python 服务在做
- 不是 ONLYOFFICE 文档服务在做

所以部署角色是：

- 后端容器：负责文件抽取、索引、兼容转换
- ONLYOFFICE 容器：负责浏览器里的 Office 查看和编辑

这两个职责不要混掉。

## 7. 当前 Dockerfile 的情况

当前项目的后端 `Dockerfile` 已经做了这两件事：

1. 设置：

```dockerfile
ENV SOFFICE_BIN=/usr/bin/soffice
```

2. 安装 LibreOffice 相关组件

为了让旧版 `.ppt` 更稳，建议后端镜像里至少包含：

- `libreoffice-writer-nogui`
- `libreoffice-impress-nogui`

其中：

- `writer` 更偏向文档转换
- `impress` 更偏向演示文稿转换

## 8. Docker 里配置怎么改？

如果你用当前项目自己的 `Dockerfile` 构建后端镜像，通常不用额外改路径，默认就是：

```env
SOFFICE_BIN=/usr/bin/soffice
```

如果你是 `docker compose` 启动后端，也可以显式写在环境变量里：

```yaml
services:
  backend:
    build: .
    environment:
      SOFFICE_BIN: /usr/bin/soffice
      PREVIEW_CONVERT_TIMEOUT_SEC: 120
```

也就是说：

- **安装位置**：后端镜像 / 后端容器内部
- **配置位置**：后端服务环境变量 `SOFFICE_BIN`
- **不是** 配在 ONLYOFFICE 容器里

## 9. 一句话记忆版

你可以这样记：

- `ONLYOFFICE` 负责 Office 文件的浏览器查看和编辑
- `LibreOffice` 负责后端旧格式兼容和部分转换兜底
- 旧版 `.ppt` 想正常抽取文本建索引，当前实现下需要 `LibreOffice`
- Docker 部署时，`LibreOffice` 装在后端容器，不装在 ONLYOFFICE 容器
