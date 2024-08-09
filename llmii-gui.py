import sys
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QCheckBox, QPushButton, QFileDialog, 
                             QTextEdit, QGroupBox, QSpinBox, QRadioButton, QButtonGroup)
from PyQt6.QtCore import QThread, pyqtSignal, QObject

import llmii

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

        # Image Instruction
        image_instruction_layout = QHBoxLayout()
        self.image_instruction_input = QLineEdit("What do you see in the image? Be specific and descriptive")
        image_instruction_layout.addWidget(QLabel("Image Instruction:"))
        image_instruction_layout.addWidget(self.image_instruction_input)
        layout.addLayout(image_instruction_layout)

        # Checkboxes for options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout()
        self.no_crawl_checkbox = QCheckBox("Don't crawl subdirectories")
        self.overwrite_checkbox = QCheckBox("Don't make backups before writing")
        self.dry_run_checkbox = QCheckBox("Pretend mode (see what happens without writing)")
        options_layout.addWidget(self.no_crawl_checkbox)
        options_layout.addWidget(self.overwrite_checkbox)
        options_layout.addWidget(self.dry_run_checkbox)
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        xmp_group = QGroupBox("Metadata Tags to Generate")
        xmp_layout = QVBoxLayout()
        
        # Keywords radio buttons
        keywords_layout = QVBoxLayout()
        self.keywords_radio_group = QButtonGroup(self)
        
        #self.no_keywords_radio = QRadioButton("Don't modify keywords")
        self.write_keywords_radio = QRadioButton("Clear existing and write new keywords")
        self.update_keywords_radio = QRadioButton("Update existing keywords")
        
        #self.keywords_radio_group.addButton(self.no_keywords_radio)
        self.keywords_radio_group.addButton(self.write_keywords_radio)
        self.keywords_radio_group.addButton(self.update_keywords_radio)
        
        #keywords_layout.addWidget(self.no_keywords_radio)
        keywords_layout.addWidget(self.write_keywords_radio)
        keywords_layout.addWidget(self.update_keywords_radio)
        
        # Set default selection
        self.update_keywords_radio.setChecked(True)
        
        keywords_count_layout = QHBoxLayout()
        self.keywords_count = QSpinBox()
        self.keywords_count.setMinimum(1)
        self.keywords_count.setMaximum(50)
        self.keywords_count.setValue(7)
        keywords_count_layout.addWidget(QLabel("Number of keywords to generate: "))
        keywords_count_layout.addWidget(self.keywords_count)
        
        keywords_layout.addLayout(keywords_count_layout)
        
        self.description_checkbox = QCheckBox("Generate and set description?")
        
        xmp_layout.addLayout(keywords_layout)
        xmp_layout.addWidget(self.description_checkbox)
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
        config.overwrite = self.overwrite_checkbox.isChecked()
        config.dry_run = self.dry_run_checkbox.isChecked()
        if self.write_keywords_radio.isChecked():
            config.write_keywords = True
            config.update_keywords = False
        elif self.update_keywords_radio.isChecked():
            config.write_keywords = False
            config.update_keywords = True

        config.keywords_count = self.keywords_count.value()
        config.write_caption = self.description_checkbox.isChecked()
        config.image_instruction = self.image_instruction_input.text()

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
