import sys
import os
import json
import llmii
from koboldapi import KoboldAPI
from PyQt6.QtCore import QThread, pyqtSignal, QObject, Qt
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                           QLabel, QLineEdit, QCheckBox, QPushButton, QFileDialog, 
                           QTextEdit, QGroupBox, QSpinBox, QRadioButton, QButtonGroup,
                           QProgressBar, QTableWidget, QTableWidgetItem, QComboBox,
                           QPlainTextEdit, QScrollArea, QMessageBox, QDialog, QMenuBar,
                           QMenu, QSizePolicy)

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(600, 400)
        
        layout = QVBoxLayout(self)
        
        api_layout = QHBoxLayout()
        self.api_url_input = QLineEdit("http://localhost:5001")
        self.api_password_input = QLineEdit()
        api_layout.addWidget(QLabel("API URL:"))
        api_layout.addWidget(self.api_url_input)
        api_layout.addWidget(QLabel("API Password:"))
        api_layout.addWidget(self.api_password_input)
        layout.addLayout(api_layout)

        caption_group = QGroupBox("Caption Settings")
        caption_layout = QVBoxLayout()
        
        caption_instruction_layout = QHBoxLayout()
        self.caption_instruction_input = QLineEdit("Describe the image in detail. Be specific.")
        caption_instruction_layout.addWidget(QLabel("Caption Instruction:"))
        caption_instruction_layout.addWidget(self.caption_instruction_input)
        caption_layout.addLayout(caption_instruction_layout)
        
        self.write_caption_checkbox = QCheckBox("Write a detailed caption (overwrites existing captions and takes twice as long)")
        caption_layout.addWidget(self.write_caption_checkbox)
        
        caption_group.setLayout(caption_layout)
        layout.addWidget(caption_group)

        gen_count_layout = QHBoxLayout()
        self.gen_count = QSpinBox()
        self.gen_count.setMinimum(50)
        self.gen_count.setMaximum(1000)
        self.gen_count.setValue(250)
        gen_count_layout.addWidget(QLabel("GenTokens: "))
        gen_count_layout.addWidget(self.gen_count)
        layout.addLayout(gen_count_layout)
        
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout()
        
        self.no_crawl_checkbox = QCheckBox("Don't crawl subdirectories")
        self.reprocess_all_checkbox = QCheckBox("Reprocess all files again")
        self.reprocess_failed_checkbox = QCheckBox("Reprocess failed files")
        self.reprocess_orphans_checkbox = QCheckBox("Reprocess orphan files")
        self.no_backup_checkbox = QCheckBox("Don't make backups")
        self.dry_run_checkbox = QCheckBox("Pretend mode")
        
        options_layout.addWidget(self.no_crawl_checkbox)
        options_layout.addWidget(self.reprocess_all_checkbox)
        options_layout.addWidget(self.reprocess_failed_checkbox)
        options_layout.addWidget(self.reprocess_orphans_checkbox)
        options_layout.addWidget(self.no_backup_checkbox)
        options_layout.addWidget(self.dry_run_checkbox)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        xmp_group = QGroupBox("Metadata Tags to Generate")
        xmp_layout = QVBoxLayout()
        
        self.keywords_radio_group = QButtonGroup(self)
        self.overwrite_keywords_radio = QRadioButton("Clear existing keywords and captions and write new ones")
        self.update_keywords_radio = QRadioButton("Add to existing keywords")
        
        self.keywords_radio_group.addButton(self.overwrite_keywords_radio)
        self.keywords_radio_group.addButton(self.update_keywords_radio)
        
        xmp_layout.addWidget(self.overwrite_keywords_radio)
        xmp_layout.addWidget(self.update_keywords_radio)
        
        xmp_group.setLayout(xmp_layout)
        layout.addWidget(xmp_group)
        
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        self.update_keywords_radio.setChecked(True)
        self.reprocess_orphans_checkbox.setChecked(False)
        
        self.load_settings()
            
    def load_settings(self):
        try:
            if os.path.exists('settings.json'):
                with open('settings.json', 'r') as f:
                    settings = json.load(f)
                    
                self.api_url_input.setText(settings.get('api_url', 'http://localhost:5001'))
                self.api_password_input.setText(settings.get('api_password', ''))
                self.gen_count.setValue(settings.get('gen_count', 250))
                
                self.no_crawl_checkbox.setChecked(settings.get('no_crawl', False))
                self.reprocess_failed_checkbox.setChecked(settings.get('reprocess_failed', False))
                self.reprocess_all_checkbox.setChecked(settings.get('reprocess_all', False))
                self.reprocess_orphans_checkbox.setChecked(settings.get('reprocess_orphans', False))
                self.no_backup_checkbox.setChecked(settings.get('no_backup', False))
                self.dry_run_checkbox.setChecked(settings.get('dry_run', False))
                
                self.caption_instruction_input.setText(settings.get('caption_instruction', 'Describe the image in detail. Be specific.'))
                self.write_caption_checkbox.setChecked(settings.get('write_caption', False))
                
                if settings.get('overwrite_keywords', False):
                    self.overwrite_keywords_radio.setChecked(True)
                else:
                    self.update_keywords_radio.setChecked(True)
        except Exception as e:
            print(f"Error loading settings: {e}")
            
    def save_settings(self):
        settings = {
            'api_url': self.api_url_input.text(),
            'api_password': self.api_password_input.text(),
            'gen_count': self.gen_count.value(),
            'no_crawl': self.no_crawl_checkbox.isChecked(),
            'reprocess_failed': self.reprocess_failed_checkbox.isChecked(),
            'reprocess_all': self.reprocess_all_checkbox.isChecked(),
            'reprocess_orphans': self.reprocess_orphans_checkbox.isChecked(),
            'no_backup': self.no_backup_checkbox.isChecked(),
            'dry_run': self.dry_run_checkbox.isChecked(),
            'overwrite_keywords': self.overwrite_keywords_radio.isChecked(),
            'caption_instruction': self.caption_instruction_input.text(),
            'write_caption': self.write_caption_checkbox.isChecked()
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
                api = KoboldAPI(self.api_url)
                version = api.get_version()
                if version:
                    self.api_status.emit(True)
                    break
            except:
                self.api_status.emit(False)
            self.msleep(1000)
            
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
        
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("Settings")
        
        settings_action = settings_menu.addAction("Configure")
        settings_action.triggered.connect(self.show_settings)
        
        self.settings_dialog = SettingsDialog(self)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        fixed_content = QWidget()
        fixed_layout = QVBoxLayout(fixed_content)
        fixed_layout.setContentsMargins(0, 0, 0, 0)
        
        dir_layout = QHBoxLayout()
        self.dir_input = QLineEdit()
        dir_button = QPushButton("Select Directory")
        dir_button.clicked.connect(self.select_directory)
        dir_layout.addWidget(QLabel("Directory:"))
        dir_layout.addWidget(self.dir_input)
        dir_layout.addWidget(dir_button)
        fixed_layout.addLayout(dir_layout)

        self.api_status_label = QLabel("API Status: Checking...")
        layout.addWidget(self.api_status_label)
        
        instruction_group = QGroupBox("Keyword Generation Instructions")
        instruction_layout = QVBoxLayout()
        
        self.instruction_input = QPlainTextEdit()
        default_instruction = """Your task is to first generate a detailed description for the image. If a description is included with the image, use that one.

Next, generate at least 10 unique Keywords for the image. Include:

 - Actions
 - Setting, location and background
 - Items and structures
 - Colors and textures
 - Composition, framing
 - Photographic style 
 - If there is one or more person:
   - Subjects
   - Physical appearance
   - Clothing
   - Gender
   - Age
   - Professions
   - Relationships 

Provide one word per entry; if more than one word is required split into two entries. Do not combine words. Generate ONLY a JSON object with the keys Caption and Keywords as follows {"Caption": str, "Keywords": [list]}"""
        
        self.instruction_input.setPlainText(default_instruction)
        self.instruction_input.setFixedHeight(350)
        
        instruction_layout.addWidget(QLabel("Instruction:"))
        instruction_layout.addWidget(self.instruction_input)
        
        instruction_group.setLayout(instruction_layout)
        fixed_layout.addWidget(instruction_group)
        
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
        fixed_layout.addLayout(button_layout)

        layout.addWidget(fixed_content)

        output_widget = QWidget()
        output_layout = QVBoxLayout(output_widget)
        output_layout.setContentsMargins(0, 0, 0, 0)
        
        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        output_layout.addWidget(QLabel("Output:"))
        output_layout.addWidget(self.output_area)
        
        self.instruction_input.setFixedHeight(350)
        
        layout.addWidget(output_widget)

        self.pause_handler = PauseHandler()
        
        self.api_check_thread = None
        self.api_is_ready = False
        
        self.run_button.setEnabled(False)
        
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
        self.api_status_label.setStyleSheet("color: orange")
        
        self.api_check_thread = APICheckThread(api_url if api_url else self.settings_dialog.api_url_input.text())
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

    def run_indexer(self):
        if not self.api_is_ready:
            QMessageBox.warning(self, "API Not Ready", 
                              "Please wait for the API to be available before running the indexer.")
            return
            
        config = llmii.Config()
        
        # Get directory from main window
        config.directory = self.dir_input.text()
        
        # Load settings from settings dialog
        config.api_url = self.settings_dialog.api_url_input.text()
        config.api_password = self.settings_dialog.api_password_input.text()
        config.no_crawl = self.settings_dialog.no_crawl_checkbox.isChecked()
        config.reprocess_failed = self.settings_dialog.reprocess_failed_checkbox.isChecked()
        config.reprocess_all = self.settings_dialog.reprocess_all_checkbox.isChecked()
        config.reprocess_orphans = self.settings_dialog.reprocess_orphans_checkbox.isChecked()
        config.no_backup = self.settings_dialog.no_backup_checkbox.isChecked()
        config.dry_run = self.settings_dialog.dry_run_checkbox.isChecked()
        
        # Load instruction from main window
        config.instruction = self.instruction_input.toPlainText()
        
        # Load caption settings from settings dialog
        config.write_caption = self.settings_dialog.write_caption_checkbox.isChecked()
        config.caption_instruction = self.settings_dialog.caption_instruction_input.text()
        
        if self.settings_dialog.overwrite_keywords_radio.isChecked():
            config.overwrite_keywords = True
            config.update_keywords = False
        elif self.settings_dialog.update_keywords_radio.isChecked():
            config.overwrite_keywords = False
            config.update_keywords = True
            
        config.gen_count = self.settings_dialog.gen_count.value()
     
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