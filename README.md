# pixiv-bookmarks-downloader

批量下载 Pixiv 收藏夹作品的 Python 脚本，自动过滤 AI 生成作品，支持断点续传、增量更新与元数据导出。

## 功能特性

- 通过 [OpenCLI](https://www.npmjs.com/package/opencli) 复用 Chrome 登录态，免处理 Pixiv 登录/Cookie
- 自动枚举收藏夹全部作品（Pixiv AJAX API）
- 过滤 AI 生成作品（基于 tag 关键词匹配：NovelAI / StableDiffusion / Midjourney 等）
- 智能文件组织：单图作品直接放根目录，多图作品放子文件夹
- 支持 `.jpg / .png / .gif / .webp / .mp4 / .webm / .zip`（含 ugoira）
- 断点续传：重新运行自动跳过已下载作品
- 增量模式：整页都已下载时自动停止枚举；可加 `--full` 强制全量扫描
- **GUI 内置 UID / 保存路径输入框**，无需修改源码即可配置
- **元数据导出**：每个作品自动追加一行到 `metadata.jsonl`（作者、tag、上传时间、URL、本地路径等）

## 依赖

- Python 3.8+
- [OpenCLI](https://www.npmjs.com/package/opencli) + Browser Bridge Chrome 扩展
- 已登录 Pixiv 的 Chrome 浏览器

## 安装与使用

1. 安装并配置 OpenCLI：
   ```bash
   npm install -g opencli
   ```
   然后在 Chrome 安装 Browser Bridge 扩展并登录 Pixiv。

2. 启动 GUI 配置 UID 与保存路径：
   ```bash
   python3 pixivdownload_gui.py
   ```
   - 顶部填入你的 Pixiv UID（登录后访问个人主页，URL 里的数字）
   - 选择保存路径（默认 `~/Pictures/pixiv_bookmarks/`）
   - 点击「开始下载」，配置会自动保存到 `~/.pixiv_bookmarks_downloader.json`

3. 或者直接命令行运行（需先配置 UID）：
   ```bash
   # 方式 A：环境变量
   PIXIV_UID=你的UID PIXIV_OUTPUT_DIR=~/Downloads/pixiv python3 pixivdownload.py

   # 方式 B：写入配置文件 ~/.pixiv_bookmarks_downloader.json
   # { "uid": "12345678", "output_dir": "~/Downloads/pixiv" }
   python3 pixivdownload.py
   ```

## 三个版本

- **`pixivdownload.py`** — 命令行版，基于 tag 关键词过滤 AI 生成作品
- **`download_all.py`** — 命令行版，无过滤，下载收藏夹全部作品
- **`pixivdownload_gui.py`** — Tkinter 图形界面：UID/路径输入框、AI 过滤开关、完整扫描开关、进度条、实时日志（无额外依赖）

三个脚本共享 `pixiv_core.py` 中的核心逻辑（抓取 / 过滤 / 下载 / 元数据）。

## 配置优先级

资源解析顺序（命中第一个非空值即生效）：

1. 环境变量 `PIXIV_UID` / `PIXIV_OUTPUT_DIR`
2. `~/.pixiv_bookmarks_downloader.json`
3. 内置默认（output_dir = `~/Pictures/pixiv_bookmarks/`；UID **没有**默认值，未配置则报错退出）

## 文件组织

```
<output_dir>/
├── metadata.jsonl          # 元数据日志（每行一个 JSON 对象）
├── 123456.jpg              # 单图作品
├── 789012.png
└── 345678_作品标题/         # 多图作品
    ├── 345678_p0.jpg
    └── 345678_p1.jpg
```

## 元数据格式

`metadata.jsonl` 每行一个作品，字段：

```json
{
  "id": "123456",
  "title": "作品标题",
  "author_id": "9876543",
  "author_name": "作者名",
  "tags": ["tag1", "tag2"],
  "pages": 3,
  "illust_type": 0,
  "create_date": "2024-01-15T12:34:56+09:00",
  "update_date": "2024-01-15T12:34:56+09:00",
  "x_restrict": 0,
  "thumbnail_url": "https://i.pximg.net/...",
  "pixiv_url": "https://www.pixiv.net/artworks/123456",
  "local_path": "/abs/path/to/file_or_folder",
  "image_count": 3,
  "downloaded_at": 1716700000
}
```

可用 `jq` 检索，例：
```bash
# 列出某作者所有作品
jq -c 'select(.author_name == "xxx")' metadata.jsonl
# 按 tag 过滤
jq -c 'select(.tags | contains(["原创"]))' metadata.jsonl
```

## AI 过滤关键词

脚本会检查作品 tag，匹配以下任意关键词即跳过：
`ai` / `novelai` / `stable_diffusion` / `midjourney` / `nijijourney` / `dall-e` / `ai生成` / `ai绘画` 等。

短关键词（≤5 字符）走精确匹配，避免 `ai` 误中 `honkaistarrail`；长关键词走子串匹配。
可在 `pixiv_core.py` 的 `AI_TAGS` 列表中自行增减。

## 命令行参数

- `--full`：禁用增量优化，扫描全部收藏（用于补漏被过滤 bug 误跳过的作品）

## License

MIT
