"""Add one LC_LOAD_DYLIB in existing arm64 Mach-O header padding.

No section offsets, virtual addresses or executable instructions are changed.
The caller must verify its supported build and sign the result before launch.
"""
import struct


def add_dylib(data, path):
    if not isinstance(data, bytes) or len(data) < 32:
        raise ValueError('truncated Mach-O')
    if not isinstance(path, str) or not path.startswith('@executable_path/') or '\0' in path:
        raise ValueError('expected a bundle-relative dylib path')
    magic, cpu, _, kind, count, size, _, _ = struct.unpack_from('<8I', data)
    if magic != 0xfeedfacf or cpu != 0x100000c or kind != 2:
        raise ValueError('expected an arm64 MH_EXECUTE image')
    end = 32 + size
    if end > len(data) or count > size // 8:
        raise ValueError('invalid command table')
    cursor = 32
    first_section = len(data)
    encoded = path.encode('utf-8') + b'\0'
    found = False
    for _ in range(count):
        if cursor + 8 > end:
            raise ValueError('truncated load command')
        cmd, length = struct.unpack_from('<II', data, cursor)
        if length < 8 or length % 8 or cursor + length > end:
            raise ValueError('invalid load command size')
        if cmd == 0x19:
            if length < 72:
                raise ValueError('truncated segment')
            sections = struct.unpack_from('<I', data, cursor + 64)[0]
            if 72 + sections * 80 > length:
                raise ValueError('truncated section table')
            for i in range(sections):
                section = cursor + 72 + i * 80
                offset = struct.unpack_from('<I', data, section + 48)[0]
                if offset:
                    first_section = min(first_section, offset)
        if cmd == 0xc:
            if length < 24:
                raise ValueError('truncated dylib command')
            name = struct.unpack_from('<I', data, cursor + 8)[0]
            if not 24 <= name < length:
                raise ValueError('invalid dylib name offset')
            found |= data[cursor + name:cursor + length].split(b'\0', 1)[0] == encoded[:-1]
        cursor += length
    if cursor != end:
        raise ValueError('command count does not match table size')
    if found:
        return data
    length = (24 + len(encoded) + 7) & ~7
    if end + length > first_section or any(data[end:end + length]):
        raise ValueError('insufficient empty header padding')
    command = struct.pack('<6I', 0xc, length, 24, 0, 0x10000, 0x10000) + encoded
    result = bytearray(data)
    result[end:end + length] = command.ljust(length, b'\0')
    struct.pack_into('<II', result, 16, count + 1, size + length)
    return bytes(result)
