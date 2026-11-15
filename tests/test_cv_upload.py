"""Başvuru botunun CV yükleme adımı — yerel test formlarında, başsız tarayıcıyla (internet yok, gönderim yok).
Çalıştırma:  venv/bin/python -m unittest discover -s tests -v
"""
import os
import tempfile
import unittest

from browser.automator import try_upload_cv, choose_cv, _accepts

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as _p:
        _b = _p.chromium.launch(headless=True)
        _b.close()
    HAS_BROWSER = True
except Exception:  # tarayıcı kurulu değilse bu testler atlanır
    HAS_BROWSER = False


FORM_WITH_PHOTO = """<form>
  <label for="ph">Profil fotoğrafı</label><input type="file" id="ph" name="photo" accept="image/*">
  <div><label for="cv">Özgeçmiş yükle</label><input type="file" id="cv" name="resume"></div>
</form>"""
FORM_PDF_ONLY = """<div><label for="cv">Upload resume</label><input type="file" id="cv" accept=".pdf"></div>"""
FORM_NO_FILE = """<form><input type="text" name="ad"></form>"""


def _uploaded(page, sel):
    return page.eval_on_selector(sel, "e => e.files.length ? e.files[0].name : null")


class AcceptTests(unittest.TestCase):
    def test_accepts(self):
        self.assertTrue(_accepts("", "a.docx"))
        self.assertTrue(_accepts(".pdf,.docx", "a.docx"))
        self.assertFalse(_accepts(".pdf", "a.docx"))
        self.assertTrue(_accepts("application/pdf", "a.pdf"))
        self.assertTrue(_accepts("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "a.docx"))

    def test_choose_cv_prefers_tailored(self):
        with tempfile.NamedTemporaryFile(suffix=".docx") as f:
            self.assertEqual(choose_cv(f.name), f.name)
        self.assertNotEqual(choose_cv("/yok/boyle/bir/dosya.docx"), "/yok/boyle/bir/dosya.docx")
        self.assertEqual(choose_cv(float("nan")), choose_cv(None))  # pandas boş hücre = NaN


@unittest.skipUnless(HAS_BROWSER, "Playwright Chromium kurulu değil")
class UploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.docx = os.path.join(cls.tmp.name, "ozel_CV.docx")
        cls.pdf = os.path.join(cls.tmp.name, "Cv.pdf")
        for p in (cls.docx, cls.pdf):
            with open(p, "wb") as fh:
                fh.write(b"test")
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.tmp.cleanup()

    def page(self, html):
        p = self.browser.new_page()
        p.set_content(html)
        self.addCleanup(p.close)
        return p

    def test_uploads_to_resume_field_not_photo(self):
        p = self.page(FORM_WITH_PHOTO)
        self.assertEqual(try_upload_cv(p, self.docx, self.pdf), self.docx)
        self.assertEqual(_uploaded(p, "#cv"), "ozel_CV.docx")
        self.assertIsNone(_uploaded(p, "#ph"))

    def test_pdf_only_field_falls_back_to_original(self):
        p = self.page(FORM_PDF_ONLY)
        self.assertEqual(try_upload_cv(p, self.docx, self.pdf), self.pdf)
        self.assertEqual(_uploaded(p, "#cv"), "Cv.pdf")

    def test_no_file_field(self):
        self.assertIsNone(try_upload_cv(self.page(FORM_NO_FILE), self.docx, self.pdf))


if __name__ == "__main__":
    unittest.main()
