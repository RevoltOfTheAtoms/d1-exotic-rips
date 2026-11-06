"""Summarise source-asset folders found in strings_*.tsv dumps.

usage: paths_summary.py <filter word> [tsv ...]
"""

import collections
import glob
import os
import re
import sys

word = sys.argv[1].lower()
files = sys.argv[2:] or glob.glob(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "analysis", "strings_*.tsv")
)
rx = re.compile(r"content\\[A-Za-z0-9_\\.\-]+")
cut = re.compile(r"\\(textures|materials|shaders|models|geometry|gear|frame)\\", re.I)
folders = collections.Counter()
for f in files:
    for line in open(f, encoding="latin-1"):
        if word not in line.lower():
            continue
        for m in rx.findall(line):
            if word in m.lower():
                folders[cut.split(m)[0]] += 1
for k, v in sorted(folders.items()):
    print(f"{v:5d}  {k}")
