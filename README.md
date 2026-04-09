# pixiv-bookmarks-downloader

批量下载 Pixiv 收藏夹作品的 Python 脚本，自动过滤 AI 生成作品，支持断点续传与增量更新。

## 功能特性

- ✅ 通过 [OpenCLI](https://github.com/) 复用 Chrome 登录态，免处理 Pixiv 登录/Cookie
- ✅ 自动枚举收藏夹全部作品（Pixiv AJAX API）
- ✅ 过滤 AI 生成作品（基于 tag 关键词匹配：NovelAI / StableDiffusion / Midjourney 等）
- ✅ 智能文件组织：单图作品直接放根目录，多图作品放子文件夹
- ✅ 支持 `.jpg / .png / .gif / .webp / .mp4 / .webm / .zip`（含 ugoira）
- ✅ 断点续传：重新运行自动跳过已下载作品
- ✅ 增量模式：整页作品都已下载时自动停止枚举，避免全量扫描

## 依赖

- Python 3.8+
- [OpenCLI](https://www.npmjs.com/package/opencli) + Browser Bridge Chrome 扩展
- 已登录 Pixiv 的 Chrome 浏览器

## 使用

1. 安装并配置 OpenCLI：
   ```bash
   npm install -g opencli
   ```
   然后在 Chrome 安装 Browser Bridge 扩展并登录 Pixiv。

2. 修改脚本中的配置：
   ```python
   OUTPUT_DIR = os.path.expanduser("~/Pictures/pixiv_bookmarks")
   USER_ID = "你的 Pixiv UID"
   ```

3. 运行：
   ```bash
   python3 pixivdownload.py       # 命令行版：过滤 AI 作品
   python3 download_all.py        # 命令行版：下载全部（不过滤 AI）
   python3 pixivdownload_gui.py   # 图形界面（带进度条）
   ```

## 三个版本

- **`pixivdownload.py`** — 命令行版，基于 tag 关键词过滤 AI 生成作品
- **`download_all.py`** — 命令行版，无过滤，下载收藏夹全部作品
- **`pixivdownload_gui.py`** — Tkinter 图形界面包装器：开始/停止按钮、进度条、实时日志、AI 过滤开关（无额外依赖）

## 文件组织

```
pixiv_bookmarks/
├── 123456.jpg              # 单图作品
├── 789012.png
└── 345678_作品标题/         # 多图作品
    ├── 345678_p0.jpg
    └── 345678_p1.jpg
```

## AI 过滤关键词

脚本会检查作品 tag，匹配以下任意关键词即跳过：
`ai` / `novelai` / `stable_diffusion` / `midjourney` / `nijijourney` / `dall-e` / `ai生成` / `ai绘画` 等。

可在 `AI_TAGS` 列表中自行增减。

## License

MIT
