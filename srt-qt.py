import sys
import time
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from DrissionPage import Chromium  # 确保已安装 DrissionPage
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QLabel,
    QFileDialog,
    QVBoxLayout,
    QWidget,
    QProgressBar,
)
from PyQt5.QtCore import Qt, QObject, pyqtSignal, QThread

# --- Worker 类 ---

class Worker(QObject):
    progress = pyqtSignal(int)      # 发射进度百分比
    status = pyqtSignal(str)        # 发射状态消息
    finished = pyqtSignal()         # 处理完成信号
    error = pyqtSignal(str)         # 发射错误消息

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.is_interrupted = False

    def run(self):
        try:
            # 初始化 Chromium
            self.status.emit("初始化 Chromium 浏览器中...")
            chromium = Chromium()
            chromium.set.cookies.clear()
            tab = chromium.get_tab()
            self.status.emit('正在导航到 Deepl.com...')
            tab.get('https://www.deepl.com/')
            time.sleep(4)
            tab.ele('c:#cookieBanner > div > span > button').click()
            time.sleep(2)
            self.status.emit("初始化成功。")

            # 开始处理文件
            self.status.emit("开始处理文件...")
            self.main(self.file_path, chromium)

            # 清理
            self.status.emit("清理资源中...")
            chromium.quit()
            self.status.emit("处理完成。")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def main(self, file, chromium):
        def translate(text):
            while True:
                try:
                    tab_new = chromium.new_tab()
                    tab_new.get('https://www.deepl.com/')
                    tab_new.ele(
                        r'c:#textareasContainer > div.rounded-es-inherit.relative.min-h-\[240px\].min-w-0.md\:min-h-\[clamp\(250px\,50vh\,557px\)\].mobile\:min-h-0.mobile\:portrait\:max-h-\[calc\(\(100vh-61px-1px-64px\)\/2\)\] > section > div > div.relative.flex-1.rounded-inherit.mobile\:min-h-0 > d-textarea > div:nth-child(1)'
                    ).input(text)
                    time.sleep(5)
                    translated_text = tab_new.ele(
                        r'c:#textareasContainer > div.rounded-ee-inherit.relative.min-h-\[240px\].min-w-0.md\:min-h-\[clamp\(250px\,50vh\,557px\)\].mobile\:min-h-0.mobile\:flex-1.mobile\:portrait\:max-h-\[calc\(\(100vh-61px-1px-64px\)\/2\)\].max-\[768px\]\:min-h-\[375px\] > section > div.rounded-inherit.mobile\:min-h-0.relative.flex.flex-1.flex-col > d-textarea > div'
                    ).text
                    tab_new.close()
                    return translated_text.replace('\n\n', '\n')
                except Exception as e:
                    self.status.emit(f"翻译错误: {e}。正在重试...")
                    time.sleep(2)
                    continue  # 失败后重试

        def accumulate_by_length(lst, limit=1400):
            blocks = []
            current_str = ""
            current_length = 0
            for string in lst:
                string_length = len(string)
                if current_length + string_length > limit:
                    blocks.append(current_str)
                    current_str = string
                    current_length = string_length
                else:
                    current_str += string
                    current_length += string_length
            blocks.append(current_str)
            return blocks

        def process_blocks_multithread(blocks, max_workers=10):
            result = [None] * len(blocks)

            def process_block(index, block):
                return index, translate(block) + '\n\n\n'

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(process_block, i, block): i
                    for i, block in enumerate(blocks)
                }
                for future in as_completed(futures):
                    if self.is_interrupted:
                        executor.shutdown(wait=False)
                        return
                    index, translated_block = future.result()
                    result[index] = translated_block
                    filled = len([b for b in result if b is not None])
                    progress_percentage = int((filled / len(blocks)) * 100)
                    self.progress.emit(progress_percentage)
            return result

        def accumulate_blocks(lst, limit=1400):
            return accumulate_by_length(lst, limit)

        def translate_texts(blocks):
            return process_blocks_multithread(blocks)

        def compare_and_process_files(file1, file2, output_file, max_workers=20):
            def process_subtitle(index, match1, match2):
                begin1, end1, text1 = match1
                _, _, text2 = match2
                if text1 == text2:
                    text2 = translate(text2)
                return index, f"{begin1} --> {end1}\n{text2}\n\n"

            with open(file1, 'r', encoding=encoding) as f1, open(file2, 'r', encoding='utf-8') as f2:
                srt_text1 = f1.read()
                srt_text2 = f2.read()

            pattern = r"(\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2},\d{3})\n(.*?)\n\n"
            matches1 = re.findall(pattern, srt_text1, re.S)
            matches2 = re.findall(pattern, srt_text2, re.S)

            if len(matches1) != len(matches2):
                raise ValueError("两个文件的字幕数量不同，无法比较处理。")

            result = [None] * len(matches1)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(process_subtitle, i, match1, match2): i
                    for i, (match1, match2) in enumerate(zip(matches1, matches2))
                }
                for future in as_completed(futures):
                    if self.is_interrupted:
                        executor.shutdown(wait=False)
                        return
                    index, processed_block = future.result()
                    result[index] = processed_block
                    filled = len([b for b in result if b is not None])
                    progress_percentage = int((filled / len(matches1)) * 100)
                    self.progress.emit(progress_percentage)

            os.remove(file2)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.writelines(result)

        import chardet

        def detect_encoding(file_path):
            with open(file_path, 'rb') as f:
                rawdata = f.read(10000)  # 读取前10000字节
            result = chardet.detect(rawdata)
            encoding = result['encoding']
            confidence = result['confidence']
            print(f"Detected encoding: {encoding} with confidence {confidence}")
            return encoding

        encoding = detect_encoding(file)
        # 读取并处理主SRT文件
        with open(file, 'r', encoding=encoding) as f:
            srt_text = f.read()
        text_list = []
        pattern = r"(\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2},\d{3})\n(.*?)\n\n"
        matches = re.findall(pattern, srt_text, re.S)
        for match in matches:
            begin, end, text = match
            text_list.append(text + '\n\n\n')
        blocks = accumulate_blocks(text_list)
        result = translate_texts(blocks)
        text_combined = ''.join(result).strip().split('\n\n\n')

        # 写入翻译后的中间文件
        file_m = 'm.srt'
        with open(file_m, 'w', encoding='utf-8') as f_m:
            for i, (match, translated_text) in enumerate(zip(matches, text_combined)):
                begin, end, _ = match
                content_now = f"{i + 1}\n{begin} --> {end}\n{translated_text}\n\n"
                f_m.write(content_now)

        # 比较并处理文件
        compare_and_process_files(file, file_m, f"{file.replace(".srt",'')} zh.srt")


