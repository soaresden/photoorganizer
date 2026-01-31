# Contributing to TriPhoto

Thanks for your interest in contributing to TriPhoto! 🎉

## How to Contribute

### Reporting Bugs
1. Check if the bug is already reported in [Issues](../../issues)
2. If not, create a new issue with:
   - Clear title and description
   - Steps to reproduce
   - Expected vs actual behavior
   - Console logs (with `[SCAN]`, `[DISPLAY]`, etc. prefixes)
   - Python version and OS

### Suggesting Features
1. Check if feature is already suggested
2. Create a new issue tagged as "enhancement"
3. Describe the feature and use case
4. Include mockups/examples if applicable

### Pull Requests
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes
4. Test thoroughly
5. Update documentation if needed
6. Commit with clear messages
7. Push and create a Pull Request

### Code Style
- Follow PEP 8
- Use descriptive variable names
- Add comments for complex logic
- Include logging with appropriate prefixes:
  - `[SCAN]` for file scanning
  - `[DISPLAY]` for UI display
  - `[EXTRACT]` for video processing
  - `[YOUR_PREFIX]` for new features

### Testing
- Test on your camera folder structure
- Test with various file types (JPG, PNG, HEIC, MP4, etc.)
- Test edge cases (files without dates, special characters, etc.)
- Verify video preview works with FFmpeg

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/TriPhoto.git
cd TriPhoto

# Install dependencies
pip install -r requirements.txt

# Run application
python TriPhoto_v5.py
```

## Questions?
Feel free to open an issue for any questions about contributing!
