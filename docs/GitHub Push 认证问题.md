# GitHub Push 认证问题排查记录

## 1. 问题背景

本地仓库在执行以下命令时失败：

```powershell
git push -u origin main
```

最开始报错是：

```text
fatal: unable to access 'https://github.com/...': Recv failure: Connection was aborted
```

随后又出现：

```text
remote: Invalid username or token. Password authentication is not supported for Git operations.
fatal: Authentication failed
```

切换到 SSH 远程地址后，又出现：

```text
git@github.com: Permission denied (publickey).
fatal: Could not read from remote repository.
```

---

## 2. 这次排查用到了什么

严格来说，这里**不是 Linux 语言**，而是下面这些工具/命令：

- Windows PowerShell
- Git 命令
- OpenSSH 客户端
- GitHub Web 页面

---

## 3. 采集到的数据

### 3.1 Git 远程地址

```powershell
git remote -v
```

输出：

```text
origin https://github.com/soberminds/knowledge-orchestration-platform.git (fetch)
origin https://github.com/soberminds/knowledge-orchestration-platform.git (push)
```

说明：
- 远程仓库地址本身是正确的
- 但 HTTPS 推送时认证失败

### 3.2 Git 版本

```powershell
git --version
```

输出：

```text
git version 2.50.1.windows.1
```

### 3.3 Git 代理/HTTP 配置

```powershell
git config --global --get http.version
git config --global --get http.proxy
git config --global --get https.proxy
```

结果：
- 没有设置代理
- 没有强制 HTTP/2
- 后来手动设置了 `http.version=HTTP/1.1`

### 3.4 SSH 服务状态

```powershell
Get-Service ssh-agent
sc.exe qc ssh-agent
```

输出结论：

- `ssh-agent` 状态是 `Stopped`
- `StartType` 是 `Disabled`

说明：
- 这个服务被系统禁用了
- 但这不影响你使用 SSH key 本身，只是不能自动缓存私钥密码

### 3.5 SSH 公钥文件

生成成功后，公钥文件路径是：

```text
C:\Users\16062\.ssh\id_ed25519.pub
```

其内容形如：

```text
ssh-ed25519 AAAA... 1606290354@qq.com
```

---

## 4. 解决流程

### 步骤 1：把 HTTPS 远程地址改成 SSH

```powershell
git remote set-url origin git@github.com:soberminds/knowledge-orchestration-platform.git
```

目的：
- 避免继续走 HTTPS 密码认证
- 改成 SSH 公钥认证

### 步骤 2：生成 SSH 密钥对

```powershell
ssh-keygen -t ed25519 -C "1606290354@qq.com"
```

生成结果：
- 私钥：`C:\Users\16062\.ssh\id_ed25519`
- 公钥：`C:\Users\16062\.ssh\id_ed25519.pub`

说明：
- 私钥保存在本机
- 公钥要上传到 GitHub

### 步骤 3：把公钥复制到剪贴板

```powershell
Get-Content $HOME\.ssh\id_ed25519.pub | Set-Clipboard
```

这一步的目的：
- 把公钥粘贴到 GitHub 页面里

### 步骤 4：把公钥加到 GitHub

有两种入口：

#### 方案 A：账号级 SSH Key

路径：

- GitHub `Settings`
- `SSH and GPG keys`
- `New SSH key`

适合：
- 这把 key 给你整个 GitHub 账号使用

#### 方案 B：仓库级 Deploy Key

你截图里的页面就是这个。

路径：

- 仓库 `Settings`
- `Deploy keys`
- `Add deploy key`

适合：
- 只给某一个仓库使用
- 如果要 `git push`，需要勾选 `Allow write access`

### 步骤 5：测试 SSH 连接

```powershell
ssh -T git@github.com
```

预期结果：
- 如果成功，会显示 GitHub 欢迎信息
- 如果失败，会继续提示 `Permission denied (publickey)`

### 步骤 6：重新推送

```powershell
git push -u origin main
```

---

## 5. 输入输出总结

| 输入 | 输出 | 含义 |
|---|---|---|
| `git push -u origin main`（HTTPS） | `Invalid username or token` | GitHub 不再支持密码方式推送 |
| `git remote set-url ...` | 远程地址变成 SSH | 准备切换到公钥认证 |
| `ssh-keygen -t ed25519 ...` | 生成 `id_ed25519` 和 `id_ed25519.pub` | 完成一对 SSH 密钥 |
| `Get-Content ...pub | Set-Clipboard` | 公钥进入剪贴板 | 准备粘贴到 GitHub |
| `ssh-agent` 启动 | `Disabled` / 启动失败 | 系统服务被禁用 |
| `ssh -T git@github.com` | `Permission denied (publickey)` | GitHub 还没认到你的公钥，或公钥还没添加正确 |

---

## 6. SSH 公钥/私钥原理

SSH 认证本质上是一种“你能证明你拥有私钥”的机制。

### 6.1 密钥对是什么

SSH 会生成一对配套的密钥：

- **私钥（private key）**：只保存在你自己的电脑上，不能泄露
- **公钥（public key）**：可以公开，发给 GitHub 没问题

这两把钥匙是数学上配套的。

### 6.2 它是怎么验证的

大致流程是：

1. 你本机发起 SSH 连接
2. GitHub 看到你的公钥已经登记在自己的系统里
3. GitHub 给你一个随机挑战
4. 你的本机用**私钥**对挑战进行签名
5. GitHub 用保存的**公钥**验证这个签名
6. 验证通过，就说明你真的持有对应私钥

### 6.3 为什么要把公钥写到 GitHub

因为 GitHub 需要先知道：

- 哪些公钥是“被允许访问”的
- 这个公钥对应哪一个账号，或者哪一个仓库

换句话说：

- **私钥证明你是谁**
- **公钥告诉 GitHub：该拿什么来验证你**

如果 GitHub 没有你的公钥，它就无法验证你发来的签名，自然会拒绝连接。

### 6.4 为什么私钥不能上传

因为谁拿到私钥，谁就能冒充你。

所以原则是：

- 私钥只保留在本地
- 公钥才上传到 GitHub

---

## 7. 最终结果

当前已经完成：

- 生成 SSH 密钥对
- 拿到公钥内容
- 准备把公钥添加到 GitHub

接下来只需要：

- 把公钥粘贴到 GitHub
- 测试 `ssh -T git@github.com`
- 再执行 `git push -u origin main`

如果测试成功，这个仓库就能稳定使用 SSH 推送。

---

## 8. 复盘结论

这次问题不是代码问题，而是**Git 认证方式**的问题。

核心思路是：

1. 先确认远程地址
2. 再区分 HTTPS 和 SSH
3. HTTPS 失败就转 SSH
4. 用密钥对完成身份验证
5. 把公钥登记到 GitHub

这是一套非常典型的 GitHub 推送认证排障流程。

