import os
import sys
import json
import time
import io
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QTextEdit, 
                             QFileDialog, QProgressBar, QFrame, QMessageBox, QScrollArea,)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap,QIcon
import fitz  # PyMuPDF
from PIL import Image
from google import genai
from google.genai import types
from google.genai.errors import APIError

API_KEY = "API_KEY"  # کلید خود را اینجا بگذارید

# --- کلاس ترد برای ترجمه (جلوگیری از هنگ کردن گرافیک برنامه) ---
class TranslationWorker(QThread):
    finished = pyqtSignal(str)
    
    def __init__(self, doc, current_page):
        super().__init__()
        self.doc = doc
        self.current_page = current_page
        
    def run(self):
        try:
            page_obj = self.doc.load_page(self.current_page)
            english_text = page_obj.get_text("text").strip()
            
            client = genai.Client(api_key=API_KEY)
            
            system_instruction = (
                "You are an elite academic translator specializing in psychology and philosophy books. "
                "Your translation must NOT sound like machine translation. Use fluent, dignified, and formal Persian (Farsi) academic prose.\n"
                "CRITICAL RULES:\n"
                "- Do not translate word-for-word. Translate meaning-for-meaning with appropriate Persian academic idioms.\n"
                "- Keep the JSON structure perfectly clean."
            )
            
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,  
                system_instruction=system_instruction  
            )

            if english_text:
                lines = [line.strip() for line in english_text.splitlines() if line.strip()]
                formatted_text = "\n".join(lines)
                
                prompt = (
                    "Translate the following English text into fluent academic Persian (Farsi).\n"
                    "You MUST return the output inside a valid JSON object with these exact keys:\n"
                    "{\n"
                    "  \"title_or_headings\": \"Main title or headings (if none, leave empty)\",\n"
                    "  \"subtitles\": \"Subtitles (if none, leave empty)\",\n"
                    "  \"authors\": \"Author names translated (if none, leave empty)\",\n"
                    "  \"publisher\": \"Publisher name (if none, leave empty)\",\n"
                    "  \"body_text\": \"Main paragraph and content translation (if none, leave empty)\"\n"
                    "}\n"
                    f"Text to translate:\n{formatted_text}"
                )
                contents = prompt
            else:
                pix = page_obj.get_pixmap(matrix=fitz.Matrix(2, 2))
                image_data = pix.tobytes("png")
                pil_img = Image.open(io.BytesIO(image_data))
                
                prompt = (
                    "This is a scanned image of a book page. Read the English text from this image and translate it into fluent academic Persian (Farsi).\n"
                    "You MUST return the output inside a valid JSON object with these exact keys:\n"
                    "{\n"
                    "  \"title_or_headings\": \"Main title or headings (if none, leave empty)\",\n"
                    "  \"subtitles\": \"Subtitles (if none, leave empty)\",\n"
                    "  \"authors\": \"Author names translated (if none, leave empty)\",\n"
                    "  \"publisher\": \"Publisher name (if none, leave empty)\",\n"
                    "  \"body_text\": \"Main paragraph and content translation (if none, leave empty)\"\n"
                    "}\n"
                )
                contents = [pil_img, prompt]

            max_retries = 4
            retry_delay = 4
            response = None
            
            for attempt in range(max_retries):
                try:
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=contents,
                        config=config
                    )
                    break
                except APIError as api_err:
                    if api_err.code in [503, 429]:
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                    raise api_err
            
            if response and response.text:
                raw_content = response.text.strip()
                try:
                    translated_json = json.loads(raw_content)
                    final_output = []
                    
                    if translated_json.get("authors"):
                        final_output.append(f"✍️ نویسنده/نویسندگان: {translated_json['authors']}")
                    if translated_json.get("title_or_headings"):
                        final_output.append(f"🔖 عنوان: {translated_json['title_or_headings']}")
                    if translated_json.get("subtitles"):
                        final_output.append(f"🔍 عنوان فرعی: {translated_json['subtitles']}")
                    if translated_json.get("publisher"):
                        final_output.append(f"🏢 ناشر: {translated_json['publisher']}")
                    if translated_json.get("body_text"):
                        final_output.append(f"\n{translated_json['body_text']}")
                        
                    self.finished.emit("\n".join(final_output))
                except Exception:
                    self.finished.emit("خطا در تحلیل ساختار خروجی JSON جمینای.")
            else:
                self.finished.emit("پاسخی از سرور جمینای دریافت نشد.")
                
        except Exception as ex:
            self.finished.emit(f"خطای غیرمنتظره رخ داد:\n{str(ex)}")

