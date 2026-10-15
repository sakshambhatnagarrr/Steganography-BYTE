#!/usr/bin/env python3
"""
solve.py - fixing the corrupted PNG from the stego challenge

Usage:
    python solve.py challenge.png        (output goes to repaired.png)

What was wrong with the file (and what this script does about it):
  1. The height in the IHDR header had been shrunk (800 instead of 850),
     which hid the bottom 50 rows of the picture.
  2. 12 junk bytes had been shoved into the middle of one IDAT chunk without
     updating its length, so the compressed pixel data fell apart and turned
     into noise partway down the image.

The trick behind both fixes is the same: a CRC is a fingerprint of a chunk's
contents. If a guess makes the fingerprint match the stored one, the guess
is right. Nobody matches a 32-bit fingerprint by accident.
"""
import re
import struct
import sys
import zlib

SIG = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}   # PNG colour type -> channels per pixel


def crc(data, start=0):
    return zlib.crc32(data, start) & 0xFFFFFFFF


def make_chunk(name, data):
    # a PNG chunk = length + name + data + CRC
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc(name + data))


def die(msg):
    print("\n[!]", msg)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Step 1: is it even a PNG?
# ---------------------------------------------------------------------------
def check_signature(d):
    if d[:8] == SIG:
        print("[ok] PNG signature is fine")
        return d
    print("[fix] signature was damaged, putting the right 8 bytes back")
    return SIG + d[8:]


# ---------------------------------------------------------------------------
# Step 2: IHDR. Find the real height by asking the CRC.
# ---------------------------------------------------------------------------
def fix_header(d):
    ihdr = d[16:29]                                  # width, height, depth, colour...
    stored = struct.unpack(">I", d[29:33])[0]

    if crc(b"IHDR" + ihdr) == stored:
        w, h = struct.unpack(">II", ihdr[:8])
        print(f"[ok] header already matches its CRC ({w} x {h})")
        return ihdr

    w, h = struct.unpack(">II", ihdr[:8])
    print(f"[..] header says {w} x {h} but its CRC disagrees, trying heights...")

    # most likely only the height was edited, so try that first (fast)
    for new_h in range(1, 20001):
        cand = ihdr[:4] + struct.pack(">I", new_h) + ihdr[8:]
        if crc(b"IHDR" + cand) == stored:
            print(f"[fix] real height is {new_h} (header claimed {h})")
            return cand

    # otherwise width might be edited too, so try both (slower)
    print("[..] not just the height, trying width and height together...")
    for new_w in range(1, 4001):
        for new_h in range(1, 4001):
            cand = struct.pack(">II", new_w, new_h) + ihdr[8:]
            if crc(b"IHDR" + cand) == stored:
                print(f"[fix] real size is {new_w} x {new_h}")
                return cand

    die("couldn't match the header CRC. Another IHDR field (bit depth, "
        "colour type...) may have been edited. Check bytes 24-28 by hand.")


# ---------------------------------------------------------------------------
# Step 3: the pixel chunks (IDAT).
# I don't trust the length fields, since the author messed with them. Instead
# I find each chunk by looking for its name and measure the space in between.
# A stray "IEND" can also hide inside the compressed data, so only the LAST
# one counts as the real end.
# ---------------------------------------------------------------------------
def find_junk(body, stored, k):
    """Remove k bytes from body so that the chunk's CRC matches `stored`."""
    print(f"      searching for {k} inserted bytes (this can take a bit)...")
    mv = memoryview(body)
    running = crc(b"IDAT")                           # CRC of "IDAT" + body[:p]
    for p in range(len(body) - k + 1):
        if crc(mv[p + k:], running) == stored:       # same as dropping body[p:p+k]
            return p
        running = crc(mv[p:p + 1], running)
    return None


def repair_idats(d):
    idat_marks = [m.start() for m in re.finditer(rb"IDAT", d[33:])]
    idat_marks = [m + 33 for m in idat_marks]
    end_mark = d.rfind(b"IEND")
    if not idat_marks or end_mark == -1:
        die("couldn't find IDAT/IEND chunks at all")

    print(f"[..] found {len(idat_marks)} IDAT chunks")
    bodies = []
    for i, m in enumerate(idat_marks):
        nxt = idat_marks[i + 1] if i + 1 < len(idat_marks) else end_mark
        blob = d[m + 4: nxt - 4]                     # data + CRC (nxt-4 is the next length field)
        body, stored = blob[:-4], struct.unpack(">I", blob[-4:])[0]
        declared = struct.unpack(">I", d[m - 4:m])[0]
        extra = len(body) - declared

        if crc(b"IDAT" + body) == stored:
            note = "" if extra == 0 else f" (its length field lied by {extra}, harmless)"
            print(f"  chunk {i + 1}: ok{note}")
        elif extra > 0:
            print(f"  chunk {i + 1}: BAD CRC and {extra} more bytes than it claims. Suspicious!")
            p = find_junk(body, stored, extra)
            if p is None:
                print(f"  chunk {i + 1}: no clean removal found, leaving it alone")
            else:
                print(f"  chunk {i + 1}: FOUND IT. Junk at byte {p} of the chunk: "
                      f"{body[p:p + extra].hex(' ')}")
                body = body[:p] + body[p + extra:]
        else:
            print(f"  chunk {i + 1}: BAD CRC but the size looks normal, "
                  "so it's something other than inserted bytes")
        bodies.append(body)
    return bodies


# ---------------------------------------------------------------------------
# Step 4: put it back together and check that it really decodes.
# ---------------------------------------------------------------------------
def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "challenge.png"
    try:
        d = open(path, "rb").read()
    except FileNotFoundError:
        die(f"can't find {path}. Put it next to solve.py or pass its name.")
    print(f"reading {path} ({len(d)} bytes)\n")

    d = check_signature(d)
    ihdr = fix_header(d)
    bodies = repair_idats(d)

    png = SIG + make_chunk(b"IHDR", ihdr)
    for body in bodies:
        png += make_chunk(b"IDAT", body)
    png += make_chunk(b"IEND", b"")                  # clean ending, drops any stray tail bytes
    open("repaired.png", "wb").write(png)
    print("\n[..] wrote repaired.png, now checking that the pixels decode")

    w, h, depth, ctype = struct.unpack(">IIBB", ihdr[:10])
    stride = 1 + (w * CHANNELS[ctype] * depth + 7) // 8
    joined = b"".join(bodies)
    try:
        raw = zlib.decompress(joined)
        print("[ok] zlib stream is clean (checksum passes)")
    except zlib.error as e:
        print("[!] zlib still complains:", e)
        raw = zlib.decompressobj(-15).decompress(joined[2:])   # skip the checksum, see what comes out

    rows = len(raw) / stride
    print(f"     decoded {rows:.1f} rows, header expects {h}")
    if abs(rows - h) < 0.01:
        print("\nLooks good. Open repaired.png, the flag is in the bottom rows.")
    else:
        print("\nRow count is off, so something else is still broken. Compare the "
              "chunk report above with the file in a hex editor.")

    # bonus: crop and enlarge the bottom strip so the text is easy to read
    try:
        from PIL import Image
        im = Image.open("repaired.png").convert("RGB")
        strip = im.crop((0, max(0, h - 120), w, h))
        strip.resize((strip.width * 2, strip.height * 2)).save("bottom_strip.png")
        print("saved bottom_strip.png (the last 120 rows, 2x bigger)")
    except Exception:
        print("(install Pillow with `pip install pillow` if you want an auto-cropped bottom strip)")


if __name__ == "__main__":
    main()
