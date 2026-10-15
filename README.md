# Corrupted PNG Steganography Challenge: Writeup

**Category:** Forensics / Steganography
**Tools:** hexed.it, Python (zlib, struct), Aperi'Solve, Google Colab

## Summary
The PNG would not render correctly. Two things were tampered with:
1. The IHDR height was altered (800 instead of 850), hiding the bottom 50 rows.
2. 12 junk bytes were inserted into the middle of IDAT chunk #3 without
   updating the chunk length, breaking the zlib stream and the chunk CRC.

## Solution
1. Verified the PNG signature (89 50 4E 47 0D 0A 1A 0A).
2. Brute-forced the IHDR height against its stored CRC; the match was 850 (0x352).
3. Walked the chunks and checked each CRC; IDAT #3 failed.
4. Aperi'Solve's zsteg output flagged 12 extra bytes near that chunk.
5. Searched for the 12-byte removal that reproduces the stored CRC, then
   rebuilt the file and decompressed all 850 rows.
6. The flag was drawn in the bottom rows of the repaired image.

## Flag
flag{g0t_1t_in_pLAin_sight}

## Files
- solve.py: repair script
- fixed5.png: fixed image

## What I learned
A broken checksum points to where the tampering is. Insertions break
deflate streams in ways that look like image noise.
