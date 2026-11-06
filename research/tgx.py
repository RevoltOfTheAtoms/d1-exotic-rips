"""Read Bungie's D1 web gear containers (.tgxm): files + render_metadata.js (per-part dye choice, flags).

Layout (destiny-tgx-loader notes): 'TGXM', u32 version, u32 file table offset, u32 file count, then per file
0x110 bytes: name[0x100], u32 offset, u32 type, u32 size.
"""

import json
import struct


def read_tgxm(path):
    d = open(path, "rb").read()
    assert d[:4] == b"TGXM", path
    _ver, off, n = struct.unpack_from("<III", d, 4)
    files = {}
    for i in range(n):
        h = off + 0x110 * i
        name = d[h : h + 0x100].split(b"\0")[0].decode()
        o, _t, size = struct.unpack_from("<III", d, h + 0x100)
        files[name] = d[o : o + size]
    meta = next(
        (json.loads(v.decode("utf-8", "replace").rstrip("\0")) for k, v in files.items() if k.endswith(".js")), None
    )
    return files, meta


def stage_parts(meta):
    """[(mesh index, part)] for every stage part: start_index, index_count, gear_dye_change_color_index, flags..."""
    return [(mi, p) for mi, m in enumerate(meta["render_model"]["render_meshes"]) for p in m["stage_part_list"]]


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        files, meta = read_tgxm(path)
        print("==", path.split("\\")[-1].split("/")[-1], list(files)[:6])
        for mi, p in stage_parts(meta):
            print(
                f"  mesh {mi} start {p['start_index']:>6} count {p['index_count']:>6}"
                f" cci {p['gear_dye_change_color_index']}"
                f" flags {p['flags']:>4} lod {p['lod_category']['value']:>2} shader {p['shader']['type']}"
                f" ext {p['external_identifier']}"
            )