# --- کلاس اصلی اپلیکیشن با رفع ارور رندر تصویر ---
class ModernTranslatorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = None
        self.current_page = 0
        self.total_pages = 0
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("kaman ai translator")
        self.setWindowIcon(QIcon("icon.png"))
        self.resize(1200, 850)
        
        self.setStyleSheet("""
            QMainWindow { background-color: #0f172a; }
            QFrame { background-color: #1e293b; border-radius: 12px; padding: 8px; }
            QLabel { color: #f1f5f9; font-family: 'Tahoma'; font-size: 14px; }
            QPushButton { background-color: #3b82f6; color: white; border-radius: 8px; padding: 10px 18px; font-family: 'Tahoma'; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:disabled { background-color: #475569; color: #94a3b8; }
            QTextEdit { background-color: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 12px; padding: 15px; font-size: 15px; line-height: 1.6; }
            QProgressBar { border: none; background-color: #334155; height: 6px; border-radius: 3px; }
            QProgressBar::chunk { background-color: #10b981; border-radius: 3px; }
            QScrollArea { border: 1px solid #334155; border-radius: 12px; background-color: #1e293b; }
        """)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        header_frame = QFrame()
        header_layout = QHBoxLayout(header_frame)
        header_layout.setDirection(QHBoxLayout.Direction.RightToLeft)
        self.lbl_file = QLabel("هیچ فایلی انتخاب نشده است")
        self.btn_open = QPushButton("📂 انتخاب کتاب (PDF / EPUB)")
        self.btn_open.clicked.connect(self.open_file)
        header_layout.addWidget(self.lbl_file)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_open)
        
        nav_frame = QFrame()
        nav_layout = QHBoxLayout(nav_frame)
        nav_layout.setDirection(QHBoxLayout.Direction.RightToLeft)
        self.btn_next = QPushButton("◀ صفحه بعد")
        self.btn_next.setEnabled(False)
        self.btn_next.clicked.connect(self.next_page)
        self.lbl_page = QLabel("صفحه: ۰ / ۰")
        self.lbl_page.setStyleSheet("font-weight: bold; font-size: 15px; color: #38bdf8;")
        self.btn_prev = QPushButton("صفحه قبل ▶")
        self.btn_prev.setEnabled(False)
        self.btn_prev.clicked.connect(self.prev_page)
        
        self.btn_translate = QPushButton("🚀 شروع ترجمه صفحه")
        self.btn_translate.setStyleSheet("background-color: #5de387;") 
        self.btn_translate.setEnabled(False)
        self.btn_translate.clicked.connect(self.translate_current_page)
        
        self.btn_copy = QPushButton("📋 کپی ترجمه")
        self.btn_copy.setStyleSheet("background-color: #64748b;")
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self.copy_translation)
        
        nav_layout.addWidget(self.btn_next)
        nav_layout.addWidget(self.lbl_page)
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addStretch()
        nav_layout.addWidget(self.btn_copy)
        nav_layout.addWidget(self.btn_translate)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        
        workspace_layout = QHBoxLayout()
        workspace_layout.setSpacing(15)
        
        right_column = QVBoxLayout()
        lbl_right_title = QLabel("📝 ترجمه فارسی")
        lbl_right_title.setStyleSheet("font-weight: bold; color: #10b981;")
        self.txt_output = QTextEdit()
        self.txt_output.setReadOnly(True)
        self.txt_output.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.txt_output.setFont(QFont("Tahoma", 12))
        self.txt_output.setText("پس از شروع ترجمه، متن فارسی در این بخش ظاهر می‌شود.")
        right_column.addWidget(lbl_right_title)
        right_column.addWidget(self.txt_output)
        
        left_column = QVBoxLayout()
        lbl_left_title = QLabel("📖 تصویر صفحه فعلی کتاب")
        lbl_left_title.setStyleSheet("font-weight: bold; color: #3b82f6;")
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        
        self.lbl_image_viewer = QLabel()
        self.lbl_image_viewer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image_viewer.setText("تصویر صفحه کتاب به محض بارگذاری در این بخش رندر می‌شود.")
        self.lbl_image_viewer.setStyleSheet("background-color: #1e293b; color: #94a3b8;")
        
        self.scroll_area.setWidget(self.lbl_image_viewer)
        left_column.addWidget(lbl_left_title)
        left_column.addWidget(self.scroll_area)
        
        workspace_layout.addLayout(right_column, stretch=1)
        workspace_layout.addLayout(left_column, stretch=1)
        
        main_layout.addWidget(header_frame)
        main_layout.addWidget(nav_frame)
        main_layout.addWidget(self.progress_bar)
        main_layout.addLayout(workspace_layout)

    def render_page_image(self):
        """اصلاح قطعی تبدیل بایت‌های تصویر پی‌دی‌اف برای بارگذاری در PyQt"""
        if self.doc:
            try:
                page_obj = self.doc.load_page(self.current_page)
                # رندر صفحه به بایت‌های خام عکسی PNG
                pix = page_obj.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                image_bytes = pix.tobytes("png")
                
                # بارگذاری مستقیم بایت‌ها در ساختار گرافیکی PyQt بدون وابستگی به متغیرهای حذفی کتابخانه
                pixmap = QPixmap()
                pixmap.loadFromData(image_bytes)
                
                self.lbl_image_viewer.setPixmap(pixmap)
            except Exception as e:
                self.lbl_image_viewer.setText(f"خطا در رندر تصویری صفحه:\n{str(e)}")

    def update_ui_controls(self):
        if self.doc:
            self.lbl_page.setText(f"صفحه: {self.current_page + 1} / {self.total_pages}")
            self.btn_prev.setEnabled(self.current_page > 0)
            self.btn_next.setEnabled(self.current_page < self.total_pages - 1)
            self.btn_translate.setEnabled(True)
            self.render_page_image()

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "انتخاب کتاب", "", "Books (*.pdf *.epub)")
        if file_path:
            try:
                self.doc = fitz.open(file_path)
                self.total_pages = len(self.doc)
                self.current_page = 0
                self.lbl_file.setText(f"📂 فایل جاری: {os.path.basename(file_path)}")
                self.update_ui_controls()
                self.txt_output.setText("کتاب تصویری با موفقیت بارگذاری شد. آماده ترجمه هوشمند دیداری.")
            except Exception as e:
                self.txt_output.setText(f"خطا در باز کردن فایل:\n{str(e)}")

    def next_page(self):
        if self.doc and self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.txt_output.setText("برای ترجمه این صفحه روی دکمه شروع ترجمه کلیک کنید.")
            self.btn_copy.setEnabled(False)
            self.update_ui_controls()

    def prev_page(self):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self.txt_output.setText("برای ترجمه این صفحه روی دکمه شروع ترجمه کلیک کنید.")
            self.btn_copy.setEnabled(False)
            self.update_ui_controls()

    def translate_current_page(self):
        self.progress_bar.setVisible(True)
        self.btn_translate.setEnabled(False)
        self.btn_copy.setEnabled(False)
        self.txt_output.setText("...هوش مصنوعی در حال خواندن متن از روی عکس صفحه و ترجمه آن است...")
        
        self.worker = TranslationWorker(self.doc, self.current_page)
        self.worker.finished.connect(self.on_translation_finished)
        self.worker.start()
        
    def on_translation_finished(self, result):
        self.progress_bar.setVisible(False)
        self.btn_translate.setEnabled(True)
        self.txt_output.setText(result)
        self.btn_copy.setEnabled(True)

    def copy_translation(self):
        text_to_copy = self.txt_output.toPlainText()
        if text_to_copy:
            clipboard = QApplication.clipboard()
            clipboard.setText(text_to_copy)
            QMessageBox.information(self, "موفقیت", "متن ترجمه با موفقیت کپی شد! ✅", QMessageBox.StandardButton.Ok)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ModernTranslatorApp()
    window.show()
    sys.exit(app.exec())