# 微信公众号文章转 Markdown

一个轻量命令行工具：把可访问的微信公众号文章正文转换为 Markdown，并可将正文图片保存到本地。

## 功能

- 提取文章标题和正文，输出 UTF-8 编码的 Markdown 文件。
- 下载正文中的常见懒加载图片，并在 Markdown 中改写为相对路径。
- 保留中文标题作为文件名；遇到同名文章时自动添加序号，避免覆盖已有文件。
- 可自定义输出目录和网络超时，也可以选择不下载图片。
- 不需要登录凭据；不收集或上传本地文件。

## 环境要求

Python 3.10 或更高版本。

## 安装

Windows PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 使用

默认保存到当前目录下的 `data/`：

```bash
python download_wechat.py "https://mp.weixin.qq.com/s/文章链接"
```

指定输出目录和请求超时：

```bash
python download_wechat.py "https://mp.weixin.qq.com/s/文章链接" --outdir ./downloads --timeout 30
```

只保存正文，不下载图片：

```bash
python download_wechat.py "https://mp.weixin.qq.com/s/文章链接" --no-images
```

每篇文章会生成一个 `.md` 文件；下载的图片会放在同名的 `_images/` 子目录。`data/` 默认已加入 `.gitignore`，避免误把下载内容提交到代码仓库。

## 测试

测试使用内置 HTML 和模拟 HTTP 响应，不会访问网络：

```bash
python -m unittest discover -s tests -v
```

## 已知限制

- 只接受 `mp.weixin.qq.com/s/...` 文章链接。
- 如果文章需要登录、遇到访问限制，或平台调整了页面结构，程序可能无法提取正文。
- 仅处理文章正文中可识别的图片；复杂排版、音视频、小程序卡片等内容不保证完整转换。

请仅下载你有权访问和保存的内容，并尊重作者的版权及相关平台规则。这个工具不绕过登录、付费或访问控制。
