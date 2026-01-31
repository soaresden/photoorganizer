# TriPhoto - Smart Photo & Video Organizer

A Python/Tkinter application designed to intelligently organize camera uploads by year and folder with advanced features like duplicate detection, video preview, and batch operations.

![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## 📸 Features

### Core Functionality
- **Automatic Year Detection**: Extracts year from filename (e.g., `IMG_20240815_143022.jpg` → 2024)
- **Folder Organization**: Organize files into `YEAR/FOLDER_NAME/` structure
- **Duplicate Detection**: Automatically moves duplicates to `!duplicate` folder
- **Smart Categorization**: Auto-organize screenshots and screen recordings into dedicated folders

### Advanced Features
- **Video Preview**: Extract and navigate through video screenshots at key timestamps (0%, 10%, 15%, 25%, 30%, 50%, 65%, 75%, 85%, 95%, 100%)
- **Interactive Slider**: Click points on timeline to preview different moments
- **Image Viewer**: Built-in image viewer with zoom support (Ctrl+Scroll)
- **HEIC Support**: Native support for Apple HEIC/HEIF images
- **Batch Operations**: Select multiple files for bulk organization
- **Color Coding**: Visual folder identification with auto-generated colors
- **Live Preview**: See final path before applying changes
- **Persistent Edits**: Auto-save work in progress, resume anytime

### Duplicate Management
- **Check Duplicates**: Scan organized folders for duplicate files
- **Auto-Delete**: Automatically remove screenshot duplicates if file exists in organized folder
- **Conflict Detection**: Identify files present in multiple organized folders
- **Ignore List**: Maintain permanent ignore list for known duplicates

## 🚀 Installation

### Prerequisites
- Python 3.8 or higher
- FFmpeg (for video screenshot extraction)

### Required Python Packages
```bash
pip install pillow pillow-heif send2trash
```

### FFmpeg Installation (Windows)
1. Download from [gyan.dev/ffmpeg](https://www.gyan.dev/ffmpeg/builds/)
2. Extract and add to PATH
3. Verify: `ffmpeg -version`

## 📁 Folder Structure

```
Camera Folder/
├── YEAR (e.g., 2024)/
│   ├── 2024-08-15 Vacation/
│   │   ├── IMG_20240815_143022.jpg
│   │   └── VID_20240815_160255.mp4
│   ├── 2024-Cooking/
│   ├── !Screenshots_2024/      (auto-organized)
│   └── !ScreenRecorder_2024/   (auto-organized)
├── 2025/
│   └── ...
├── !duplicate/                  (automatic duplicates)
└── !tempvideoscreen/            (video preview cache)
```

## 🎯 Usage

### Basic Workflow

1. **Scan Camera Folder**
   - Click `Browse` to select your camera uploads folder
   - Click `Scan` to index all images and videos
   - Duplicates automatically moved to `!duplicate`

2. **Organize Files**
   - Select file(s) in the main list
   - Choose existing folder from the **Folders** listbox
   - OR create new folder with custom name
   - Preview shows final path: `\YEAR\FOLDER_NAME\filename.jpg`

3. **Apply Changes**
   - Review all changes in the list
   - Click `✅ APPLY` to move files
   - Files are moved with collision detection (auto-renames if needed)

4. **Video Preview**
   - Click on a video file
   - Screenshots extracted automatically (cached for performance)
   - Use slider to navigate through video timeline
   - Click points at 0%, 10%, 15%, 25%, 30%, 50%, 65%, 75%, 85%, 95%, 100%

### Auto-Organization

**Screenshots & Screen Recordings**
- Click `⚡ Auto Screenshots/Recorder`
- Files containing "screenshot" → `!Screenshots_YEAR/`
- Files containing "screen" + "recorder" → `!ScreenRecorder_YEAR/`

### Duplicate Management

**Check Duplicates**
1. Click `🔍 Check Duplicates`
2. **Auto-Delete**: Screenshot duplicates removed if file exists in organized folder
3. **Conflicts**: Dialog shows files in multiple organized folders
4. Options:
   - `Ignore Selected`: Add to permanent ignore list
   - `Open Folder`: Navigate to file location
   - Manually delete unwanted copies

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Delete` | Delete selected files (send to trash) |
| `Ctrl+Scroll` | Zoom image in/out |
| `↑↓` | Navigate files |
| `Double-Click` | Edit year field (for files without date metadata) |

## 🎨 Interface

### Three-Panel Layout

```
┌─────────────────────────────────────────────────────────────┐
│  [Camera Folder] [Browse] [Scan]                            │
├──────────────────┬──────────────────┬────────────────────────┤
│                  │                  │                        │
│  📋 Files List   │  📁 Folders      │  🖼️ Preview           │
│                  │                  │                        │
│  • Filename      │  • 2024-Vacation │  [Image/Video]        │
│  • Year          │  • 2024-Cooking  │                        │
│  • Folder Name   │  • 2024-Work     │  [Video Slider]       │
│  • Final Path    │                  │  0% ● ● ● 50% ● 100%  │
│                  │  [Create New]    │                        │
│  [Color coded    │  [✨ Create]     │                        │
│   by folder]     │                  │                        │
│                  │                  │                        │
├──────────────────┴──────────────────┴────────────────────────┤
│  [⚡ Auto] [🔍 Duplicates] [✅ APPLY] [🗑️ DELETE] [❌ Reset] │
└─────────────────────────────────────────────────────────────┘
```

## ⚙️ Configuration Files

All configuration files are stored next to the script:

- `triphoto_config.json` - Camera folder path
- `triphoto_edits.json` - Current editing session (auto-saved)
- `triphoto_ignore.json` - Duplicate ignore list

## 🎬 Video Preview Technical Details

**Screenshot Extraction**
- Uses FFmpeg/FFprobe
- Extracts 11 frames at specific percentages
- Cached in `!tempvideoscreen/` folder
- Hash-based naming prevents re-extraction
- Fallback to double-click playback if FFmpeg unavailable

**Slider Points**
- 0% - Start
- 10%, 15%, 25%, 30% - Early moments
- 50% - Middle
- 65%, 75%, 85%, 95% - Later moments
- 100% - End (t-0.5s to avoid black frame)

## 🔧 Advanced Features

### Color Coding
- Each folder gets a unique pastel color (HSL-based)
- Consistent across sessions (hash-based generation)
- Visual grouping in file list
- Colors assigned by **Folders listbox**, applied to TreeView

### Edit Year Manually
- Double-click on **Year** column
- Useful for files without date metadata (e.g., `unnamed.jpg`)
- Updates folder list and final path automatically

### Persistent Editing
- All edits auto-saved to `triphoto_edits.json`
- Resume work after closing application
- Deleted files removed from cache automatically

## 🐛 Troubleshooting

**Video preview not working**
- Install FFmpeg and add to PATH
- Check console for `[EXTRACT]` logs
- Verify with: `ffmpeg -version`

**HEIC images not showing**
- Install: `pip install pillow-heif`
- Restart application

**Files not moving**
- Check write permissions on destination folder
- Review console for `[SCAN]` and `[DISPLAY]` logs
- Verify folder structure matches expected format

**Duplicates not detected**
- Check filename exactly matches (case-sensitive)
- Files must be in year folders (`2024/`, `2025/`, etc.)
- Special folders (`!Screenshots_*`, `!ScreenRecorder_*`) are treated as screenshot folders

## 📝 Logging

Enable detailed logging by running from terminal:
```bash
python TriPhoto_v5.py
```

Log prefixes:
- `[SCAN]` - File scanning operations
- `[DISPLAY]` - Media display events
- `[EXTRACT]` - Video screenshot extraction
- `[SLIDER]` - Slider drawing and interactions
- `[SLIDER-CLICK]` - Click events and image loading
- `[DUPLICATES]` - Duplicate detection operations

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## 📄 License

MIT License - feel free to use and modify for your needs.

## 🙏 Acknowledgments

- Built with Python & Tkinter
- Video processing powered by FFmpeg
- HEIC support via pillow-heif
- Safe file deletion with send2trash

## 📞 Support

For issues, questions, or feature requests, please open an issue on GitHub.

---

**Made with ❤️ for organizing thousands of camera photos and videos**
