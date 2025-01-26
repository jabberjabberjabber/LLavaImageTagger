import sys
import os
import llmii
from PyQt6.QtCore import QThread, pyqtSignal, QObject, Qt
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                           QLabel, QLineEdit, QCheckBox, QPushButton, QFileDialog, 
                           QTextEdit, QGroupBox, QSpinBox, QRadioButton, QButtonGroup,
                           QProgressBar, QTableWidget, QTableWidgetItem, QComboBox,
                           QPlainTextEdit, QScrollArea, QMessageBox)
from koboldapi import KoboldAPI

class APICheckThread(QThread):
    api_status = pyqtSignal(bool)
    
    def __init__(self, api_url):
        super().__init__()
        self.api_url = api_url
        self.running = True
        
    def run(self):
        while self.running:
            try:
                api = KoboldAPI(self.api_url)
                version = api.get_version()
                if version:
                    self.api_status.emit(True)
                    break
            except:
                self.api_status.emit(False)
            self.msleep(1000)  # Check every second
            
    def stop(self):
        self.running = False

class IndexerThread(QThread):
    output_received = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.paused = False
        self.stopped = False

    def run(self):
        try:
            llmii.main(self.config, self.output_received.emit, self.check_paused_or_stopped)
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

class PauseHandler(QObject):
    pause_signal = pyqtSignal(bool)
    stop_signal = pyqtSignal()

class ImageIndexerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Indexer GUI")
        self.setGeometry(100, 100, 800, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Directory selection
        dir_layout = QHBoxLayout()
        self.dir_input = QLineEdit()
        dir_button = QPushButton("Select Directory")
        dir_button.clicked.connect(self.select_directory)
        dir_layout.addWidget(QLabel("Directory:"))
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(dir_button)
        layout.addLayout(dir_layout)

        # API URL and Password
        api_layout = QHBoxLayout()
        self.api_url_input = QLineEdit("http://localhost:5001")
        self.api_password_input = QLineEdit()
        api_layout.addWidget(QLabel("API URL:"))
        api_layout.addWidget(self.api_url_input)
        api_layout.addWidget(QLabel("API Password:"))
        api_layout.addWidget(self.api_password_input)
        layout.addLayout(api_layout)

        # Add API status indicator
        self.api_status_label = QLabel("API Status: Checking...")
        layout.addWidget(self.api_status_label)
        
        caption_instruction_layout = QVBoxLayout()
        caption_group = QGroupBox("Caption Settings")
        caption_inner_layout = QVBoxLayout()
        
        self.caption_instruction_input = QPlainTextEdit()
        self.caption_instruction_input.setPlainText("Describe the image in detail. Be specific.")
        self.caption_instruction_input.setMaximumHeight(100)
        
        caption_label = QLabel("Caption Instruction:")
        caption_inner_layout.addWidget(caption_label)
        caption_inner_layout.addWidget(self.caption_instruction_input)
        
        self.write_caption_checkbox = QCheckBox("Write a caption and place in XMP:Description")
        caption_inner_layout.addWidget(self.write_caption_checkbox)
        
        caption_group.setLayout(caption_inner_layout)
        caption_instruction_layout.addWidget(caption_group)
        layout.addLayout(caption_instruction_layout)
        
        # Replace Instruction section
        instruction_group = QGroupBox("Keyword Generation Instructions")
        instruction_layout = QVBoxLayout()
        
        self.instruction_input = QPlainTextEdit()
        default_instruction = """Generate at least 14 unique one or two word IPTC Keywords for the image. Cover the following categories as applicable:
1. Main subject of the image
2. Physical appearance and clothing, gender, age, professions and relationships
3. Actions or state of the main elements
4. Setting or location, environment, or background
5. Notable items, structures, or elements
6. Colors and textures, patterns, or lighting
7. Atmosphere and mood, time of day, season, or weather
8. Composition and perspective, framing, or style of the photo.
9. Any other relevant keywords

Provide one or two words. Do not combine words. Generate ONLY a JSON object with the key Keywords with a single list of keywords as follows {"Keywords": []}"""
        
        self.instruction_input.setPlainText(default_instruction)
        self.instruction_input.setMinimumHeight(200)
        
        instruction_layout.addWidget(QLabel("Instruction:"))
        instruction_layout.addWidget(self.instruction_input)
        
        instruction_group.setLayout(instruction_layout)
        layout.addWidget(instruction_group)

        # GenTokens
        gen_count_layout = QHBoxLayout()
        self.gen_count = QSpinBox()
        self.gen_count.setMinimum(50)
        self.gen_count.setMaximum(1000)
        self.gen_count.setValue(150)
        gen_count_layout.addWidget(QLabel("GenTokens: "))
        gen_count_layout.addWidget(self.gen_count)
        layout.addLayout(gen_count_layout)
        
        # Options and Keyword Post-Processing
        options_group = QGroupBox("Options")
        options_layout = QHBoxLayout()
        
        # Left column: Checkboxes
        checkbox_layout = QVBoxLayout()
        self.no_crawl_checkbox = QCheckBox("Don't crawl subdirectories")
        self.reprocess_failed_checkbox = QCheckBox("Reprocess failed files")
        self.reprocess_all_checkbox = QCheckBox("Reprocess ALL files again")
        self.skip_orphans_checkbox = QCheckBox("Skip images previously processed but not in database")
        self.no_backup_checkbox = QCheckBox("Don't make backups (processing AND post-processing)")
        self.dry_run_checkbox = QCheckBox("Pretend mode (do not write to files)")
        self.skip_processing_checkbox = QCheckBox("Skip processing and go to post-processing")
        checkbox_layout.addWidget(self.no_crawl_checkbox)
        checkbox_layout.addWidget(self.reprocess_failed_checkbox)
        checkbox_layout.addWidget(self.reprocess_all_checkbox)
        checkbox_layout.addWidget(self.skip_orphans_checkbox)
        checkbox_layout.addWidget(self.no_backup_checkbox)
        checkbox_layout.addWidget(self.dry_run_checkbox)
        checkbox_layout.addWidget(self.skip_processing_checkbox)
        options_layout.addLayout(checkbox_layout)
        
        # Right column: Keyword Post-Processing
        keyword_processing_layout = QVBoxLayout()
        keyword_processing_layout.addWidget(QLabel("Keyword Post-Processing:"))
        self.keyword_processing_combo = QComboBox()
        self.keyword_processing_combo.addItems(["keep", "expand", "dedupe"])
        keyword_processing_layout.addWidget(self.keyword_processing_combo)
        
        example_text = (
            "<b>Example:</b><br>"
            "backpack, teen<br>"
            "knapsack, teenager<br>"
            "backpack, teenager<br>"
            "<b>Expand</b> <i>(every synonym used)</i>:<br>"
            "backpack, knapsack, teen, teenager<br>"
            "<b>DeDupe</b> <i>(most frequent synonym used)</i>:<br>"
            "backpack, teenager<br>"
            "<b>Note:</b> This can be run later without reprocessing files."
        )
        example_label = QLabel(example_text)
        example_label.setWordWrap(True)
        example_label.setTextFormat(Qt.TextFormat.RichText)
        keyword_processing_layout.addWidget(example_label)
                
        options_layout.addLayout(keyword_processing_layout)
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        xmp_group = QGroupBox("Metadata Tags to Generate")
        xmp_layout = QVBoxLayout()
        
        # Keywords radio buttons
        keywords_layout = QVBoxLayout()
        self.keywords_radio_group = QButtonGroup(self)
        self.overwrite_keywords_radio = QRadioButton("Clear existing keywords and write new ones")
        self.update_keywords_radio = QRadioButton("Add to existing keywords")
        
        self.keywords_radio_group.addButton(self.overwrite_keywords_radio)
        self.keywords_radio_group.addButton(self.update_keywords_radio)
        
        keywords_layout.addWidget(self.overwrite_keywords_radio)
        keywords_layout.addWidget(self.update_keywords_radio)
        
        # Set default selection
        self.update_keywords_radio.setChecked(True)
        self.skip_orphans_checkbox.setChecked(True)
        
        xmp_layout.addLayout(keywords_layout)
        xmp_group.setLayout(xmp_layout)
        layout.addWidget(xmp_group)
        
        # Run, Pause, and Stop buttons
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
        layout.addLayout(button_layout)

        # Output area
        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        layout.addWidget(QLabel("Output:"))
        layout.addWidget(self.output_area)

        self.pause_handler = PauseHandler()
        
        # Initialize API check thread
        self.api_check_thread = None
        self.api_is_ready = False
        
        # Disable Run button initially
        self.run_button.setEnabled(False)
        
        # Start checking API when URL changes
        self.api_url_input.textChanged.connect(self.start_api_check)
        
        # Start initial API check
        self.start_api_check()

    def start_api_check(self):
        if self.api_check_thread and self.api_check_thread.isRunning():
            self.api_check_thread.stop()
            self.api_check_thread.wait()
            
        self.api_is_ready = False
        self.run_button.setEnabled(False)
        self.api_status_label.setText("API Status: Checking...")
        self.api_status_label.setStyleSheet("color: orange")
        
        self.api_check_thread = APICheckThread(self.api_url_input.text())
        self.api_check_thread.api_status.connect(self.update_api_status)
        self.api_check_thread.start()

    def update_api_status(self, is_available):
        if is_available:
            self.api_is_ready = True
            self.api_status_label.setText("API Status: Connected")
            self.api_status_label.setStyleSheet("color: green")
            self.run_button.setEnabled(True)
            
            # Stop the check thread once we're connected
            if self.api_check_thread:
                self.api_check_thread.stop()
        else:
            self.api_is_ready = False
            self.api_status_label.setText("API Status: Waiting for connection...")
            self.api_status_label.setStyleSheet("color: red")
            self.run_button.setEnabled(False)

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.dir_input.setText(directory)

    def run_indexer(self):
        if not self.api_is_ready:
            QMessageBox.warning(self, "API Not Ready", 
                              "Please wait for the API to be available before running the indexer.")
            return
            
        config = llmii.Config()
        config.directory = self.dir_input.text()
        config.api_url = self.api_url_input.text()
        config.api_password = self.api_password_input.text()
        config.no_crawl = self.no_crawl_checkbox.isChecked()
        config.reprocess_failed = self.reprocess_failed_checkbox.isChecked()
        config.reprocess_all = self.reprocess_all_checkbox.isChecked()
        config.skip_orphans = self.skip_orphans_checkbox.isChecked()
        config.skip_processing = self.skip_processing_checkbox.isChecked()
        config.no_backup = self.no_backup_checkbox.isChecked()
        config.write_caption = self.write_caption_checkbox.isChecked()
        config.dry_run = self.dry_run_checkbox.isChecked()
        config.instruction = self.instruction_input.toPlainText()
        config.caption_instruction = self.caption_instruction_input.toPlainText()
        if self.overwrite_keywords_radio.isChecked():
            config.overwrite_keywords = True
            config.update_keywords = False
        elif self.update_keywords_radio.isChecked():
            config.overwrite_keywords = False
            config.update_keywords = True
            
        config.keyword_processing = self.keyword_processing_combo.currentText()
        config.gen_count = self.gen_count.value()
     
        self.indexer_thread = IndexerThread(config)
        self.indexer_thread.output_received.connect(self.update_output)
        self.indexer_thread.finished.connect(self.indexer_finished)
        self.pause_handler.pause_signal.connect(self.set_paused)
        self.pause_handler.stop_signal.connect(self.set_stopped)
        self.indexer_thread.start()

        self.output_area.clear()
        self.output_area.append("Running Image Indexer...\n")
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
        self.update_output("Image Indexer finished.")
        self.run_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.pause_button.setText("Pause")

    def update_output(self, text):
        self.output_area.append(text)
        self.output_area.verticalScrollBar().setValue(self.output_area.verticalScrollBar().maximum())
        QApplication.processEvents()
        
    def closeEvent(self, event):
        # Clean up API check thread when closing the window
        if self.api_check_thread and self.api_check_thread.isRunning():
            self.api_check_thread.stop()
            self.api_check_thread.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ImageIndexerGUI()
    window.show()
    sys.exit(app.exec())