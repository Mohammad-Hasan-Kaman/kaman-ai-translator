# 📚 AI PDF & EPUB Translator

> A powerful desktop application for translating **PDF and EPUB** documents from English to academic Persian (Farsi) using Google Gemini AI. Built with PyQt6 for a modern, responsive interface.

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?logo=python&logoColor=white)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-Modern%20UI-purple.svg?logo=qt)](https://riverbankcomputing.com/software/pyqt/)
[![Google-Gemini](https://img.shields.io/badge/Google-Gemini%20AI-orange.svg?logo=google)](https://gemini.google.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 🚀 Purpose & Target Audience

This project is designed for **"Academic PDF Translation"** targeting students, researchers, and professionals who need high-quality, fluent Persian translations of English academic papers and books.

| Audience | Usage Method |
|----------|--------------|
| **End Users** | Download and run the compiled `.exe` file (no Python installation required). |
| **Developers** | Clone, install dependencies, and run the source code for customization. |

---

## ✨ Key Features

- 🌐 **Multi-Format Translation (PDF & EPUB):**
  - Seamlessly translates both **PDF documents** and **EPUB ebooks**.
  - Optimized for **academic, psychological, and philosophical texts** with formal, dignified Persian prose.
  - Supports page-by-page or chapter-by-chapter translation.
- 🎨 **Modern PyQt6 Interface:**
  - Clean, responsive UI with progress bars and real-time status updates.
  - Multi-threaded architecture to prevent UI freezing during heavy translation tasks.
- 🖼️ **Custom Icon & Desktop Ready:**
  - Includes a custom application icon.
  - Ready-to-run executable (`.exe`) for Windows.
- 🔐 **API Key Management:**
  - Secure configuration for your Google GenAI API key.

---

## 📥 Installation & Setup

### 1. For End Users (Compiled Executable)

1.  Download the latest release (`translator_app_v2.exe`) from the [Releases](https://github.com/Mohammad-Hasan-Kaman/ai-pdf-translator/releases) page.
2.  Run the executable.
3.  **Configure API Key:**
    - Open `translator_app_v2.py` in the source code (if you have it).
    - Replace `"API_KEY"` on line 17 with your actual **Google GenAI API Key**.
    - *(Alternatively, if using the EXE, you may need to set it via a config file or prompt).*
4.  Select a PDF file, choose pages, and translate!

### 2. For Developers (Source Code)

```bash
# Clone the repository
git clone https://github.com/Mohammad-Hasan-Kaman/ai-pdf-translator.git
cd ai_pdf_translator

# Create a virtual environment (optional but recommended)
python -m venv venv
venv\Scripts\activate  # On Windows

# Install dependencies
pip install PyQt6 PyMuPDF Pillow google-genai

# Run the application
python translator_app_v2.py
```

---

## 🛠 Tech Stack & Libraries

| Technology | Role |
|------------|------|
| **Python 3.10+** | Core programming language |
| **PyQt6** | Modern Desktop UI Framework |
| **PyMuPDF (fitz)** | PDF Text Extraction |
| **Pillow (PIL)** | Image Processing (if needed for embedded images) |
| **Google GenAI** | AI Translation Engine (Gemini) |
| **QThread** | Multi-threaded background processing |

---

## 📝 How to Use

1.  **Launch the App:** Run `translator_app_v2.exe` or `python translator_app_v2.py`.
2.  **Select PDF:** Click "Choose PDF" to load your document.
3.  **Choose Pages:** Select specific pages or translate the entire document.
4.  **Translate:** Click the "Translate" button.
5.  **View Output:** The translated text will appear in the result box. You can copy or save it.

---

## 📂 Project Structure

```
ai_pdf_translator/
├── translator_app_v2.py   # Main application logic & UI
├── translator_app_v2.exe  # Compiled executable (Windows)
├── icon.png               # App icon (source)
├── icon.ico               # App icon (Windows)
├── LICENSE                # MIT License
├── README.md              # This file
└── requirements.txt       # Python dependencies (if generated)
```

---

## ⚙️ Configuration

To make the app work, you need a **Google GenAI API Key**:
1.  Go to [Google AI Studio](https://aistudio.google.com/).
2.  Create an API Key.
3.  Paste it into `translator_app_v2.py` where it says `API_KEY = "API_KEY"`.

---

## 🤝 Contributing

Found a bug or have a suggestion? Please open an [Issue](https://github.com/Mohammad-Hasan-Kaman/ai-pdf-translator/issues).
Contributions are welcome!

---

## ⭐ Support

If you find this tool useful, please give it a **star**! ⭐

[![Star History](https://api.star-history.com/svg?repos=kaman-ai-translator&type=Date)](https://star-history.com/#kaman-ai-translator&Date)

---
*Maintained by Mohammad Hasan Kaman | Last updated: July 2026*

> **Disclaimer:** This tool uses external AI APIs (Google GenAI). Ensure you have sufficient quota in your account. Translation quality depends on the AI model's capabilities.