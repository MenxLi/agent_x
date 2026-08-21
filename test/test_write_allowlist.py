import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from xun.tools.common import WriteAllowList


class WriteAllowListTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_file_entry_matches_only_exact_path(self) -> None:
        alist = WriteAllowList()
        note = self.root / "note.md"
        note.touch()
        alist.add(note)
        self.assertTrue(alist.has(note))
        self.assertFalse(alist.has(self.root / "note.md.bak"))
        self.assertFalse(alist.has(self.root / "sub" / "note.md"))

    def test_directory_entry_matches_subpaths(self) -> None:
        alist = WriteAllowList()
        base = self.root / "proj"
        base.mkdir()
        alist.add(base, is_dir=True)
        self.assertTrue(alist.has(base))
        self.assertTrue(alist.has(base / "a" / "b.txt"))
        self.assertFalse(alist.has(self.root / "sibling.txt"))
        # string prefix is not a path prefix
        self.assertFalse(alist.has(self.root / "proj2" / "x.txt"))

    def test_add_records_type_at_add_time(self) -> None:
        alist = WriteAllowList()
        note = self.root / "x.txt"
        note.touch()
        base = self.root / "dir"
        base.mkdir()
        alist.add(note)  # defaults to file
        alist.add(base, is_dir=True)
        self.assertFalse(alist.entries[note.resolve()])
        self.assertTrue(alist.entries[base.resolve()])

    def test_readd_overwrites_existing_entry(self) -> None:
        alist = WriteAllowList()
        base = self.root / "x"
        base.mkdir()
        alist.add(base)  # recorded as file even though it's a directory on disk
        alist.add(base, is_dir=True)
        self.assertTrue(alist.entries[base.resolve()])
        self.assertTrue(alist.has(base / "y.txt"))

    def test_remove_by_path_regardless_of_type(self) -> None:
        alist = WriteAllowList()
        base = self.root / "x"
        base.mkdir()
        alist.add(base, is_dir=True)
        alist.remove(base)
        self.assertEqual(alist.entries, {})
        self.assertFalse(alist.has(base))
        self.assertFalse(alist.has(base / "y.txt"))

    def test_directory_entry_matches_even_if_dir_no_longer_exists(self) -> None:
        # is_dir is recorded at add time, so later disk state must not matter
        alist = WriteAllowList()
        base = self.root / "gone"
        base.mkdir()
        alist.add(base, is_dir=True)
        base.rmdir()
        self.assertTrue(alist.has(base / "f.txt"))


if __name__ == "__main__":
    unittest.main()
