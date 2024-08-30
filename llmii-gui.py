import sys
import os
import llmii
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QCheckBox, QPushButton, QFileDialog, 
                             QTextEdit, QGroupBox, QSpinBox, QRadioButton, QButtonGroup,
                             QProgressBar, QTableWidget, QTableWidgetItem)

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
            # After unpausing, check again if we've been stopped
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
        
        # Instruction
        instruction_layout = QHBoxLayout()
        self.instruction_input = QLineEdit("Analyze the image and generate at least 30 unique IPTC keywords. Cover the following categories as applicable:\n\n1. Main subject: Identify the primary focus of the image\n2. Living beings: If present, describe people's (and animal's where appropriate) appearance and clothing, infer gender, age, professions and relationships\n3. Actions or state: Describe any activities or the state of the main elements\n4. Setting: Describe the location, environment, or background\n5. Objects: List notable items, structures, or elements in the scene\n6. Visual qualities: Mention colors, textures, patterns, or lighting\n7. Atmosphere: Describe the mood, time of day, season, or weather\n8. Composition: Note the perspective, framing, or style of the photo\n\nProvide one or two words, avoiding repetition. Be specific and descriptive. Return ONLY a JSON object with the key 'Keywords' and an array of keyword strings as the value.")
        instruction_layout.addWidget(QLabel("Instruction:"))
        instruction_layout.addWidget(self.instruction_input)
        layout.addLayout(instruction_layout)
        
        # Checkboxes for options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout()
        self.no_crawl_checkbox = QCheckBox("Don't crawl subdirectories")
        self.reprocess_failed_checkbox = QCheckBox("Reprocess failed files")
        self.reprocess_all_checkbox = QCheckBox("Reprocess ALL files again")
        #self.lemmatize_checkbox = QCheckBox("Lemmatize keywords (example: run, ran, running all become run)")
        self.overwrite_checkbox = QCheckBox("Don't make backups before writing")
        self.dry_run_checkbox = QCheckBox("Pretend mode (do not write to files)")
        options_layout.addWidget(self.no_crawl_checkbox)
        options_layout.addWidget(self.overwrite_checkbox)
        options_layout.addWidget(self.reprocess_failed_checkbox)
        options_layout.addWidget(self.reprocess_all_checkbox)
        #options_layout.addWidget(self.lemmatize_checkbox)        
        options_layout.addWidget(self.dry_run_checkbox)
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        xmp_group = QGroupBox("Metadata Tags to Generate")
        xmp_layout = QVBoxLayout()
        
        # Keywords radio buttons
        keywords_layout = QVBoxLayout()
        self.keywords_radio_group = QButtonGroup(self)
        
        #self.no_keywords_radio = QRadioButton("Don't modify keywords")
        self.write_keywords_radio = QRadioButton("Clear existing keywords and write new ones")
        self.update_keywords_radio = QRadioButton("Add to existing keywords")
        
        #self.keywords_radio_group.addButton(self.no_keywords_radio)
        self.keywords_radio_group.addButton(self.write_keywords_radio)
        self.keywords_radio_group.addButton(self.update_keywords_radio)
        
        #keywords_layout.addWidget(self.no_keywords_radio)
        keywords_layout.addWidget(self.write_keywords_radio)
        keywords_layout.addWidget(self.update_keywords_radio)
        
        # Set default selection
        self.update_keywords_radio.setChecked(True)
        
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

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.dir_input.setText(directory)

    def run_indexer(self):
        config = llmii.Config()
        config.directory = self.dir_input.text()
        config.api_url = self.api_url_input.text()
        config.api_password = self.api_password_input.text()
        config.no_crawl = self.no_crawl_checkbox.isChecked()
        config.reprocess_failed = self.reprocess_failed_checkbox.isChecked()
        config.reprocess_all = self.reprocess_all_checkbox.isChecked()
        config.overwrite = self.overwrite_checkbox.isChecked()
        config.dry_run = self.dry_run_checkbox.isChecked()
        #config.lemmatize = self.lemmatize_checkbox.isChecked()
        config.instruction = self.instruction_input.text()
        if self.write_keywords_radio.isChecked():
            config.write_keywords = True
            config.update_keywords = False
        elif self.update_keywords_radio.isChecked():
            config.write_keywords = False
            config.update_keywords = True
        
        config.keywords_count = 7
        #config.keywords_count = self.keywords_count.value()
     
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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ImageIndexerGUI()
    window.show()
    sys.exit(app.exec())
