"""Gear mesh geometry: vertex/index buffers -> positions, UVs, normals, triangles."""

import struct

import numpy as np

from d1kit.pkg.tags import entry, read

# The game is Z-up; glTF is Y-up.
Z_UP_TO_Y_UP = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float32)


def vertex_buffer(tag):
    hdr = read(tag)
    size, stride = struct.unpack_from("<II", hdr, 0)
    _, e = entry(tag)
    return np.frombuffer(read(e["reference"])[:size], dtype=np.uint8).reshape(-1, stride), stride


def index_buffer(tag):
    _, e = entry(tag)
    return np.frombuffer(read(e["reference"]), dtype="<u2")


def s16(cols):
    return cols.copy().view("<i2").astype(np.float32) / 32767.0


def triangles(idx):
    """All D1 PS4 gear index ranges are triangle strips with 0xFFFF restart (the part 'prim' byte is not topology)."""
    out, strip = [], []
    for v in idx.tolist() + [0xFFFF]:
        if v != 0xFFFF:
            strip.append(v)
            continue
        for i in range(len(strip) - 2):
            a, b, c = strip[i], strip[i + 1], strip[i + 2]
            if i & 1:
                a, b = b, a
            out.append((a, b, c))
        strip = []
    return [t for t in out if t[0] != t[1] and t[1] != t[2] and t[0] != t[2]]


def decode_mesh(m):
    """Mesh dict (gear.parse_mesh_tag) -> (positions, uvs or None, normals or None, index buffer)."""
    vb0, st0 = vertex_buffer(m["vbs"][0])
    pos = s16(vb0[:, 0:6]).reshape(-1, 3) * np.array(m["pos_scale"][:3], np.float32) + np.array(
        m["pos_offset"][:3], np.float32
    )
    uv = nrm = None
    if len(m["vbs"]) > 1:
        vb1, st1 = vertex_buffer(m["vbs"][1])
        # Two layouts: VB0 stride 8 = pos only, VB1 = uv, normal, tangent (+4).
        #              VB0 stride 12 = pos + uv (later-content meshes), VB1 = normal, tangent (+4).
        uv_src, nrm_at = (vb0[:, 8:12], 0) if st0 >= 12 else (vb1[:, 0:4], 4)
        uv = s16(uv_src).reshape(-1, 2) * np.array(m["uv_scale"], np.float32) + np.array(m["uv_offset"], np.float32)
        nrm = s16(vb1[:, nrm_at : nrm_at + 6]).reshape(-1, 3)
        ln = np.linalg.norm(nrm, axis=1, keepdims=True)
        nrm = np.where(ln > 1e-6, nrm / np.maximum(ln, 1e-6), np.array([0, 0, 1], np.float32))
    return pos, uv, nrm, index_buffer(m["ib"])


def fix_winding(tris, pos, nrm):
    """Return tris in CCW (glTF) order, decided by agreement with vertex normals."""
    if nrm is None or not tris:
        return tris
    t = np.array(tris)
    fn = np.cross(pos[t[:, 1]] - pos[t[:, 0]], pos[t[:, 2]] - pos[t[:, 0]])
    agree = np.einsum("ij,ij->i", fn, nrm[t].sum(axis=1))
    if (agree < 0).sum() > (agree > 0).sum():
        t = t[:, [0, 2, 1]]
    return [tuple(x) for x in t.tolist()]


def primitive(tris, pos, uv, nrm, key):
    """One glTF primitive from a group of triangles: only the vertices it uses, re-indexed, converted to Y-up."""
    tris = fix_winding(tris, pos, nrm)
    used = np.unique(np.array(tris).reshape(-1))
    remap = np.full(len(pos), -1, np.int64)
    remap[used] = np.arange(len(used))
    return dict(
        pos=pos[used] @ Z_UP_TO_Y_UP.T,
        nrm=None if nrm is None else nrm[used] @ Z_UP_TO_Y_UP.T,
        uv=None if uv is None else uv[used],
        idx=remap[np.array(tris)],
        key=key,
    )
