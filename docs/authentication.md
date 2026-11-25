# 独立 GitHub／Copilot 登录工具

工具位于 **context-tree 项目**：`src/context_tree/tools/auth.py`，命令入口为
`context-tree-auth`。它不修改 pi，也不读取或复用 pi、VS Code 或其他 agent 的凭据。

## 登录

安装本项目后：

```sh
context-tree-auth login --allow-network
```

尚未安装命令入口时，在仓库根目录使用 Python 模块；先通过可编辑安装或
`PYTHONPATH=src` 使包可导入：

```sh
python -m context_tree.tools.auth login --allow-network
```

工具会请求 GitHub OAuth device code，打开 `https://github.com/login/device`，
并显示短期 **user code**。用户在浏览器登录自己的账号、输入该代码并确认授权。
账号密码和授权确认不能由 agent 代替用户完成。

该流程使用实验性 Copilot 设备授权协议及公开 OAuth client ID，要求账号有
Copilot 访问权限并符合服务条款；不是保证所有 GitHub PAT 都可使用的公开 SDK。
目前仅支持 github.com，不包含 GitHub Enterprise Server 自定义域名。

### 分两步适配 coding agent 工具调用

默认 `login` 在显示代码后立即返回，不启动隐形后台轮询进程。这样 coding
agent 可以把代码交给用户，不会一直阻塞到授权过期才展示。

浏览器批准后运行：

```sh
context-tree-auth complete --allow-network --timeout 180
```

工具轮询授权结果，获得 GitHub OAuth access token，再兑换短期 Copilot bearer
并保存。`authorization_pending` 会等待，`slow_down` 会增加并保存轮询间隔；
拒绝／过期停止，不无限重试。短轮询超时但 device code 尚有效时可再次 complete。
登录失败不覆盖此前可用的凭据。

用户直接在交互终端操作时，也可以一次等待：

```sh
context-tree-auth login --wait --allow-network
```

`--no-browser` 禁止自动打开浏览器，仍显示验证链接和 user code。
**user code 不是 access token**，仅用于当前短期设备授权；工具不会显示秘密的
`device_code`、GitHub access token 或 Copilot bearer。

## 凭据位置和权限

默认 Windows 位置：

```text
%LOCALAPPDATA%/context-tree/auth/copilot-credentials.json
```

其他平台使用项目的数据目录（`context_tree.common.config.data_dir`）。
`CONTEXT_TREE_DATA_DIR` 可覆盖位置，但保存认证文件时会拒绝 Git 工作区中的路径。
工具代码在仓库里，凭据不能放进仓库。

- POSIX：认证目录 `0700`、凭据文件 `0600`。
- Windows：显式设置受保护 DACL，仅当前用户和 SYSTEM 有访问权限。
- 保存采用同目录临时文件、flush/fsync 和原子替换；拒绝认证目录／文件符号链接。
- Token 是明文 JSON，不是加密保险库。磁盘加密、备份和用户账号安全仍需自行保护。
- 待授权 device code 临时存储于同一私有目录，完成、拒绝或过期时移除。
- 认证响应正文、密钥、子进程输出不会写入日志或显示到终端。

## 查看状态和验证

```sh
context-tree-auth status
context-tree-auth status --check --allow-network
```

`status` 只看本地元数据，返回保存位置、登录模式、有效期、是否过期和是否存在
环境变量覆盖。不会读取其他应用的认证状态。

`--check` 获取 Copilot 模型目录以验证权限，返回目录中的条目数量，不做推理；
这个数量不保证每个模型都已获准使用，模型策略仍以实际账号能力为准。

```sh
context-tree-auth logout
```

只删除本项目的凭据和待授权数据；不影响其他 agent 登录，也不撤销 GitHub 上的
服务端授权。需要撤销时，在 GitHub 的授权应用设置中处理。

## 模型传输接入

`common/llm.py` 按下列优先级选择凭据：

1. `CONTEXT_TREE_COPILOT_TOKEN`：显式短期 bearer，拒绝后要求用户替换。
2. `CONTEXT_TREE_GITHUB_TOKEN`：显式 GitHub token，尝试正常兑换。
3. 本工具创建的项目私有凭据。

私有凭据的 Copilot bearer 即将过期时，使用本项目保存的 GitHub OAuth token
正常续期；401 会尝试续期，若仍返回被拒绝的同一 token 则停止并要求重新登录。
重新登录不会通过读取其他应用 token 来绕过授权。

API 地址从 token 的 proxy endpoint 派生，只允许 HTTPS GitHub Copilot 官方
域名，避免把 Authorization header 发送给任意地址。环境变量覆盖同样遵循这个
地址校验。账号切换时清空进程内模型目录缓存。

这些认证／模型目录请求不计入推理请求预算；`sync`、`retrieve` 和模型评估
仍需单独的 `--allow-network`。登录成功不意味着允许上传所有私人历史。

## 测试

```sh
python -m unittest discover -s tests -p test_auth.py -v
```

测试使用虚构 token 和 mock 请求，覆盖安全输出、设备授权等待／降速／拒绝／
过期、保存与续期、环境变量优先级、API 地址校验和 Windows ACL 命令。
不登录真实账号，不读取或更改用户已有凭据，不调用真实模型。
