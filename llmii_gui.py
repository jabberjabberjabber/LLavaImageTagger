import sys
import os
import json
import shutil
import base64
import requests
from PyQt6.QtCore import QThread, pyqtSignal, QObject, Qt, QSize
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                           QLabel, QLineEdit, QCheckBox, QPushButton, QFileDialog, 
                           QTextEdit, QGroupBox, QSpinBox, QRadioButton, QButtonGroup,
                           QProgressBar, QTableWidget, QTableWidgetItem, QComboBox,
                           QPlainTextEdit, QScrollArea, QMessageBox, QDialog, QMenuBar,
                           QMenu, QSizePolicy, QSplitter, QFrame)
from PyQt6.QtGui import QPixmap, QImage
from src import llmii, image_processor

# Configuration class for window dimensions and properties
class GuiConfig:
    """ Configuration class for GUI dimensions and properties
        
        This class centralizes all GUI dimension settings to make them
        easy to find and modify.
    """
    # Main window properties
    WINDOW_WIDTH = 704
    WINDOW_HEIGHT = 740
    WINDOW_FIXED = True
    
    # Preview panel dimensions
    IMAGE_PREVIEW_WIDTH = 340
    IMAGE_PREVIEW_HEIGHT = 360
    
    # Metadata panel dimensions
    METADATA_WIDTH = 360
    METADATA_HEIGHT = 360
    
    # Log panel dimensions
    LOG_WIDTH = 700
    LOG_HEIGHT = 250
    
    # Other GUI elements
    CONTROL_PANEL_HEIGHT = 80
    SPLITTER_HANDLE_WIDTH = 4
    
    # Font settings
    FONT_SIZE_NORMAL = 10
    FONT_SIZE_HEADER = 11
    
    # Colors
    COLOR_KEYWORD_BG = "#e1f0ff"
    COLOR_KEYWORD_TEXT = "#0066cc"
    COLOR_KEYWORD_BORDER = "#99ccff"
    COLOR_CAPTION_BG = "#f9f9f9"
    COLOR_BORDER = "#cccccc"
    
    CONTENT_MARGINS = 1
    SPACING = 0
    KEYWORDS_PER_ROW = 4
    FILENAME_LABEL_HEIGHT = 24
    CAPTION_BOX_HEIGHT = 200
    KEYWORDS_BOX_HEIGHT = abs(METADATA_HEIGHT - (FILENAME_LABEL_HEIGHT + CAPTION_BOX_HEIGHT))

