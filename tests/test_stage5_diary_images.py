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

    def test_v2_dimension_limit_is_enforced(self):
        valid_1280 = make_image(size=(1280, 960))
        oversized_1281 = make_image(size=(1281, 960))
        self.assertTrue(
            valid_diary_jpeg(
                valid_1280,
                max_dimension=1280,
                max_pixels=1280 * 1280,
                reject_metadata=True,
            )
        )
        self.assertFalse(
            valid_diary_jpeg(
                oversized_1281,
                max_dimension=1280,
                max_pixels=1280 * 1280,
                reject_metadata=True,
            )
        )

    def test_v2_rejects_exif_and_comment_metadata(self):
        exif = Image.Exif()
        exif[0x010F] = "CameraMaker"
        buf_exif = io.BytesIO()
        with Image.new("RGB", (16, 16), "white") as image:
            image.save(buf_exif, format="JPEG", exif=exif.tobytes())
        jpeg_with_exif = buf_exif.getvalue()

        self.assertTrue(valid_diary_jpeg(jpeg_with_exif, reject_metadata=False))
        self.assertFalse(valid_diary_jpeg(jpeg_with_exif, reject_metadata=True))

        buf_comment = io.BytesIO()
        with Image.new("RGB", (16, 16), "white") as image:
            image.save(buf_comment, format="JPEG", comment=b"gps-note")
        jpeg_with_comment = buf_comment.getvalue()

        self.assertFalse(
            valid_diary_jpeg(jpeg_with_comment, reject_metadata=True)
        )


if __name__ == "__main__":
    unittest.main()