"""Validate diary images using real encoded files."""
import io
import unittest

from PIL import Image
from avenra.services.diary_service import valid_diary_jpeg


def make_image(format="JPEG", size=(16, 16)):
    buffer = io.BytesIO()
    with Image.new("RGB", size, "white") as image:
        image.save(buffer, format=format)
    return buffer.getvalue()


class DiaryImageTests(unittest.TestCase):
    def test_real_jpeg_is_accepted_without_modifying_bytes(self):
        photo = make_image()
        original = bytes(photo)
        self.assertTrue(valid_diary_jpeg(photo))
        self.assertEqual(photo, original)

    def test_jpeg_prefix_does_not_make_text_an_image(self):
        self.assertFalse(valid_diary_jpeg(b"\xff\xd8not-a-jpeg"))

    def test_png_is_rejected(self):
        self.assertFalse(valid_diary_jpeg(make_image("PNG")))

    def test_truncated_jpeg_is_rejected(self):
        photo = make_image()
        self.assertFalse(valid_diary_jpeg(photo[:len(photo) // 2]))

    def test_missing_end_of_image_is_rejected(self):
        photo = make_image()
        self.assertFalse(valid_diary_jpeg(photo[:-2]))

    def test_excessive_dimension_is_rejected(self):
        self.assertFalse(
            valid_diary_jpeg(make_image(size=(8193, 1)))
        )

    def test_excessive_pixel_count_is_rejected(self):
        self.assertFalse(
            valid_diary_jpeg(make_image(size=(4001, 4000)))
        )

    def test_empty_input_is_rejected(self):
        self.assertFalse(valid_diary_jpeg(b""))


if __name__ == "__main__":
    unittest.main()