class InstructionDialog(QDialog):
    def __init__(self, instruction_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Instruction")
        self.setModal(True)
        self.resize(700, 500)
        
        layout = QVBoxLayout(self)
        
        # Instruction editor
        self.instruction_input = QPlainTextEdit()
        self.instruction_input.setPlainText(instruction_text)
        layout.addWidget(QLabel("Edit Instruction:"))
        layout.addWidget(self.instruction_input)
        
        # Buttons
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
    
    def get_instruction(self):
        return self.instruction_input.toPlainText()

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(600, 450)
        
        layout = QVBoxLayout(self)
        
        # Create a scroll area to handle potential overflow
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        api_layout = QHBoxLayout()
        self.api_url_input = QLineEdit("http://localhost:5001")
        self.api_password_input = QLineEdit()
        api_layout.addWidget(QLabel("API URL:"))
        api_layout.addWidget(self.api_url_input)
        api_layout.addWidget(QLabel("API Password:"))
        api_layout.addWidget(self.api_password_input)
        scroll_layout.addLayout(api_layout)

        system_instruction_layout = QHBoxLayout()
        self.system_instruction_input = QLineEdit("You are a helpful assistant.")
        system_instruction_layout.addWidget(QLabel("System Instruction:"))
        system_instruction_layout.addWidget(self.system_instruction_input)
        scroll_layout.addLayout(system_instruction_layout)

        # Add button to edit instruction text
        instruction_button_layout = QHBoxLayout()
        self.edit_instruction_button = QPushButton("Edit Processing Instruction")
        self.edit_instruction_button.clicked.connect(self.edit_instruction)
        instruction_button_layout.addWidget(self.edit_instruction_button)
        scroll_layout.addLayout(instruction_button_layout)

        caption_group = QGroupBox("Caption Options")
        caption_layout = QVBoxLayout()

        caption_instruction_layout = QHBoxLayout()
        self.caption_instruction_input = QLineEdit("Describe the image.")
        caption_instruction_layout.addWidget(QLabel("Caption Instruction:"))
        caption_instruction_layout.addWidget(self.caption_instruction_input)
        caption_layout.addLayout(caption_instruction_layout)

        self.caption_radio_group = QButtonGroup(self)
        self.detailed_caption_radio = QRadioButton("Generate a detailed caption (takes two LLM queries)")
        self.short_caption_radio = QRadioButton("Generate a short caption (single LLM query)")
        self.no_caption_radio = QRadioButton("Do not add a caption")

        self.caption_radio_group.addButton(self.detailed_caption_radio)
        self.caption_radio_group.addButton(self.short_caption_radio)
        self.caption_radio_group.addButton(self.no_caption_radio)

        self.short_caption_radio.setChecked(True)

        caption_layout.addWidget(self.detailed_caption_radio)
        caption_layout.addWidget(self.short_caption_radio)
        caption_layout.addWidget(self.no_caption_radio)

        caption_group.setLayout(caption_layout)
        scroll_layout.addWidget(caption_group)

        gen_count_layout = QHBoxLayout()
        self.gen_count = QSpinBox()
        self.gen_count.setMinimum(50)
        self.gen_count.setMaximum(1000)
        self.gen_count.setValue(150)
        gen_count_layout.addWidget(QLabel("GenTokens: "))
        gen_count_layout.addWidget(self.gen_count)
        scroll_layout.addLayout(gen_count_layout)
        
        options_group = QGroupBox("File Options")
        options_layout = QVBoxLayout()
        
        self.no_crawl_checkbox = QCheckBox("Don't crawl subdirectories")
        self.reprocess_all_checkbox = QCheckBox("Reprocess all files again")
        self.reprocess_failed_checkbox = QCheckBox("Reprocess previously failed files")
        self.reprocess_orphans_checkbox = QCheckBox("If file has UUID, mark status (recommended)")
        self.no_backup_checkbox = QCheckBox("Don't make backups")
        self.dry_run_checkbox = QCheckBox("Pretend mode / Dry run")
        self.skip_verify_checkbox = QCheckBox("No file checking (not recommended)")
        self.quick_fail_checkbox = QCheckBox("Quick fail (recommended for newer models)")
        
        options_layout.addWidget(self.no_crawl_checkbox)
        options_layout.addWidget(self.reprocess_all_checkbox)
        options_layout.addWidget(self.reprocess_failed_checkbox)
        options_layout.addWidget(self.reprocess_orphans_checkbox)
        options_layout.addWidget(self.no_backup_checkbox)
        options_layout.addWidget(self.dry_run_checkbox)
        options_layout.addWidget(self.skip_verify_checkbox)
        options_layout.addWidget(self.quick_fail_checkbox)
        
        options_group.setLayout(options_layout)
        scroll_layout.addWidget(options_group)
        
        xmp_group = QGroupBox("Metadata Options")
        xmp_layout = QVBoxLayout()
        
        self.update_keywords_checkbox = QCheckBox("Add new keywords to existing keywords")
        self.update_keywords_checkbox.setChecked(True)
        self.update_caption_checkbox = QCheckBox("Add new caption to existing caption with <caption>")
        self.update_caption_checkbox.setChecked(False)
        xmp_layout.addWidget(self.update_keywords_checkbox)
        xmp_layout.addWidget(self.update_caption_checkbox)
        
        xmp_group.setLayout(xmp_layout)
        scroll_layout.addWidget(xmp_group)
        
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)
        
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        # Store the instruction text
        self.instruction_text = """First, generate a detailed caption for the image.

Next, generate at least eight unique one or two word keywords for the image. Include the following when present:

 - Themes, concepts
 - Items, animals, objects
   - Key features, aspects
 - Structures, landmarks, setting
   - Foreground and background elements   
 - Notable colors, textures, styles
 - Actions, activities
 - Human demographics:
   - Physical appearance
   - Age range
   - Apparent ancestry
   - Visible occupation/role
   - Obvious relationships between individuals
   - Clearly conveyed emotions, expressions, body language
   
Limit response to things clearly and obviously apparent; do not guess. Do not combine words. Use ENGLISH only. Generate ONLY a JSON object with the keys Caption and Keywords as follows {"Caption": str, "Keywords": []}"""
        
        self.load_settings()
    
    def edit_instruction(self):
        dialog = InstructionDialog(self.instruction_text, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.instruction_text = dialog.get_instruction()
     
    def load_settings(self):
        try:
            if os.path.exists('settings.json'):
                with open('settings.json', 'r') as f:
                    settings = json.load(f)
                    
                self.api_url_input.setText(settings.get('api_url', 'http://localhost:5001'))
                self.api_password_input.setText(settings.get('api_password', ''))
                self.system_instruction_input.setText(settings.get('system_instruction', 'You are a helpful assistant.'))
                self.gen_count.setValue(settings.get('gen_count', 150))
                
                # Load the instruction text
                default_instruction = """First, generate a detailed caption for the image.

Next, generate at least eight unique one or two word keywords for the image. Include the following when present:

 - Themes, concepts
 - Items, animals, objects
   - Key features, aspects
 - Structures, landmarks, setting
   - Foreground and background elements   
 - Notable colors, textures, styles
 - Actions, activities
 - Human demographics:
   - Physical appearance
   - Age range
   - Apparent ancestry
   - Visible occupation/role
   - Obvious relationships between individuals
   - Clearly conveyed emotions, expressions, body language
   
Limit response to things clearly and obviously apparent; do not guess. Do not combine words. Use ENGLISH only. Generate ONLY a JSON object with the keys Caption and Keywords as follows {"Caption": str, "Keywords": []}"""
                
                self.instruction_text = settings.get('instruction', default_instruction)
                
                self.no_crawl_checkbox.setChecked(settings.get('no_crawl', False))
                self.reprocess_failed_checkbox.setChecked(settings.get('reprocess_failed', False))
                self.reprocess_all_checkbox.setChecked(settings.get('reprocess_all', False))
                self.reprocess_orphans_checkbox.setChecked(settings.get('reprocess_orphans', True))
                self.no_backup_checkbox.setChecked(settings.get('no_backup', False))
                self.dry_run_checkbox.setChecked(settings.get('dry_run', False))
                self.skip_verify_checkbox.setChecked(settings.get('skip_verify', False))
                self.quick_fail_checkbox.setChecked(settings.get('quick_fail', False))
                self.caption_instruction_input.setText(settings.get('caption_instruction', 'Describe the image in detail. Be specific.'))
                
                # Set radio button based on settings
                if settings.get('detailed_caption', False):
                    self.detailed_caption_radio.setChecked(True)
                elif settings.get('no_caption', False):
                    self.no_caption_radio.setChecked(True)
                else:
                    # Default to short caption
                    self.short_caption_radio.setChecked(True)
                    
                self.update_keywords_checkbox.setChecked(settings.get('update_keywords', True))
                self.update_caption_checkbox.setChecked(settings.get('update_caption', False))
                    
        except Exception as e:
            print(f"Error loading settings: {e}")
            
    def save_settings(self):
        settings = {
            'api_url': self.api_url_input.text(),
            'api_password': self.api_password_input.text(),
            'system_instruction': self.system_instruction_input.text(),
            'instruction': self.instruction_text,
            'gen_count': self.gen_count.value(),
            'no_crawl': self.no_crawl_checkbox.isChecked(),
            'reprocess_failed': self.reprocess_failed_checkbox.isChecked(),
            'reprocess_all': self.reprocess_all_checkbox.isChecked(),
            'reprocess_orphans': self.reprocess_orphans_checkbox.isChecked(),
            'no_backup': self.no_backup_checkbox.isChecked(),
            'dry_run': self.dry_run_checkbox.isChecked(),
            'skip_verify': self.skip_verify_checkbox.isChecked(),
            'quick_fail': self.quick_fail_checkbox.isChecked(),
            'update_keywords': self.update_keywords_checkbox.isChecked(),
            'caption_instruction': self.caption_instruction_input.text(),
            'detailed_caption': self.detailed_caption_radio.isChecked(),
            'short_caption': self.short_caption_radio.isChecked(),
            'no_caption': self.no_caption_radio.isChecked(),
            'update_caption': self.update_caption_checkbox.isChecked(),
        }
        
        try:
            with open('settings.json', 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save settings: {e}")

class APICheckThread(QThread):
    api_status = pyqtSignal(bool)
    
    def __init__(self, api_url):
        super().__init__()
        self.api_url = api_url
        self.running = True
        
    def run(self):
        while self.running:
            try:
                # Direct HTTP request to the version endpoint
                response = requests.get(f"{self.api_url}/api/extra/version", timeout=5)
                if response.status_code == 200:
                    self.api_status.emit(True)
                    break
            except Exception:
                self.api_status.emit(False)
            self.msleep(1000)
            
    def stop(self):
        self.running = False
        
class IndexerThread(QThread):
    output_received = pyqtSignal(str)
    image_processed = pyqtSignal(str, str, list, str)  # base64_image, caption, keywords, filename

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.paused = False
        self.stopped = False

    def process_callback(self, message):
        """Callback for llmii's process_file function"""
        # Check if message is a dictionary with image data
        if isinstance(message, dict) and 'type' in message and message['type'] == 'image_data':
            # Extract the image data and emit signal
            base64_image = message.get('base64_image', '')
            caption = message.get('caption', '')
            keywords = message.get('keywords', [])
            file_path = message.get('file_path', '')
            self.image_processed.emit(base64_image, caption, keywords, file_path)
        else:
            # Regular text message for the log
            self.output_received.emit(str(message))

    def run(self):
        try:
            # Pass our callback function to llmii
            llmii.main(self.config, self.process_callback, self.check_paused_or_stopped)
        except Exception as e:
            self.output_received.emit(f"Error: {str(e)}")

    def check_paused_or_stopped(self):
        if self.stopped:
            raise Exception("Indexer stopped by user")
        if self.paused:
            while self.paused and not self.stopped:
                self.msleep(100)
            if self.stopped:
                raise Exception("Indexer stopped by user")
        return self.paused

class KeywordWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.keywords = []
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS)
        
        # Create the container for keyword rows
        self.keywords_container = QWidget()
        self.keywords_layout = QVBoxLayout(self.keywords_container)
        self.keywords_container.setStyleSheet("border: none; padding: 2px")
        self.keywords_layout.setContentsMargins(GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS)
        self.keywords_layout.setSpacing(0)
        self.keywords_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        
        # Set fixed size policy for container
        self.keywords_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        
        # Add header and container to layout
        #self.layout.addWidget(QLabel("Keywords:"))
        self.layout.addWidget(self.keywords_container)
        
        # Ensure widget doesn't expand beyond its allocated space
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    
    def clear(self):
        # Clear keywords layout
        for i in reversed(range(self.keywords_layout.count())): 
            widget = self.keywords_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        self.keywords = []
    
    def set_keywords(self, keywords):
        self.clear()
        self.keywords = keywords
        
        # Display keywords in rows
        max_per_row = GuiConfig.KEYWORDS_PER_ROW
        current_row = 0
        row_layouts = []
        
        # Create the first row
        row_widget = QWidget()
        #row_widget.setFrameStyle(QFrame.Shape.NoFrame)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        row_layouts.append(row_layout)
        self.keywords_layout.addWidget(row_widget)
        
        # Add keyword labels
        for i, keyword in enumerate(keywords):
            # Check if we need to start a new row
            if i > 0 and i % max_per_row == 0:
                # Create a new row
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(0)
                row_layouts.append(row_layout)
                self.keywords_layout.addWidget(row_widget)
                current_row += 1
                
            # Create the keyword label
            keyword_label = QLabel(keyword)
            keyword_label.setStyleSheet(f"""
                background-color: {GuiConfig.COLOR_KEYWORD_BG}; 
                color: {GuiConfig.COLOR_KEYWORD_TEXT};
                padding: 1px 4px;
                border-radius: 5px;
                border: 1px solid {GuiConfig.COLOR_KEYWORD_BORDER};
                margin: 1px;
                font-size: {GuiConfig.FONT_SIZE_NORMAL}px;
            """)
            
            # Add the keyword to the current row
            row_layouts[current_row].addWidget(keyword_label)
        
        # Add stretch to each row to push keywords to the left
        for row_layout in row_layouts:
            row_layout.addStretch(1)

class PauseHandler(QObject):
    pause_signal = pyqtSignal(bool)
    stop_signal = pyqtSignal()

class ImageIndexerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Apply fixed window size

        self.setWindowTitle("Image Indexer GUI")
        self.setFixedSize(GuiConfig.WINDOW_WIDTH, GuiConfig.WINDOW_HEIGHT)
        # Disable maximize button and resizing
        if GuiConfig.WINDOW_FIXED:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)
            self.setFixedSize(GuiConfig.WINDOW_WIDTH, GuiConfig.WINDOW_HEIGHT)
            
        self.settings_dialog = SettingsDialog(self)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS)
        
        # Upper section with controls - fixed height
        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(GuiConfig.SPACING)
        
        # Directory and Settings section
        dir_layout = QHBoxLayout()
        self.dir_input = QLineEdit()
        dir_button = QPushButton("Select Directory")
        dir_button.clicked.connect(self.select_directory)
        dir_layout.addWidget(QLabel("Directory:"))
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(dir_button)
        controls_layout.addLayout(dir_layout)

        # Settings button and API status in one row
        settings_api_layout = QHBoxLayout()
        settings_button = QPushButton("Settings")
        settings_button.clicked.connect(self.show_settings)
        self.api_status_label = QLabel("API Status: Checking...")
        settings_api_layout.addWidget(settings_button)
        settings_api_layout.addStretch(1)
        settings_api_layout.addWidget(self.api_status_label)
        controls_layout.addLayout(settings_api_layout)
        
        # Control buttons
        button_layout = QHBoxLayout()
        self.run_button = QPushButton("Run Image Indexer")
        self.run_button.clicked.connect(self.run_indexer)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.pause_button.setEnabled(False)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_indexer)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.run_button)
        button_layout.addWidget(self.pause_button)
        button_layout.addWidget(self.stop_button)
        controls_layout.addLayout(button_layout)
        
        # Set fixed height for controls widget
        controls_widget.setFixedHeight(GuiConfig.CONTROL_PANEL_HEIGHT)
        main_layout.addWidget(controls_widget)
        nav_widget = QWidget()
        
        nav_layout = QHBoxLayout(nav_widget)
        nav_layout.setContentsMargins(GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS)
        nav_layout.setSpacing(GuiConfig.SPACING)

        # Create navigation buttons
        self.first_button = QPushButton("|<")  # Go to first image
        self.prev_button = QPushButton("<")    # Go to previous image
        self.position_label = QLabel("No images processed")
        self.position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_button = QPushButton(">")    # Go to next image
        self.last_button = QPushButton(">|")   # Go to most recent image

        # Add widgets to layout
        nav_layout.addWidget(self.first_button)
        nav_layout.addWidget(self.prev_button)
        nav_layout.addStretch(1)
        nav_layout.addWidget(self.position_label)
        nav_layout.addStretch(1)
        nav_layout.addWidget(self.next_button)
        nav_layout.addWidget(self.last_button)

        # Connect button signals to slots
        self.first_button.clicked.connect(self.navigate_first)
        self.prev_button.clicked.connect(self.navigate_prev)
        self.next_button.clicked.connect(self.navigate_next)
        self.last_button.clicked.connect(self.navigate_last)

        # Set initial button states (disabled until we have images)
        self.first_button.setEnabled(False)
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.last_button.setEnabled(False)

        # Add to the main layout
        main_layout.addWidget(nav_widget)
        
        # Middle section with image and metadata side by side
        middle_section = QWidget()
        middle_layout = QHBoxLayout(middle_section)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(GuiConfig.SPACING)
        
        # Image preview panel - fixed size
        image_frame = QFrame()
        image_frame.setFrameShape(QFrame.Shape.Box)
        image_frame.setStyleSheet(f"border: 1px solid {GuiConfig.COLOR_BORDER};")
        
        image_layout = QVBoxLayout(image_frame)
        image_layout.setContentsMargins(GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS)
        
        # Image preview label with fixed size
        self.image_preview = QLabel("No image processed yet")
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.image_preview.setFixedSize(GuiConfig.IMAGE_PREVIEW_WIDTH, GuiConfig.IMAGE_PREVIEW_HEIGHT)
        self.image_preview.setFrameShape(QFrame.Shape.NoFrame)
        self.image_preview.setStyleSheet("border: none;")
               
        image_layout.addWidget(self.image_preview, 0, Qt.AlignmentFlag.AlignCenter)
        
        image_frame.setFixedSize(GuiConfig.IMAGE_PREVIEW_WIDTH, GuiConfig.IMAGE_PREVIEW_HEIGHT)
        middle_layout.addWidget(image_frame)
        
        # Metadata panel - fixed size
        metadata_frame = QFrame()
        
        metadata_frame.setFrameShape(QFrame.Shape.Box)
        metadata_frame.setStyleSheet(f"border: 1px solid {GuiConfig.COLOR_BORDER};")
        #metadata_frame.setStyleSheet("")
        metadata_layout = QVBoxLayout(metadata_frame)
        metadata_layout.setContentsMargins(GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS)
        metadata_layout.setSpacing(GuiConfig.SPACING)
        
        # Image filename
        self.filename_label = QLabel("Filename: ")
        self.filename_label.setStyleSheet("font-weight: bold; border:none;")
        self.filename_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.filename_label.setFixedHeight(GuiConfig.FILENAME_LABEL_HEIGHT)
        
        metadata_layout.addWidget(self.filename_label)
        
        # Caption
        caption_group = QGroupBox("Caption")
        caption_group.setStyleSheet("QGroupBox { border: none; }")
        caption_layout = QVBoxLayout(caption_group)
        
        caption_layout.setContentsMargins(GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS)
        caption_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.caption_label = QLabel("No caption generated yet")
        self.caption_label.setWordWrap(True)
        #self.caption_label.setFrameStyle(QFrame.Shape.NoFrame)
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.caption_label.setStyleSheet(f"background-color: {GuiConfig.COLOR_CAPTION_BG}; padding: 4px;")
        
        # Create a scroll area for caption to ensure it fits in fixed space
        caption_scroll = QScrollArea()
        caption_scroll.setWidgetResizable(True)
        caption_scroll.setWidget(self.caption_label)
        #caption_scroll.setAlignment(Qt.AlignmentFlag.AlignTop)
        caption_scroll.setFixedHeight(200)  # Ensure fixed height for caption area
        caption_scroll.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        caption_layout.addWidget(caption_scroll, 0, Qt.AlignmentFlag.AlignTop)
        metadata_layout.addWidget(caption_group, 0, Qt.AlignmentFlag.AlignTop)
        
        # Keywords
        self.keywords_widget = KeywordWidget()
        metadata_layout.addWidget(self.keywords_widget)
        
        # Set fixed size for metadata frame
        metadata_frame.setFixedSize(GuiConfig.METADATA_WIDTH, GuiConfig.METADATA_HEIGHT)
        middle_layout.addWidget(metadata_frame)
        
        # Add middle section to main layout
        main_layout.addWidget(middle_section)
        

        
        # Bottom section - log output with fixed size
        log_frame = QFrame()
        log_frame.setFrameShape(QFrame.Shape.Box)
        log_frame.setFrameStyle(QFrame.Shape.NoFrame)
        #log_frame.setStyleSheet(f"border: 1px solid {GuiConfig.COLOR_BORDER};")
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS, GuiConfig.CONTENT_MARGINS)
        
        log_label = QLabel("Processing Log:")
        log_layout.addWidget(log_label)
        
        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        log_layout.addWidget(self.output_area)
        
        # Set fixed size for log frame
        log_frame.setFixedSize(GuiConfig.LOG_WIDTH, GuiConfig.LOG_HEIGHT)
        main_layout.addWidget(log_frame)
        
        # Store the previous image data to keep showing something
        self.previous_image_data = None
        self.previous_caption = None
        self.previous_keywords = None
        self.previous_filename = None

        self.pause_handler = PauseHandler()
        
        self.api_check_thread = None
        self.api_is_ready = False
        
        self.run_button.setEnabled(False)
        
        self.image_history = []  # [(base64_image, caption, keywords, filename)]
        self.current_position = -1
        
        if os.path.exists('settings.json'):
            try:
                with open('settings.json', 'r') as f:
                    settings = json.load(f)
                    self.dir_input.setText(settings.get('directory', ''))
                    self.start_api_check(settings.get('api_url', 'http://localhost:5001'))
                    
            except Exception as e:
                print(f"Error loading settings: {e}")
                self.start_api_check('http://localhost:5001')
        else:
            self.start_api_check('http://localhost:5001')

    def show_settings(self):
        if self.settings_dialog.exec() == QDialog.DialogCode.Accepted:
            # First save settings from the settings dialog
            self.settings_dialog.save_settings()
            
            # Then update the API check if needed
            self.start_api_check(self.settings_dialog.api_url_input.text())
            
            try:
                with open('settings.json', 'r') as f:
                    settings = json.load(f)
                settings['directory'] = self.dir_input.text()
                with open('settings.json', 'w') as f:
                    json.dump(settings, f, indent=4)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to save directory setting: {e}")

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.dir_input.setText(directory)

    def start_api_check(self, api_url):
        self.api_url = api_url
        if self.api_check_thread and self.api_check_thread.isRunning():
            self.api_check_thread.stop()
            self.api_check_thread.wait()
            
        self.api_is_ready = False
        self.run_button.setEnabled(False)
        self.api_status_label.setText("API Status: Checking...")
        self.api_status_label.setStyleSheet("color: orange; padding: 4px")

        
        self.api_check_thread = APICheckThread(api_url if api_url else self.settings_dialog.api_url_input.text())
        self.api_check_thread.api_status.connect(self.update_api_status)
        self.api_check_thread.start()

    def update_api_status(self, is_available):
        if is_available:
            self.api_is_ready = True
            self.api_status_label.setText("API Status: Connected")
            self.api_status_label.setStyleSheet("color: green; padding: 4px")
            self.run_button.setEnabled(True)
            
            # Stop the check thread once we're connected
            if self.api_check_thread:
                self.api_check_thread.stop()
        else:
            self.api_is_ready = False
            self.api_status_label.setText("API Status: Waiting for connection...")
            self.api_status_label.setStyleSheet("color: red padding: 4px")
            self.run_button.setEnabled(False)
    
    def update_image_preview(self, base64_image, caption, keywords, filename):
        # Store current image as previous (existing code)
        self.previous_image_data = base64_image
        self.previous_caption = caption
        self.previous_keywords = keywords
        self.previous_filename = filename
        
        # Add to history
        self.image_history.append((base64_image, caption, keywords, filename))
        
        # If user was viewing the most recent image (or this is the first image),
        # update current_position to point to the new image
        if self.current_position == -1 or len(self.image_history) <= 1:
            self.current_position = -1  # Keep at most recent
            self.display_image(base64_image, caption, keywords, filename)
        else:
            # Just update navigation buttons without changing the view
            self.update_navigation_buttons()
            
    def display_image(self, base64_image, caption, keywords, filename):
        # Update the UI with the image data
        try:
            # Convert base64 to QImage
            image_data = base64.b64decode(base64_image)
            image = QImage.fromData(image_data)
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                
                # Scale the pixmap to fit the fixed container while maintaining aspect ratio
                scaled_pixmap = pixmap.scaled(
                    GuiConfig.IMAGE_PREVIEW_WIDTH,
                    GuiConfig.IMAGE_PREVIEW_HEIGHT, 
                    Qt.AspectRatioMode.KeepAspectRatio, 
                    Qt.TransformationMode.SmoothTransformation
                )
                
                # Set the pixmap
                self.image_preview.setPixmap(scaled_pixmap)
                
                # Center the pixmap in the label
                self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                self.image_preview.setText("Error loading image")
        except Exception as e:
            self.image_preview.setText(f"Error: {str(e)}")
        
        # Update filename, caption and keywords
        file_basename = os.path.basename(filename)
        self.filename_label.setText(f"Filename: {file_basename}")
        self.caption_label.setText(caption or "No caption generated")
        self.keywords_widget.set_keywords(keywords or [])
        
        # Update navigation buttons and position indicator
        self.update_navigation_buttons()

    def navigate_first(self):
        if self.image_history:
            self.current_position = 0
            base64_image, caption, keywords, filename = self.image_history[0]
            self.display_image(base64_image, caption, keywords, filename)

    def navigate_prev(self):
        if not self.image_history:
            return
            
        if self.current_position == -1:
            # If at the most recent, go to the second most recent
            if len(self.image_history) > 1:
                self.current_position = len(self.image_history) - 2
                base64_image, caption, keywords, filename = self.image_history[self.current_position]
                self.display_image(base64_image, caption, keywords, filename)
        elif self.current_position > 0:
            self.current_position -= 1
            base64_image, caption, keywords, filename = self.image_history[self.current_position]
            self.display_image(base64_image, caption, keywords, filename)

    def navigate_next(self):
        if not self.image_history:
            return
            
        if self.current_position != -1 and self.current_position < len(self.image_history) - 1:
            self.current_position += 1
            
            # If we've reached the end, set to -1 to indicate "most recent"
            if self.current_position == len(self.image_history) - 1:
                self.current_position = -1
                
            base64_image, caption, keywords, filename = self.image_history[
                len(self.image_history) - 1 if self.current_position == -1 else self.current_position
            ]
            self.display_image(base64_image, caption, keywords, filename)

    def navigate_last(self):
        if self.image_history:
            self.current_position = -1
            base64_image, caption, keywords, filename = self.image_history[-1]
            self.display_image(base64_image, caption, keywords, filename)

    def update_navigation_buttons(self):
        history_size = len(self.image_history)
        
        if history_size == 0:
            # No images yet
            self.first_button.setEnabled(False)
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.last_button.setEnabled(False)
            self.position_label.setText("No images processed")
            return
        
        # Determine position for display
        if self.current_position == -1:
            # At the most recent image
            position = history_size
            self.next_button.setEnabled(False)
            self.last_button.setEnabled(False)
        else:
            position = self.current_position + 1  # 1-based for display
            self.next_button.setEnabled(self.current_position < history_size - 1)
            self.last_button.setEnabled(self.current_position < history_size - 1)
        
        # Update position text
        self.position_label.setText(f"Image {position} of {history_size}")
        
        # Enable/disable first/prev buttons
        self.first_button.setEnabled(history_size > 1 and (self.current_position > 0 or self.current_position == -1))
        self.prev_button.setEnabled(history_size > 1 and (self.current_position > 0 or self.current_position == -1))
          
    def run_indexer(self):
        if not self.api_is_ready:
            QMessageBox.warning(self, "API Not Ready", 
                              "Please wait for the API to be available before running the indexer.")
            return
        
        self.image_history = []
        self.current_position = -1
        self.update_navigation_buttons()
        
        config = llmii.Config()
        
        self.image_preview.setText("No image processed yet")
        self.filename_label.setText("Filename: ")
        self.caption_label.setText("No caption generated yet")
        self.keywords_widget.clear()
        
        # Get directory from main window
        config.directory = self.dir_input.text()
        
        # Load settings from settings dialog
        config.api_url = self.settings_dialog.api_url_input.text()
        config.api_password = self.settings_dialog.api_password_input.text()
        config.system_instruction = self.settings_dialog.system_instruction_input.text()
        config.no_crawl = self.settings_dialog.no_crawl_checkbox.isChecked()
        config.reprocess_failed = self.settings_dialog.reprocess_failed_checkbox.isChecked()
        config.reprocess_all = self.settings_dialog.reprocess_all_checkbox.isChecked()
        config.reprocess_orphans = self.settings_dialog.reprocess_orphans_checkbox.isChecked()
        config.no_backup = self.settings_dialog.no_backup_checkbox.isChecked()
        config.dry_run = self.settings_dialog.dry_run_checkbox.isChecked()
        config.skip_verify = self.settings_dialog.skip_verify_checkbox.isChecked()
        config.quick_fail = self.settings_dialog.quick_fail_checkbox.isChecked()
        
        # Load caption settings
        config.detailed_caption = self.settings_dialog.detailed_caption_radio.isChecked()
        config.short_caption = self.settings_dialog.short_caption_radio.isChecked()
        config.no_caption = self.settings_dialog.no_caption_radio.isChecked()
        config.caption_instruction = self.settings_dialog.caption_instruction_input.text()
        
        # Load instruction from settings
        config.instruction = self.settings_dialog.instruction_text
        
        # Load update keywords setting
        config.update_keywords = self.settings_dialog.update_keywords_checkbox.isChecked()
        config.update_caption = self.settings_dialog.update_caption_checkbox.isChecked()
        config.gen_count = self.settings_dialog.gen_count.value()
             
        self.indexer_thread = IndexerThread(config)
        self.indexer_thread.output_received.connect(self.update_output)
        self.indexer_thread.image_processed.connect(self.update_image_preview)
        self.indexer_thread.finished.connect(self.indexer_finished)
        self.pause_handler.pause_signal.connect(self.set_paused)
        self.pause_handler.stop_signal.connect(self.set_stopped)
        self.indexer_thread.start()

        self.output_area.clear()
        self.output_area.append("Running Image Indexer...")
        self.run_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)

    def set_paused(self, paused):
        if self.indexer_thread:
            self.indexer_thread.paused = paused

    def set_stopped(self):
        if self.indexer_thread:
            self.indexer_thread.stopped = True

    def toggle_pause(self):
        if self.pause_button.text() == "Pause":
            self.pause_handler.pause_signal.emit(True)
            self.pause_button.setText("Resume")
            self.update_output("Indexer paused.")
        else:
            self.pause_handler.pause_signal.emit(False)
            self.pause_button.setText("Pause")
            self.update_output("Indexer resumed.")

    def stop_indexer(self):
        self.pause_handler.stop_signal.emit()
        self.update_output("Stopping indexer...")
        self.run_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)

    def indexer_finished(self):
        self.update_output("\nImage Indexer finished.")
        self.run_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.pause_button.setText("Pause")

    def update_output(self, text):
        self.output_area.append(text)
        self.output_area.verticalScrollBar().setValue(self.output_area.verticalScrollBar().maximum())
        QApplication.processEvents()

    # Override resizeEvent to disable it since we're using fixed sizes
    def resizeEvent(self, event):
        """We override this but it shouldn't be called since window is fixed"""
        super().resizeEvent(event)
        
    def closeEvent(self, event):
        # Clean up API check thread when closing the window
        if self.api_check_thread and self.api_check_thread.isRunning():
            self.api_check_thread.stop()
            self.api_check_thread.wait()
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = ImageIndexerGUI()
    window.show()
    sys.exit(app.exec())    

if __name__ == "__main__":
    main()