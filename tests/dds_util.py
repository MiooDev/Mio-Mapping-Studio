"""Generation de petits fichiers DDS synthetiques pour les tests (aucune texture Rockstar).

Formats produits :
  - DXT1 (BC1) avec mipmaps, couleur unie par niveau ;
  - DXT5 (BC3) avec alpha, mipmaps ;
  - A8R8G8B8 non compresse avec mipmaps.
"""

import struct

DDSD_CAPS = 0x1
DDSD_HEIGHT = 0x2
DDSD_WIDTH = 0x4
DDSD_PITCH = 0x8
DDSD_PIXELFORMAT = 0x1000
DDSD_MIPMAPCOUNT = 0x20000
DDSD_LINEARSIZE = 0x80000
DDPF_ALPHAPIXELS = 0x1
DDPF_FOURCC = 0x4
DDPF_RGB = 0x40
DDSCAPS_COMPLEX = 0x8
DDSCAPS_TEXTURE = 0x1000
DDSCAPS_MIPMAP = 0x400000


def _rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _mip_count(w, h, min_size=1):
    """Nombre de niveaux de mips. Les textures GTA compressees (BCn) s'arretent a 4x4 :
    le format RAGE calcule la taille de chaque mip par division par 4, ce qui tronque
    les niveaux 2x2 et 1x1 d'un DDS standard."""
    n = 1
    while min(w, h) // 2 >= min_size and (w > 1 or h > 1):
        w = max(1, w // 2)
        h = max(1, h // 2)
        n += 1
    return n


def make_dds(width, height, fmt="DXT1", color=(200, 80, 40), alpha=255, mips=True):
    levels = _mip_count(width, height, 4 if fmt in ("DXT1", "DXT5") else 1) if mips else 1
    data = bytearray()
    w, h = width, height
    for lvl in range(levels):
        # couleur legerement differente par niveau pour detecter une perte de mips
        r, g, b = [(c + 7 * lvl) % 256 for c in color]
        bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
        if fmt == "DXT1":
            c = _rgb565(r, g, b)
            block = struct.pack("<HHI", c, c, 0)
            data += block * (bw * bh)
        elif fmt == "DXT5":
            ablock = struct.pack("<BB", alpha, alpha) + b"\x00" * 6
            c = _rgb565(r, g, b)
            cblock = struct.pack("<HHI", c, c, 0)
            data += (ablock + cblock) * (bw * bh)
        elif fmt == "A8R8G8B8":
            data += bytes((b, g, r, alpha)) * (w * h)
        else:
            raise ValueError(fmt)
        w, h = max(1, w // 2), max(1, h // 2)

    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    caps = DDSCAPS_TEXTURE
    if levels > 1:
        flags |= DDSD_MIPMAPCOUNT
        caps |= DDSCAPS_COMPLEX | DDSCAPS_MIPMAP
    if fmt in ("DXT1", "DXT5"):
        flags |= DDSD_LINEARSIZE
        bsize = 8 if fmt == "DXT1" else 16
        pitch = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * bsize
        pf = struct.pack("<II4sIIIII", 32, DDPF_FOURCC, fmt.encode(), 0, 0, 0, 0, 0)
    else:
        flags |= DDSD_PITCH
        pitch = width * 4
        pf = struct.pack("<II4sIIIII", 32, DDPF_RGB | DDPF_ALPHAPIXELS, b"\0\0\0\0", 32,
                         0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    header = struct.pack("<4sIIIIIII", b"DDS ", 124, flags, height, width, pitch, 0, levels)
    header += b"\0" * 44
    header += pf
    header += struct.pack("<IIIII", caps, 0, 0, 0, 0)
    assert len(header) == 128
    return bytes(header) + bytes(data)


def write_dds(path, *args, **kwargs):
    with open(path, "wb") as f:
        f.write(make_dds(*args, **kwargs))
    return path
