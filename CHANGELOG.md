# Changelog

All notable changes to TriPhoto will be documented in this file.

## [v5.0.0] - 2026-01-31

### 🎉 Initial Release

#### Added
- **Core Features**
  - Automatic year detection from filenames
  - Folder-based organization system (YEAR/FOLDER_NAME/)
  - Duplicate detection and auto-move to `!duplicate` folder
  - Three-panel interface (Files, Folders, Preview)
  - Color-coded folders for visual organization
  - Persistent edit cache (auto-save work in progress)

- **Video Preview System**
  - FFmpeg-based screenshot extraction at 11 key timestamps
  - Interactive slider with clickable points (0%, 10%, 15%, 25%, 30%, 50%, 65%, 75%, 85%, 95%, 100%)
  - Screenshot caching for improved performance
  - Fallback to double-click playback

- **Image Viewer**
  - Built-in image viewer with zoom (Ctrl+Scroll)
  - HEIC/HEIF support via pillow-heif
  - Auto-fit canvas with aspect ratio preservation

- **Batch Operations**
  - Multi-file selection
  - Bulk folder assignment
  - Auto-organize screenshots and screen recordings

- **Duplicate Management**
  - Check duplicates across all organized folders
  - Auto-delete screenshot duplicates when file exists in organized folder
  - Conflict detection for files in multiple organized folders
  - Permanent ignore list for known duplicates

- **UI/UX**
  - Folder listbox with color coding
  - Inline year editing (double-click)
  - Live final path preview
  - Status bar with operation feedback
  - Keyboard shortcuts (Delete, Arrow keys)

- **Technical**
  - Extensive logging system with prefixes ([SCAN], [DISPLAY], [EXTRACT], etc.)
  - Thread-based background scanning
  - Safe file operations with send2trash
  - Configuration persistence (JSON)

#### Fixed
- Video slider now correctly updates displayed image on point click
- Config file saved next to script (not in system32)
- Proper path normalization for send2trash compatibility
- Canvas resize handling for video previews

#### Technical Details
- Python 3.8+ compatible
- Tkinter-based UI
- FFmpeg required for video features
- Platform: Windows (primary), Linux/Mac (untested)

---

## Version Format
This project uses [Semantic Versioning](https://semver.org/):
- MAJOR version for incompatible API changes
- MINOR version for added functionality (backwards compatible)
- PATCH version for backwards compatible bug fixes
