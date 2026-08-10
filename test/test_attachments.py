import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from xun.attachments import AttachmentError, AttachmentStore


class AttachmentStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.store = AttachmentStore(Path(self.tempdir.name), max_bytes=1024)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def image_bytes(self, format: str = "PNG") -> bytes:
        output = BytesIO()
        Image.new("RGB", (2, 2), "red").save(output, format=format)
        return output.getvalue()

    def test_saves_and_resolves_verified_image(self) -> None:
        attachment_id = self.store.save_image(self.image_bytes())
        self.assertRegex(attachment_id, r"^[0-9a-f]{32}\.png$")
        self.assertEqual(self.store.resolve(attachment_id).read_bytes(), self.image_bytes())

    def test_rejects_invalid_oversized_and_unknown_ids(self) -> None:
        with self.assertRaises(AttachmentError):
            self.store.save_image(b"not an image")
        with self.assertRaises(AttachmentError):
            self.store.save_image(b"x" * 1025)
        with self.assertRaises(AttachmentError):
            self.store.resolve("../image.png")
        with self.assertRaises(AttachmentError):
            self.store.resolve("0" * 32 + ".png")

        outside = Path(self.tempdir.name).parent / "outside.png"
        outside.write_bytes(self.image_bytes())
        self.addCleanup(outside.unlink, missing_ok=True)
        attachment_id = "1" * 32 + ".png"
        (self.store.directory / attachment_id).symlink_to(outside)
        with self.assertRaises(AttachmentError):
            self.store.resolve(attachment_id)


if __name__ == "__main__":
    unittest.main()
