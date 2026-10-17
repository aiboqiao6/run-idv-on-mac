import struct
import unittest
from macho_load import add_dylib


class MachOLoadTests(unittest.TestCase):
    def sample(self):
        # __TEXT segment and one section starting after command padding.
        segment = struct.pack('<II16sQQQQIIII', 0x19, 152, b'__TEXT',
                              0x100000000, 0x4000, 0, 0x4000, 5, 5, 1, 0)
        section = struct.pack('<16s16sQQIIIIIIII', b'__text', b'__TEXT',
                              0x100001000, 16, 4096, 2, 0, 0, 0, 0, 0, 0)
        header = struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 1, len(segment+section), 0, 0)
        return (header+segment+section).ljust(4096, b'\0')+b'CODE MUST STAY!!'

    def test_add_keeps_sections_and_code_at_original_offsets(self):
        original = self.sample()
        changed = add_dylib(original, '@executable_path/PCSupport/libIDVNativeInput.dylib')
        self.assertEqual(changed[4096:], original[4096:])
        self.assertEqual(len(changed), len(original))
        self.assertEqual(struct.unpack_from('<I', changed, 16)[0], 2)
        self.assertIn(b'@executable_path/PCSupport/libIDVNativeInput.dylib\0', changed[:4096])

    def test_repeated_install_does_not_duplicate_command(self):
        path = '@executable_path/PCSupport/libIDVNativeInput.dylib'
        changed = add_dylib(self.sample(), path)
        self.assertEqual(add_dylib(changed, path), changed)

    def test_rejects_nonzero_padding(self):
        data = bytearray(self.sample())
        data[184] = 1
        with self.assertRaises(ValueError):
            add_dylib(bytes(data), '@executable_path/PCSupport/libIDVNativeInput.dylib')

    def test_rejects_invalid_header_and_command_sizes(self):
        for data in (b'', b'fake', bytes(4096)):
            with self.assertRaises(ValueError):
                add_dylib(data, '@executable_path/test.dylib')
        data = bytearray(self.sample())
        struct.pack_into('<I', data, 36, 0)
        with self.assertRaises(ValueError):
            add_dylib(bytes(data), '@executable_path/test.dylib')