# --- 主窗口类 ---

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("字幕处理器")
        self.setGeometry(100, 100, 500, 200)
        self.file_path = ""

        # 布局
        layout = QVBoxLayout()

        # 选择文件按钮
        self.select_button = QPushButton("选择字幕文件")
        self.select_button.clicked.connect(self.select_file)
        layout.addWidget(self.select_button)

        # 选择的文件标签
        self.file_label = QLabel("未选择文件")
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.progress_bar)

        # 状态标签
        self.status_label = QLabel("状态: 等待中")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # 设置布局
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # 线程和工作对象
        self.worker_thread = None
        self.worker = None

    def select_file(self):
        options = QFileDialog.Options()
        file, _ = QFileDialog.getOpenFileName(
            self,
            "选择字幕文件",
            "",
            "Subtitle Files (*.srt);;All Files (*)",
            options=options,
        )
        if file:
            self.file_path = file
            self.file_label.setText(f"选择的文件: {self.file_path}")
            self.start_processing()

    def start_processing(self):
        if not self.file_path:
            self.status_label.setText("状态: 请先选择一个文件。")
            return

        # 禁用选择按钮以防止重复点击
        self.select_button.setEnabled(False)
        self.status_label.setText("状态: 处理中...")

        # 重置进度条
        self.progress_bar.setValue(0)

        # 设置工作对象和线程
        self.worker = Worker(self.file_path)
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)

        # 连接信号和槽
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.update_progress)
        self.worker.status.connect(self.update_status)
        self.worker.finished.connect(self.processing_finished)
        self.worker.error.connect(self.processing_error)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        # 启动线程
        self.worker_thread.start()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_status(self, message):
        self.status_label.setText(f"状态: {message}")

    def processing_finished(self):
        self.progress_bar.setValue(100)
        self.status_label.setText("状态: 处理完成。")
        self.select_button.setEnabled(True)

    def processing_error(self, error_message):
        self.progress_bar.setValue(0)
        self.status_label.setText(f"错误: {error_message}")
        self.select_button.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()