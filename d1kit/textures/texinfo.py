"""Decode D1 PS4 texture headers (GNM T# descriptor + Tiger tail)."""

import struct
import sys

from d1kit.pkg.tags import entry, read

FORMATS = {
    35: "BC1",
    36: "BC2",
    37: "BC3",
    38: "BC4",
    39: "BC5",
    40: "BC6",
    41: "BC7",
    10: "R8G8B8A8",
    1: "R8",
    3: "R8G8",
    4: "R32",
    5: "R16G16",
    12: "R16G16B16A16",
}
TYPES = {9: "2d", 11: "cube", 10: "3d", 13: "2d_array"}


def texinfo(t):
    p, e = entry(t)
    h = read(t)
    w = struct.unpack_from("<8I", h, 0)
    info = dict(
        tag=t,
        fmt=(w[1] >> 20) & 0x3F,
        numfmt=(w[1] >> 26) & 0xF,
        width=(w[2] & 0x3FFF) + 1,
        height=((w[2] >> 14) & 0x3FFF) + 1,
        base_level=(w[3] >> 12) & 0xF,
        last_level=(w[3] >> 16) & 0xF,
        tile=(w[3] >> 20) & 0x1F,
        type=w[3] >> 28,
        depth=(w[4] & 0x1FFF) + 1,
        pitch=((w[4] >> 13) & 0x3FFF) + 1,
        dst_sel=w[3] & 0xFFF,
        data_tag=e["reference"],
        tail=h[0x24:].hex(),
    )
    info["fmt_name"] = FORMATS.get(info["fmt"], f"fmt{info['fmt']}")
    info["type_name"] = TYPES.get(info["type"], f"type{info['type']}")
    if e["reference"] != 0xFFFFFFFF:
        _, f = entry(e["reference"])
        info["data_kind"] = f"t{f['type']}/s{f['subtype']}"
        info["data_size"] = f["size"]
    return info


if __name__ == "__main__":
    for a in sys.argv[1:]:
        print(texinfo(int(a, 16)))
