#!/usr/bin/env python3
"""
TriPhoto - Smart Photo/Video Organizer
Organizes camera uploads by year with duplicate detection and manual categorization
"""

import os
import re
import json
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import threading
import queue
from pathlib import Path

try:
    from PIL import Image, ImageTk
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError as e:
    print(f"Warning: {e}")
    print("Install: pip install pillow pillow-heif")

class TriPhotoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TriPhoto - Smart Photo Organizer")
        self.root.geometry("1400x700")

        # Variables
        self.base_path = tk.StringVar()
        self.root_files = []  # Files in root
        self.year_files = {}  # {year: [list of filenames already organized]}
        self.file_data = {}  # {filename: {year, folder_name, path_final}}
        self.queue = queue.Queue()
        
        # Folder colors - defined by listbox, applied to treeview
        self.folder_colors = {}  # {folder_name: color}
        
        # Video cache
        self.video_cache_dir = None
        self.current_video_screenshots = []  # List of screenshot paths
        self.current_screenshot_index = 0
        
        # Duplicate ignore list
        self.duplicate_ignore_list = set()  # Set of filenames to ignore
        
        # Config and cache files next to script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(script_dir, "triphoto_config.json")
        self.edits_cache_file = os.path.join(script_dir, "triphoto_edits.json")
        self.ignore_list_file = os.path.join(script_dir, "triphoto_ignore.json")
        
        # Create video cache folder if base path exists
        self.load_config()
        base_path_value = self.base_path.get()
        if base_path_value and os.path.exists(base_path_value):
            self.video_cache_dir = os.path.join(base_path_value, '!tempvideoscreen')
            os.makedirs(self.video_cache_dir, exist_ok=True)
        
        # Load ignore list
        self.load_ignore_list()
        
        self.current_image = None
        self.current_image_pil = None
        self.current_filepath = None
        self.zoom_level = 1.0
        self.mpc_hc_path = r"C:\Program Files (x86)\K-Lite Codec Pack\MPC-HC64\mpc-hc64.exe"

        # File extensions
        self.image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.heic', '.heif'}
        self.video_extensions = {'.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv', '.m4v', '.3gp', '.webm', '.mts'}

        self.setup_ui()
        self.check_queue()

    def load_config(self):
        """Load configuration"""
        default_config = {
            "camera_path": "D:/DOCS/Documents/Camera Uploads/DCIM MI11TPRO/Camera"
        }

        print(f"=== LOADING CONFIG ===")
        print(f"Config file: {os.path.abspath(self.config_file)}")
        print(f"Current directory: {os.getcwd()}")

        try:
            if os.path.exists(self.config_file):
                print(f"✅ Config file found")
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            else:
                print(f"ℹ️ Config file not found, creating with default values")
                self.config = default_config
                self.save_config()
        except Exception as e:
            print(f"❌ Error loading config: {e}")
            self.config = default_config

        self.base_path.set(self.config.get("camera_path", default_config["camera_path"]))

    def save_config(self):
        """Save configuration"""
        try:
            self.config["camera_path"] = self.base_path.get()
            
            # Detailed logs
            print(f"=== SAVING CONFIG ===")
            print(f"Config file: {os.path.abspath(self.config_file)}")
            print(f"Directory: {os.path.dirname(os.path.abspath(self.config_file)) or os.getcwd()}")
            print(f"Directory exists: {os.path.exists(os.path.dirname(os.path.abspath(self.config_file)) or os.getcwd())}")
            print(f"File already exists: {os.path.exists(self.config_file)}")
            
            # Direct save (no temp file for debug)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Config saved successfully")
            
        except Exception as e:
            print(f"❌ Error saving config:")
            print(f"   Type: {type(e).__name__}")
            print(f"   Message: {e}")
            import traceback
            traceback.print_exc()

    def load_ignore_list(self):
        """Load duplicate ignore list from JSON"""
        try:
            if os.path.exists(self.ignore_list_file):
                with open(self.ignore_list_file, 'r', encoding='utf-8') as f:
                    self.duplicate_ignore_list = set(json.load(f))
        except Exception as e:
            print(f"Error loading ignore list: {e}")
            self.duplicate_ignore_list = set()

    def save_ignore_list(self):
        """Save duplicate ignore list to JSON"""
        try:
            with open(self.ignore_list_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.duplicate_ignore_list), f, indent=2)
        except Exception as e:
            print(f"Error saving ignore list: {e}")

    def setup_ui(self):
        """Setup user interface"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # === CONFIGURATION ===
        config_frame = ttk.LabelFrame(main_frame, text="⚙️ Configuration", padding="10")
        config_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(config_frame, text="Camera Folder:").grid(row=0, column=0, sticky=tk.W)
        path_entry = ttk.Entry(config_frame, textvariable=self.base_path, width=60)
        path_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 0))
        # Save only when leaving field (not on every keystroke)
        path_entry.bind('<FocusOut>', lambda e: self.save_config())

        ttk.Button(config_frame, text="Browse", command=self.browse_folder).grid(row=0, column=2, padx=(5, 0))
        ttk.Button(config_frame, text="Scan", command=self.start_scan).grid(row=0, column=3, padx=(5, 0))

        config_frame.columnconfigure(1, weight=1)

        # === SPLIT PANEL ===
        paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Left panel - TreeView
        left_panel = ttk.Frame(paned_window)
        paned_window.add(left_panel, weight=2)

        # Middle panel - Folders
        middle_panel = ttk.Frame(paned_window)
        paned_window.add(middle_panel, weight=1)

        # Right panel - Viewer
        right_panel = ttk.Frame(paned_window)
        paned_window.add(right_panel, weight=1)

        # === TREEVIEW ===
        tree_frame = ttk.LabelFrame(left_panel, text="📋 Files to Organize", padding="5")
        tree_frame.pack(fill=tk.BOTH, expand=True)

        # Columns: filename_display, year, folder_name, path_final
        columns = ('filename_display', 'year', 'folder_name', 'path_final')
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=12, selectmode='extended')

        self.tree.heading('filename_display', text='Filename')
        self.tree.heading('year', text='Year')
        self.tree.heading('folder_name', text='Folder Name')
        self.tree.heading('path_final', text='Final Path')

        self.tree.column('filename_display', width=250)
        self.tree.column('year', width=60)
        self.tree.column('folder_name', width=250)
        self.tree.column('path_final', width=300)

        scrollbar_tree = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar_tree.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_tree.pack(side=tk.RIGHT, fill=tk.Y)

        # Configure tag for blue selection
        self.tree.tag_configure('selected_cell', background='lightblue')

        # Bind selection to display in viewer
        self.tree.bind('<<TreeviewSelect>>', self.on_tree_select)
        # Double-click on Year to edit
        self.tree.bind('<Double-1>', self.on_tree_double_click)
        # Delete key to delete
        self.tree.bind('<Delete>', lambda e: self.delete_selected())

        # === FOLDERS LISTBOX (MIDDLE PANEL) ===
        self.folders_year_label = ttk.Label(middle_panel, text="📁 Folders", font=('Arial', 10, 'bold'))
        self.folders_year_label.pack(pady=(0, 5))
        
        folders_list_frame = ttk.Frame(middle_panel)
        folders_list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.folders_listbox = tk.Listbox(folders_list_frame, font=('Consolas', 9))
        scrollbar_folders = ttk.Scrollbar(folders_list_frame, orient=tk.VERTICAL, command=self.folders_listbox.yview)
        self.folders_listbox.configure(yscrollcommand=scrollbar_folders.set)
        
        self.folders_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_folders.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind click on listbox
        self.folders_listbox.bind('<<ListboxSelect>>', self.on_folder_select)
        
        # Frame for new folder
        new_folder_frame = ttk.LabelFrame(middle_panel, text="Create New", padding="5")
        new_folder_frame.pack(fill=tk.X)
        
        self.new_folder_var = tk.StringVar()
        new_folder_entry = ttk.Entry(new_folder_frame, textvariable=self.new_folder_var)
        new_folder_entry.pack(fill=tk.X, pady=(0, 5))
        new_folder_entry.bind('<Return>', lambda e: self.create_new_folder())
        
        ttk.Button(new_folder_frame, text="✨ Create", command=self.create_new_folder).pack(fill=tk.X)

        # === VIEWER ===
        viewer_frame = ttk.LabelFrame(right_panel, text="🖼️ Preview (Ctrl+Scroll = Zoom)", padding="10")
        viewer_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(viewer_frame, bg='gray20', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # Frame for video slider with clickable points
        self.video_slider_frame = ttk.Frame(viewer_frame)
        
        # Canvas for custom slider with points
        self.video_slider_canvas = tk.Canvas(self.video_slider_frame, height=40, bg='white', highlightthickness=1, highlightbackground='gray')
        self.video_slider_canvas.pack(fill=tk.X)
        self.video_slider_canvas.bind('<Button-1>', self.on_video_slider_click)
        
        self.video_slider_label = ttk.Label(self.video_slider_frame, text="", font=('Arial', 9))
        self.video_slider_label.pack()
        # Slider will be shown only for videos
        
        self.file_label = ttk.Label(viewer_frame, text="", font=('Arial', 9))
        self.file_label.pack(pady=(5, 0))

        # Zoom with wheel
        self.canvas.bind('<Control-MouseWheel>', self.on_mouse_wheel)
        self.canvas.bind('<Configure>', self.on_canvas_resize)

        # === ACTION BUTTONS ===
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X)

        ttk.Button(action_frame, text="⚡ Auto Screenshots/Recorder", command=self.auto_screenshots).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="🔍 Check Duplicates", command=self.check_duplicates).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="✅ APPLY", command=self.apply_changes, style='Accent.TButton').pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="🗑️ DELETE", command=self.delete_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="❌ Reset", command=self.reset_tree).pack(side=tk.LEFT, padx=5)

        # === STATUS BAR ===
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, pady=(5, 0))

    def draw_video_slider(self):
        """Draw custom video slider with clickable points"""
        print(f"[SLIDER] Drawing slider...")
        canvas = self.video_slider_canvas
        canvas.delete("all")
        
        width = canvas.winfo_width()
        if width <= 1:
            width = 600  # Default
            print(f"[SLIDER] Canvas width not ready, using default: {width}")
        else:
            print(f"[SLIDER] Canvas width: {width}")
        
        height = 40
        
        # Percentages for points
        percentages = [0, 10, 15, 25, 30, 50, 65, 75, 85, 95, 100]
        print(f"[SLIDER] Current screenshot index: {self.current_screenshot_index}")
        print(f"[SLIDER] Total screenshots: {len(self.current_video_screenshots)}")
        
        # Draw line
        y_line = height // 2
        canvas.create_line(20, y_line, width - 20, y_line, fill='gray', width=2)
        
        # Draw points
        for idx, pct in enumerate(percentages):
            x = 20 + (width - 40) * (pct / 100)
            
            # Draw circle - highlight current index
            radius = 6
            is_current = (idx == self.current_screenshot_index)
            color = 'blue' if is_current else 'lightgray'
            print(f"[SLIDER] Point {pct}% (index {idx}): color={color}, is_current={is_current}")
            
            canvas.create_oval(x - radius, y_line - radius, x + radius, y_line + radius, 
                              fill=color, outline='darkgray', tags=f'point_{pct}')
            
            # Draw label
            canvas.create_text(x, y_line + 15, text=f"{pct}%", font=('Arial', 8), tags=f'point_{pct}')
        
        # Bind clicks on points
        for pct in percentages:
            canvas.tag_bind(f'point_{pct}', '<Button-1>', 
                           lambda e, p=pct: self.on_video_slider_point_click(p))
        
        print(f"[SLIDER] Slider drawn successfully")

    def on_video_slider_click(self, event):
        """Click on slider area"""
        canvas = self.video_slider_canvas
        width = canvas.winfo_width()
        
        # Calculate clicked percentage
        x = event.x
        pct = max(0, min(100, ((x - 20) / (width - 40)) * 100))
        
        # Find nearest point
        percentages = [0, 10, 15, 25, 30, 50, 65, 75, 85, 95, 100]
        nearest = min(percentages, key=lambda p: abs(p - pct))
        
        self.on_video_slider_point_click(nearest)

    def on_video_slider_point_click(self, percentage):
        """Click on a specific point"""
        print(f"[SLIDER-CLICK] Clicked on {percentage}%")
        
        if not self.current_video_screenshots:
            print(f"[SLIDER-CLICK] ERROR: No screenshots available")
            return
        
        # Convert percentage to index
        percentages = [0, 10, 15, 25, 30, 50, 65, 75, 85, 95, 100]
        try:
            index = percentages.index(percentage)
            print(f"[SLIDER-CLICK] Percentage {percentage}% maps to index {index}")
        except ValueError:
            print(f"[SLIDER-CLICK] ERROR: Percentage {percentage}% not found in list")
            return
        
        index = min(index, len(self.current_video_screenshots) - 1)
        print(f"[SLIDER-CLICK] Clamped index: {index} (total screenshots: {len(self.current_video_screenshots)})")
        
        self.current_screenshot_index = index
        
        # Load and display screenshot
        try:
            screenshot_path = self.current_video_screenshots[index]
            print(f"[SLIDER-CLICK] Loading screenshot: {screenshot_path}")
            print(f"[SLIDER-CLICK] File exists: {os.path.exists(screenshot_path)}")
            
            img = Image.open(screenshot_path)
            print(f"[SLIDER-CLICK] Image loaded, size: {img.size}")
            
            self.current_image_pil = img
            
            # FIX: Call resize_and_display_image() to convert PIL to PhotoImage
            self.resize_and_display_image()
            print(f"[SLIDER-CLICK] Image converted to PhotoImage and displayed")
            
            # Update label
            self.video_slider_label.config(text=f"{percentage}%")
            print(f"[SLIDER-CLICK] Label updated to {percentage}%")
            
            # Redraw slider with highlighted point
            self.draw_video_slider()
            
        except Exception as e:
            print(f"[SLIDER-CLICK] ERROR displaying screenshot: {e}")
            import traceback
            traceback.print_exc()

    def browse_folder(self):
        """Browse for camera folder"""
        folder = filedialog.askdirectory(title="Select Camera Folder")
        if folder:
            self.base_path.set(folder)
            self.save_config()

    def start_scan(self):
        """Start folder scan in background thread"""
        base_path = self.base_path.get()
        
        if not base_path or not os.path.exists(base_path):
            messagebox.showerror("Error", "Select a valid folder")
            return

        self.status_var.set("Scanning...")
        self.root_files.clear()
        self.year_files.clear()
        
        # Start thread
        thread = threading.Thread(target=self.scan_folder, args=(base_path,), daemon=True)
        thread.start()

    def scan_folder(self, base_path):
        """Scan folder for files (runs in background thread)"""
        print(f"\n[SCAN] ========== Starting folder scan ==========")
        print(f"[SCAN] Base path: {base_path}")
        
        try:
            root_files = []
            year_files = {}
            duplicates_count = 0
            
            # Create !duplicate folder if needed
            duplicate_folder = os.path.join(base_path, '!duplicate')
            os.makedirs(duplicate_folder, exist_ok=True)
            print(f"[SCAN] Duplicate folder: {duplicate_folder}")

            # Scan root only (not recursive)
            print(f"[SCAN] Scanning root directory...")
            files_found = 0
            for filename in os.listdir(base_path):
                filepath = os.path.join(base_path, filename)
                
                # Skip directories and special files
                if os.path.isdir(filepath):
                    continue
                
                ext = os.path.splitext(filename)[1].lower()
                if ext not in (self.image_extensions | self.video_extensions):
                    continue

                files_found += 1

                # Extract year from filename
                match = re.search(r'(20\d{2})', filename)
                if match:
                    year = match.group(1)
                    
                    # Index year folders if not done
                    if year not in year_files:
                        year_files[year] = set()
                        year_folder = os.path.join(base_path, year)
                        if os.path.exists(year_folder):
                            print(f"[SCAN] Indexing year folder: {year}")
                            # Scan recursively for existing files
                            for root, dirs, files in os.walk(year_folder):
                                year_files[year].update(files)
                            print(f"[SCAN] Year {year} has {len(year_files[year])} existing files")
                    
                    # Check for duplicates
                    if filename in year_files[year]:
                        # Duplicate found - move to !duplicate
                        print(f"[SCAN] DUPLICATE found: {filename}")
                        try:
                            dest_path = os.path.join(duplicate_folder, filename)
                            # Handle name collision
                            counter = 1
                            while os.path.exists(dest_path):
                                name, ext = os.path.splitext(filename)
                                dest_path = os.path.join(duplicate_folder, f"{name}_{counter}{ext}")
                                counter += 1
                            shutil.move(filepath, dest_path)
                            duplicates_count += 1
                            print(f"[SCAN] Moved to: {dest_path}")
                            continue
                        except Exception as e:
                            print(f"[SCAN] Error moving duplicate {filename}: {e}")
                
                # Extract datetime for sorting
                datetime_obj = None
                dt_match = re.search(r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', filename)
                if dt_match:
                    try:
                        datetime_obj = datetime(
                            int(dt_match.group(1)), int(dt_match.group(2)), int(dt_match.group(3)),
                            int(dt_match.group(4)), int(dt_match.group(5)), int(dt_match.group(6))
                        )
                    except:
                        pass
                
                root_files.append({
                    'filename': filename,
                    'filepath': filepath,
                    'ext': ext,
                    'datetime': datetime_obj
                })
            
            print(f"[SCAN] Total files found: {files_found}")
            print(f"[SCAN] Files to organize: {len(root_files)}")
            print(f"[SCAN] Duplicates moved: {duplicates_count}")
            
            # Sort by datetime
            root_files.sort(key=lambda x: x['datetime'] if x['datetime'] else datetime.min)
            print(f"[SCAN] Files sorted by datetime")
            
            # Send result to main thread
            self.queue.put(('done', {
                'root_files': root_files,
                'year_files': year_files,
                'duplicates_count': duplicates_count
            }))
            
            print(f"[SCAN] ========== Scan complete ==========\n")
            
        except Exception as e:
            print(f"[SCAN] ERROR: {e}")
            import traceback
            traceback.print_exc()
            self.queue.put(('error', str(e)))

    def check_queue(self):
        """Check for messages from background thread"""
        try:
            msg_type, data = self.queue.get_nowait()

            if msg_type == 'done':
                self.root_files = data['root_files']
                self.year_files = data['year_files']
                
                self.update_ui()
                
                msg = f"Scan completed: {len(self.root_files)} files to organize"
                if data['duplicates_count'] > 0:
                    msg += f"\n{data['duplicates_count']} duplicates moved to !duplicate"
                
                self.status_var.set(msg)
                messagebox.showinfo("Scan completed", msg)
            
            elif msg_type == 'error':
                messagebox.showerror("Error", f"Scan error: {data}")
                self.status_var.set("Error during scan")
                
        except queue.Empty:
            pass
        
        # Check again after 100ms
        self.root.after(100, self.check_queue)

    def on_tree_select(self, event):
        """File selected in TreeView"""
        selection = self.tree.selection()
        if not selection:
            return

        # Take first selected for display
        item_id = selection[0]
        values = self.tree.item(item_id, 'values')
        filename = values[0]  # Original name
        year = values[1]
        
        # Refresh folder listbox for this year
        if year:
            self.refresh_folders_listbox(year)
        
        # Find corresponding file
        for file_info in self.root_files:
            if file_info['filename'] == filename:
                self.current_filepath = file_info['filepath']
                self.zoom_level = 1.0  # Reset zoom
                self.display_media(file_info)
                break

    def on_tree_double_click(self, event):
        """Double-click to edit cell (Year only)"""
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        column = self.tree.identify_column(event.x)
        row_id = self.tree.identify_row(event.y)
        
        if not row_id:
            return

        # Editable column: year (#2) only
        if column != '#2':
            return

        # Get current value
        values = self.tree.item(row_id, 'values')
        filename = values[0]
        col_index = int(column[1]) - 1
        current_value = values[col_index]

        # Create edit popup
        popup = tk.Toplevel(self.root)
        popup.title("Edit Year")
        popup.geometry("300x100")
        popup.transient(self.root)
        popup.grab_set()

        ttk.Label(popup, text="Year:").pack(pady=5)
        
        entry_var = tk.StringVar(value=current_value)
        entry = ttk.Entry(popup, textvariable=entry_var, width=40)
        entry.pack(pady=5)
        entry.focus()
        entry.select_range(0, tk.END)

        def save():
            new_value = entry_var.get().strip()
            values_list = list(values)
            values_list[col_index] = new_value
            
            # Update file_data (year)
            self.file_data[filename]['year'] = new_value
            
            # Recalculate final path
            self.update_path_final(filename, values_list)
            
            self.tree.item(row_id, values=values_list)
            
            # Save
            self.save_edits()
            
            popup.destroy()
            self.tree.focus_set()
            
            # Refresh folder listbox if year changed
            if new_value:
                self.refresh_folders_listbox(new_value)

        ttk.Button(popup, text="OK", command=save).pack(pady=5)
        entry.bind('<Return>', lambda e: save())
        entry.bind('<Escape>', lambda e: popup.destroy())

    def display_media(self, file_info):
        """Display image or video"""
        filepath = file_info['filepath']
        filename = file_info['filename']
        ext = file_info['ext']

        print(f"\n[DISPLAY] ========== Displaying media ==========")
        print(f"[DISPLAY] Filename: {filename}")
        print(f"[DISPLAY] Extension: {ext}")
        print(f"[DISPLAY] Path: {filepath}")

        self.file_label.configure(text=filename)

        if ext in self.video_extensions:
            print(f"[DISPLAY] Type: VIDEO")
            
            # Reset
            self.current_video_screenshots = []
            print(f"[DISPLAY] Reset current_video_screenshots")
            
            # Extract screenshots
            self.canvas.delete("all")
            self.canvas.create_text(
                self.canvas.winfo_width()//2, 
                self.canvas.winfo_height()//2,
                text="⏳ Extracting screenshots...",
                fill="white",
                font=('Arial', 12)
            )
            self.root.update()
            print(f"[DISPLAY] Showing 'Extracting...' message")
            
            success = self.extract_video_screenshots(filepath)
            print(f"[DISPLAY] Extraction result: {success}")
            print(f"[DISPLAY] Screenshots count: {len(self.current_video_screenshots)}")
            
            if success and self.current_video_screenshots:
                print(f"[DISPLAY] SUCCESS - Showing slider")
                
                # Show slider
                self.video_slider_frame.pack(fill=tk.X, before=self.file_label, pady=5)
                print(f"[DISPLAY] Slider frame packed")
                
                # Draw slider with points
                self.root.after(100, self.draw_video_slider)  # Wait for canvas to be sized
                print(f"[DISPLAY] Scheduled draw_video_slider in 100ms")
                
                # Display screenshot at 25% by default
                print(f"[DISPLAY] Clicking on 25% point by default")
                self.on_video_slider_point_click(25)
            else:
                print(f"[DISPLAY] FALLBACK - Showing clickable icon")
                
                # Fallback: display clickable icon
                self.canvas.delete("all")
                self.canvas.create_text(
                    self.canvas.winfo_width()//2, 
                    self.canvas.winfo_height()//2,
                    text="▶️ Video\nDouble-click to play",
                    fill="white",
                    font=('Arial', 16, 'bold'),
                    tags="video_icon"
                )
                self.canvas.tag_bind("video_icon", "<Double-1>", 
                                    lambda e: self.play_video(filepath))
                # Hide slider
                self.video_slider_frame.pack_forget()
                print(f"[DISPLAY] Slider frame hidden")
            
        elif ext in self.image_extensions:
            print(f"[DISPLAY] Type: IMAGE")
            
            # Hide slider for images
            self.video_slider_frame.pack_forget()
            self.current_video_screenshots = []
            print(f"[DISPLAY] Slider hidden, screenshots cleared")
            
            self.display_image(filepath)
        
        print(f"[DISPLAY] ========== Display complete ==========\n")

    def display_image(self, filepath):
        """Display image"""
        try:
            image = Image.open(filepath)
            self.current_image_pil = image
            self.resize_and_display_image()
        except Exception as e:
            self.canvas.delete("all")
            self.canvas.create_text(
                self.canvas.winfo_width()//2,
                self.canvas.winfo_height()//2,
                text=f"❌ Error\n{str(e)}",
                fill="red",
                font=('Arial', 10)
            )

    def resize_and_display_image(self):
        """Resize and display image with zoom"""
        if not hasattr(self, 'current_image_pil') or self.current_image_pil is None:
            return

        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        if canvas_width <= 1 or canvas_height <= 1:
            return

        img = self.current_image_pil
        img_width, img_height = img.size

        # Calculate scale to fit canvas
        scale = min(canvas_width / img_width, canvas_height / img_height)
        
        # Apply zoom
        scale *= self.zoom_level
        
        new_width = int(img_width * scale)
        new_height = int(img_height * scale)

        if new_width > 0 and new_height > 0:
            resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            self.current_image = ImageTk.PhotoImage(resized)
            
            self.redraw_image()

    def redraw_image(self):
        """Redraw image on canvas"""
        if self.current_image:
            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()

            x = canvas_width // 2
            y = canvas_height // 2

            self.canvas.delete("all")
            self.canvas.create_image(x, y, image=self.current_image, anchor=tk.CENTER)

    def extract_video_screenshots(self, video_path):
        """Extract video screenshots at different percentages"""
        print(f"\n[EXTRACT] ========== Starting video screenshot extraction ==========")
        print(f"[EXTRACT] Video path: {video_path}")
        print(f"[EXTRACT] File exists: {os.path.exists(video_path)}")
        
        try:
            import subprocess
            
            # Create cache folder if needed
            if not self.video_cache_dir:
                base = self.base_path.get()
                self.video_cache_dir = os.path.join(base, '!tempvideoscreen')
                os.makedirs(self.video_cache_dir, exist_ok=True)
                print(f"[EXTRACT] Created cache dir: {self.video_cache_dir}")
            else:
                print(f"[EXTRACT] Using cache dir: {self.video_cache_dir}")
            
            # Hash file for unique name
            video_hash = str(abs(hash(video_path)))[-8:]
            print(f"[EXTRACT] Video hash: {video_hash}")
            
            # Check if already cached
            cache_pattern = os.path.join(self.video_cache_dir, f"{video_hash}_*.jpg")
            import glob
            existing = sorted(glob.glob(cache_pattern))
            print(f"[EXTRACT] Found {len(existing)} existing cached screenshots")
            
            if len(existing) >= 11:  # Already extracted
                print(f"[EXTRACT] Using cached screenshots:")
                for i, path in enumerate(existing):
                    print(f"[EXTRACT]   {i}: {os.path.basename(path)}")
                self.current_video_screenshots = existing
                return True
            
            print(f"[EXTRACT] Need to extract new screenshots")
            
            # Get video duration
            print(f"[EXTRACT] Getting video duration with ffprobe...")
            cmd_duration = [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path
            ]
            print(f"[EXTRACT] Command: {' '.join(cmd_duration)}")
            
            result = subprocess.run(cmd_duration, capture_output=True, text=True, timeout=10, 
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            
            print(f"[EXTRACT] ffprobe return code: {result.returncode}")
            print(f"[EXTRACT] ffprobe stdout: {result.stdout}")
            print(f"[EXTRACT] ffprobe stderr: {result.stderr}")
            
            duration = float(result.stdout.strip())
            print(f"[EXTRACT] Video duration: {duration} seconds")
            
            # Percentages to extract
            percentages = [0, 10, 15, 25, 30, 50, 65, 75, 85, 95, 100]
            self.current_video_screenshots = []
            
            print(f"[EXTRACT] Extracting {len(percentages)} screenshots...")
            
            for idx, pct in enumerate(percentages):
                timestamp = (duration * pct) / 100
                # Avoid exceeding end
                if pct == 100:
                    timestamp = max(0, duration - 0.5)
                
                output_path = os.path.join(self.video_cache_dir, f"{video_hash}_{pct:03d}.jpg")
                
                print(f"[EXTRACT] [{idx+1}/{len(percentages)}] Extracting {pct}% (t={timestamp:.2f}s) -> {os.path.basename(output_path)}")
                
                cmd_extract = [
                    'ffmpeg', '-ss', str(timestamp),
                    '-i', video_path,
                    '-vframes', '1',
                    '-q:v', '2',
                    '-y',  # Overwrite
                    output_path
                ]
                
                result = subprocess.run(cmd_extract, capture_output=True, timeout=10,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                
                if result.returncode != 0:
                    print(f"[EXTRACT] WARNING: ffmpeg returned code {result.returncode}")
                    print(f"[EXTRACT] stderr: {result.stderr.decode('utf-8', errors='ignore')[:200]}")
                
                if os.path.exists(output_path):
                    file_size = os.path.getsize(output_path)
                    print(f"[EXTRACT] ✓ Screenshot created: {file_size} bytes")
                    self.current_video_screenshots.append(output_path)
                else:
                    print(f"[EXTRACT] ✗ Screenshot NOT created!")
            
            print(f"[EXTRACT] Extraction complete: {len(self.current_video_screenshots)}/{len(percentages)} screenshots")
            print(f"[EXTRACT] Screenshots list:")
            for i, path in enumerate(self.current_video_screenshots):
                print(f"[EXTRACT]   {i}: {os.path.basename(path)}")
            
            print(f"[EXTRACT] ========== Extraction finished ==========\n")
            return len(self.current_video_screenshots) > 0
            
        except Exception as e:
            print(f"[EXTRACT] ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False

    def on_mouse_wheel(self, event):
        """Zoom with Ctrl+Wheel"""
        if event.delta > 0:
            self.zoom_level *= 1.1
        else:
            self.zoom_level *= 0.9
        
        # Limit zoom
        self.zoom_level = max(0.1, min(self.zoom_level, 10.0))
        
        self.resize_and_display_image()

    def on_canvas_resize(self, event):
        """Canvas resized"""
        if hasattr(self, 'current_image_pil') and self.current_image_pil is not None:
            self.resize_and_display_image()

    def play_video(self, filepath):
        """Play video"""
        try:
            if os.path.exists(self.mpc_hc_path):
                os.startfile(filepath, 'open')
            else:
                os.startfile(filepath)
        except Exception as e:
            messagebox.showerror("Error", f"Cannot play video:\n{e}")

    def update_ui(self):
        """Update interface"""
        # Load previous edits
        saved_edits = self.load_edits()
        
        # Update tree
        self.tree.delete(*self.tree.get_children())
        self.file_data.clear()

        for file_info in self.root_files:
            filename = file_info['filename']
            
            # Extract year
            match = re.search(r'(20\d{2})', filename)
            year = match.group(1) if match else ""
            
            # Display original name (no formatting)
            display_name = filename
            
            # Retrieve saved edit if exists
            folder_name = saved_edits.get(filename, '')
            
            # Initialize data
            self.file_data[filename] = {
                'year': year,
                'folder_name': folder_name,
                'path_final': ''
            }
            
            # Create row
            item_id = self.tree.insert('', 'end', values=(display_name, year, folder_name, ''))
            
            # Calculate final path if folder_name exists
            if folder_name:
                values = [display_name, year, folder_name, '']
                self.update_path_final(filename, values)
                self.tree.item(item_id, values=values)
                
                # Apply color (will be assigned by listbox)
                self.apply_folder_color(item_id, folder_name)
        
        # Select first row and set focus
        all_items = self.tree.get_children()
        if all_items:
            first_item = all_items[0]
            self.tree.selection_set(first_item)
            self.tree.focus(first_item)
            self.tree.see(first_item)
            self.on_tree_select(None)  # Display in viewer
        
        # Set focus on TreeView
        self.tree.focus_set()

    def update_path_final(self, filename, values):
        """Calculate final path"""
        year = values[1]
        folder_name = values[2]
        
        if folder_name:
            # folder_name already contains everything (e.g., "2024-08-15 Vacation")
            path_final = f"\\{year}\\{folder_name}\\{filename}"
            self.file_data[filename]['path_final'] = path_final
            values[3] = path_final
        else:
            # If no folder name, suggest adding one
            values[3] = "⚠️ Add folder name"

    def auto_screenshots(self):
        """Auto-organize screenshots and screen recorder"""
        if not self.root_files:
            messagebox.showinfo("Info", "No files to organize")
            return

        count = 0
        for file_info in self.root_files[:]:
            filename = file_info['filename']
            
            # Check if screenshot or screen recorder
            is_screenshot = 'screenshot' in filename.lower()
            is_recorder = 'screen' in filename.lower() and 'recorder' in filename.lower()
            
            if not (is_screenshot or is_recorder):
                continue
            
            # Extract year
            match = re.search(r'(20\d{2})', filename)
            if not match:
                continue
            
            year = match.group(1)
            
            # Determine target folder
            if is_screenshot:
                folder_name = f"!Screenshots_{year}"
            else:
                folder_name = f"!ScreenRecorder_{year}"
            
            # Create folder
            base = self.base_path.get()
            year_folder = os.path.join(base, year)
            target_folder = os.path.join(year_folder, folder_name)
            
            try:
                os.makedirs(target_folder, exist_ok=True)
                
                # Move file
                dest_path = os.path.join(target_folder, filename)
                shutil.move(file_info['filepath'], dest_path)
                
                # Remove from list
                self.root_files.remove(file_info)
                count += 1
                
            except Exception as e:
                print(f"Error moving {filename}: {e}")
        
        self.update_ui()
        messagebox.showinfo("Auto-organize", f"{count} file(s) automatically organized")

    def apply_changes(self):
        """Apply file moves"""
        if not self.root_files:
            messagebox.showinfo("Info", "No files to apply")
            return

        base = self.base_path.get()
        moved = 0
        errors = []

        for file_info in self.root_files[:]:
            filename = file_info['filename']
            
            if filename not in self.file_data:
                continue
            
            data = self.file_data[filename]
            
            if not data.get('path_final') or data['path_final'].startswith('⚠️'):
                continue
            
            # Build full path
            year = data['year']
            folder_name = data['folder_name']
            
            year_folder = os.path.join(base, year)
            target_folder = os.path.join(year_folder, folder_name)
            target_path = os.path.join(target_folder, filename)
            
            try:
                # Create folders
                os.makedirs(target_folder, exist_ok=True)
                
                # Handle collision
                final_path = target_path
                counter = 1
                while os.path.exists(final_path):
                    name, ext = os.path.splitext(filename)
                    final_path = os.path.join(target_folder, f"{name}_{counter}{ext}")
                    counter += 1
                
                # Move file
                shutil.move(file_info['filepath'], final_path)
                
                # Remove from list
                self.root_files.remove(file_info)
                moved += 1
                
            except Exception as e:
                errors.append(f"{filename}: {e}")
        
        self.update_ui()
        
        msg = f"{moved} file(s) moved"
        if errors:
            msg += f"\n{len(errors)} error(s)"
        
        messagebox.showinfo("Apply", msg)

    def delete_selected(self):
        """Delete selected files and select next"""
        selection = self.tree.selection()
        if not selection:
            return

        filenames = []
        item_ids = []
        for item_id in selection:
            values = self.tree.item(item_id, 'values')
            filename = values[0]  # Original name
            
            filenames.append(filename)
            item_ids.append(item_id)

        deleted = 0
        errors = 0

        # Remember index of first selected item
        first_item = item_ids[0]
        all_items = self.tree.get_children()
        first_index = all_items.index(first_item) if first_item in all_items else 0

        for filename in filenames:
            try:
                # Find file
                for file_info in self.root_files[:]:
                    if file_info['filename'] == filename:
                        filepath = file_info['filepath']
                        
                        # Normalize path for send2trash (avoid \\?\ issues)
                        normalized_path = os.path.normpath(filepath)
                        
                        # Send to trash
                        try:
                            from send2trash import send2trash
                            send2trash(normalized_path)
                        except ImportError:
                            # Fallback if send2trash not installed
                            os.remove(normalized_path)
                        except Exception as e:
                            # If send2trash fails, try direct delete
                            print(f"send2trash failed, direct delete: {e}")
                            os.remove(normalized_path)
                        
                        self.root_files.remove(file_info)
                        
                        # Remove from file_data too
                        if filename in self.file_data:
                            del self.file_data[filename]
                        
                        deleted += 1
                        break
            except Exception as e:
                print(f"Error deleting {filename}: {e}")
                errors += 1

        # Delete rows from TreeView WITHOUT rebuilding all
        for item_id in item_ids:
            self.tree.delete(item_id)
        
        # Select next file
        all_items = self.tree.get_children()
        if all_items:
            # Select at previous index, or last if overflow
            next_index = min(first_index, len(all_items) - 1)
            next_item = all_items[next_index]
            self.tree.selection_set(next_item)
            self.tree.focus(next_item)
            self.tree.see(next_item)
            # Trigger display
            self.on_tree_select(None)
        
        # Set focus back on TreeView
        self.tree.focus_set()
        
        # Discreet message in status bar
        self.status_var.set(f"🗑️ {deleted} file(s) deleted" + (f" - {errors} error(s)" if errors > 0 else ""))

    def reset_tree(self):
        """Reset tree"""
        if messagebox.askyesno("Confirmation", "Reset all fields?"):
            self.update_ui()

    def refresh_folders_listbox(self, year=None):
        """Refresh listbox with folders for specified year"""
        self.folders_listbox.delete(0, tk.END)
        
        if not year:
            self.folders_year_label.configure(text="📁 Folders")
            return
        
        # Update label
        self.folders_year_label.configure(text=f"📁 Folders {year}")
        
        # Get folders for this year only
        base = self.base_path.get()
        year_folder = os.path.join(base, year)
        
        if not os.path.exists(year_folder):
            return
        
        folders = []
        try:
            for item in os.listdir(year_folder):
                item_path = os.path.join(year_folder, item)
                if os.path.isdir(item_path) and not item.startswith('!'):
                    folders.append(item)
        except Exception as e:
            print(f"Error reading {year_folder}: {e}")
        
        # Add to listbox sorted, and assign colors
        for folder in sorted(folders):
            # Assign color if not already assigned
            if folder not in self.folder_colors:
                self.folder_colors[folder] = self.generate_color_from_name(folder)
            
            # Add to listbox
            self.folders_listbox.insert(tk.END, folder)
            
            # Color the item (Tkinter Listbox doesn't support per-item colors natively)
            # Workaround: use itemconfig with bg
            idx = self.folders_listbox.size() - 1
            color = self.folder_colors[folder]
            self.folders_listbox.itemconfig(idx, bg=color)

    def on_folder_select(self, event):
        """When clicking a folder, apply to selected rows"""
        selection = self.folders_listbox.curselection()
        if not selection:
            return
        
        folder_name = self.folders_listbox.get(selection[0])
        
        # Apply to selected TreeView rows
        tree_selection = self.tree.selection()
        if not tree_selection:
            messagebox.showinfo("Info", "Select files to organize first")
            self.tree.focus_set()
            return
        
        count = 0
        for item_id in tree_selection:
            values = list(self.tree.item(item_id, 'values'))
            filename = values[0]
            
            # Apply folder name
            values[2] = folder_name
            
            # Update file_data
            if filename in self.file_data:
                self.file_data[filename]['folder_name'] = folder_name
                
                # Recalculate final path
                self.update_path_final(filename, values)
                
                # Apply color (from listbox-defined color)
                self.apply_folder_color(item_id, folder_name)
                
                # Update display
                self.tree.item(item_id, values=values)
                count += 1
        
        # Save edits
        self.save_edits()
        
        self.status_var.set(f"📁 {count} file(s) → {folder_name}")
        
        # Set focus back on TreeView
        self.tree.focus_set()

    def create_new_folder(self):
        """Create new folder physically and apply it"""
        folder_name = self.new_folder_var.get().strip()
        
        if not folder_name:
            messagebox.showwarning("Warning", "Enter a folder name")
            return
        
        # Check selected files
        tree_selection = self.tree.selection()
        if not tree_selection:
            messagebox.showinfo("Info", "Select files to organize first")
            self.tree.focus_set()
            return
        
        # Get year from first selected file
        first_item = tree_selection[0]
        values = self.tree.item(first_item, 'values')
        year = values[1]
        
        if not year:
            messagebox.showerror("Error", "Cannot determine year")
            return
        
        # Create folder physically
        base = self.base_path.get()
        year_folder = os.path.join(base, year)
        new_folder_path = os.path.join(year_folder, folder_name)
        
        try:
            # Create year folder if needed
            os.makedirs(year_folder, exist_ok=True)
            
            # Create new folder
            if not os.path.exists(new_folder_path):
                os.makedirs(new_folder_path)
                self.status_var.set(f"✨ Folder created: {folder_name}")
            else:
                self.status_var.set(f"📁 Folder already exists: {folder_name}")
            
            # Assign color to new folder
            if folder_name not in self.folder_colors:
                self.folder_colors[folder_name] = self.generate_color_from_name(folder_name)
            
            # Apply to selected files
            count = 0
            for item_id in tree_selection:
                values = list(self.tree.item(item_id, 'values'))
                filename = values[0]
                
                # Apply folder name
                values[2] = folder_name
                
                # Update file_data
                if filename in self.file_data:
                    self.file_data[filename]['folder_name'] = folder_name
                    
                    # Recalculate final path
                    self.update_path_final(filename, values)
                    
                    # Apply color
                    self.apply_folder_color(item_id, folder_name)
                    
                    # Update display
                    self.tree.item(item_id, values=values)
                    count += 1
            
            # Save edits
            self.save_edits()
            
            # Refresh listbox for this year
            self.refresh_folders_listbox(year)
            
            # Clear field
            self.new_folder_var.set('')
            
            self.status_var.set(f"✨ Created and applied to {count} file(s): {folder_name}")
            
            # Set focus back on TreeView
            self.tree.focus_set()
            
        except Exception as e:
            messagebox.showerror("Error", f"Cannot create folder: {e}")

    def generate_color_from_name(self, name):
        """Generate pastel color from name"""
        if not name:
            return None
        
        # Hash name to generate stable color
        hash_value = hash(name)
        
        # Generate pastel colors (fixed saturation and lightness)
        import random
        random.seed(hash_value)
        
        # HSL: Variable Hue, Saturation 40%, Lightness 90%
        hue = random.randint(0, 360)
        
        # Convert HSL to RGB
        def hsl_to_rgb(h, s, l):
            c = (1 - abs(2 * l - 1)) * s
            x = c * (1 - abs((h / 60) % 2 - 1))
            m = l - c / 2
            
            if h < 60:
                r, g, b = c, x, 0
            elif h < 120:
                r, g, b = x, c, 0
            elif h < 180:
                r, g, b = 0, c, x
            elif h < 240:
                r, g, b = 0, x, c
            elif h < 300:
                r, g, b = x, 0, c
            else:
                r, g, b = c, 0, x
            
            return int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)
        
        r, g, b = hsl_to_rgb(hue, 0.4, 0.9)
        return f'#{r:02x}{g:02x}{b:02x}'

    def apply_folder_color(self, item_id, folder_name):
        """Apply color to row based on folder name"""
        if not folder_name:
            self.tree.item(item_id, tags=())
            return
        
        # Get color for this folder (must already be assigned by listbox)
        if folder_name not in self.folder_colors:
            self.folder_colors[folder_name] = self.generate_color_from_name(folder_name)
        
        tag_name = f'folder_{folder_name}'
        
        # Configure tag with color (every time, no problem)
        color = self.folder_colors[folder_name]
        self.tree.tag_configure(tag_name, background=color)
        
        # Apply tag to row
        self.tree.item(item_id, tags=(tag_name,))

    def save_edits(self):
        """Save edits to cache file"""
        try:
            edits = {}
            for filename, data in self.file_data.items():
                if data.get('folder_name'):
                    edits[filename] = data['folder_name']
            
            with open(self.edits_cache_file, 'w', encoding='utf-8') as f:
                json.dump(edits, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving edits: {e}")

    def load_edits(self):
        """Load saved edits"""
        try:
            if os.path.exists(self.edits_cache_file):
                with open(self.edits_cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading edits: {e}")
        
        return {}

    def check_duplicates(self):
        """Check for duplicate files across all folders"""
        print(f"\n[DUPLICATES] ========== Starting duplicate check ==========")
        
        base = self.base_path.get()
        if not os.path.exists(base):
            print(f"[DUPLICATES] ERROR: Camera folder not found: {base}")
            messagebox.showerror("Error", "Camera folder not found")
            return
        
        self.status_var.set("🔍 Scanning for duplicates...")
        self.root.update()
        
        # Build index: filename -> [list of full paths]
        file_index = {}
        screenshot_folders = set()
        organized_folders = set()
        
        print(f"[DUPLICATES] Scanning year folders...")
        
        # Scan all year folders
        years_found = 0
        for item in os.listdir(base):
            item_path = os.path.join(base, item)
            if not os.path.isdir(item_path):
                continue
            
            # Check if it's a year folder
            if re.match(r'^\d{4}$', item):
                years_found += 1
                year_path = item_path
                print(f"[DUPLICATES] Processing year folder: {item}")
                
                # Scan all folders in this year
                folders_in_year = 0
                for folder in os.listdir(year_path):
                    folder_path = os.path.join(year_path, folder)
                    if not os.path.isdir(folder_path):
                        continue
                    
                    folders_in_year += 1
                    
                    # Track folder type
                    if folder.startswith('!Screenshot') or folder.startswith('!ScreenRecorder'):
                        screenshot_folders.add(folder_path)
                        print(f"[DUPLICATES]   Screenshot folder: {folder}")
                    elif not folder.startswith('!'):
                        organized_folders.add(folder_path)
                        print(f"[DUPLICATES]   Organized folder: {folder}")
                    
                    # Index all files in this folder
                    try:
                        files_in_folder = 0
                        for filename in os.listdir(folder_path):
                            filepath = os.path.join(folder_path, filename)
                            if os.path.isfile(filepath):
                                if filename not in file_index:
                                    file_index[filename] = []
                                file_index[filename].append(filepath)
                                files_in_folder += 1
                        print(f"[DUPLICATES]     {files_in_folder} files indexed")
                    except Exception as e:
                        print(f"[DUPLICATES] Error scanning {folder_path}: {e}")
                
                print(f"[DUPLICATES]   Total folders in {item}: {folders_in_year}")
        
        print(f"[DUPLICATES] Years processed: {years_found}")
        print(f"[DUPLICATES] Screenshot folders: {len(screenshot_folders)}")
        print(f"[DUPLICATES] Organized folders: {len(organized_folders)}")
        print(f"[DUPLICATES] Total unique filenames: {len(file_index)}")
        
        # Find duplicates
        auto_delete_count = 0
        conflicts = []  # List of (filename, [paths])
        
        duplicates_found = 0
        for filename, paths in file_index.items():
            if len(paths) < 2:
                continue
            
            duplicates_found += 1
            print(f"[DUPLICATES] Duplicate: {filename} ({len(paths)} copies)")
            
            # Skip if in ignore list
            if filename in self.duplicate_ignore_list:
                print(f"[DUPLICATES]   → IGNORED (in ignore list)")
                continue
            
            # Check if any path is in screenshot folder
            screenshot_paths = [p for p in paths if any(p.startswith(sf) for sf in screenshot_folders)]
            organized_paths = [p for p in paths if any(p.startswith(of) for of in organized_folders)]
            
            print(f"[DUPLICATES]   Screenshot copies: {len(screenshot_paths)}")
            print(f"[DUPLICATES]   Organized copies: {len(organized_paths)}")
            
            if screenshot_paths and organized_paths:
                # AUTO DELETE: Screenshot + Organized → delete screenshot copy
                print(f"[DUPLICATES]   → AUTO DELETE screenshot copies")
                for screenshot_path in screenshot_paths:
                    try:
                        from send2trash import send2trash
                        send2trash(screenshot_path)
                        auto_delete_count += 1
                        print(f"[DUPLICATES]     Deleted: {screenshot_path}")
                    except Exception as e:
                        print(f"[DUPLICATES] Error deleting {screenshot_path}: {e}")
            
            elif len(organized_paths) >= 2:
                # CONFLICT: Multiple organized folders
                print(f"[DUPLICATES]   → CONFLICT (multiple organized folders)")
                conflicts.append((filename, organized_paths))
        
        print(f"[DUPLICATES] Total duplicates found: {duplicates_found}")
        print(f"[DUPLICATES] Auto-deleted: {auto_delete_count}")
        print(f"[DUPLICATES] Conflicts: {len(conflicts)}")
        
        # Show results
        if auto_delete_count > 0:
            self.status_var.set(f"✅ Auto-deleted {auto_delete_count} screenshot duplicates")
        
        if conflicts:
            print(f"[DUPLICATES] Showing conflict dialog...")
            self.show_duplicate_conflicts(conflicts)
        else:
            if auto_delete_count == 0:
                messagebox.showinfo("Check Duplicates", "No duplicates found")
            else:
                messagebox.showinfo("Check Duplicates", 
                                  f"Auto-deleted {auto_delete_count} screenshot duplicates\nNo conflicts found")
        
        print(f"[DUPLICATES] ========== Duplicate check complete ==========\n")

    def show_duplicate_conflicts(self, conflicts):
        """Show UI for handling duplicate conflicts"""
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Duplicate Conflicts ({len(conflicts)} files)")
        dialog.geometry("800x600")
        dialog.transient(self.root)
        
        # Header
        ttk.Label(dialog, text="Files found in multiple organized folders:", 
                  font=('Arial', 12, 'bold')).pack(pady=10)
        
        # Listbox for conflicts
        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        conflict_listbox = tk.Listbox(list_frame, font=('Consolas', 9), height=20)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=conflict_listbox.yview)
        conflict_listbox.configure(yscrollcommand=scrollbar.set)
        
        conflict_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Populate listbox
        for filename, paths in conflicts:
            conflict_listbox.insert(tk.END, f"📄 {filename}")
            for path in paths:
                # Show relative path
                rel_path = os.path.relpath(path, self.base_path.get())
                conflict_listbox.insert(tk.END, f"   → {rel_path}")
            conflict_listbox.insert(tk.END, "")  # Blank line
        
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        def ignore_selected():
            """Add selected files to ignore list"""
            selection = conflict_listbox.curselection()
            ignored_count = 0
            
            for idx in selection:
                text = conflict_listbox.get(idx)
                if text.startswith("📄 "):
                    filename = text[2:].strip()
                    self.duplicate_ignore_list.add(filename)
                    ignored_count += 1
            
            if ignored_count > 0:
                self.save_ignore_list()
                messagebox.showinfo("Ignored", f"Added {ignored_count} file(s) to ignore list")
                dialog.destroy()
        
        def open_folder():
            """Open folder containing selected file"""
            selection = conflict_listbox.curselection()
            if not selection:
                return
            
            idx = selection[0]
            text = conflict_listbox.get(idx)
            
            # Find the file data
            if text.startswith("   → "):
                folder_path = os.path.dirname(os.path.join(self.base_path.get(), text[5:].strip()))
                if os.path.exists(folder_path):
                    os.startfile(folder_path)
        
        ttk.Button(button_frame, text="Ignore Selected", command=ignore_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Open Folder", command=open_folder).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)
        
        # Instructions
        instructions = ttk.Label(dialog, 
                                text="Select files and click 'Ignore Selected' to stop checking them in future scans\n"
                                     "OR manually delete unwanted copies using 'Open Folder' button",
                                foreground="gray")
        instructions.pack(pady=5)


if __name__ == '__main__':
    root = tk.Tk()
    app = TriPhotoApp(root)
    root.mainloop()
