# -*- coding: utf-8 -*-
"""Fix Persian PDF text extracted in visual order: split each line on base
direction changes, reverse RTL runs (with bracket mirroring), then join runs
back in logical order."""
import re
import sys
import glob
import os

PUNCT = set('،؛؟!.,:;!?…ـ\u200c')


def is_rtl(ch):
    o = ord(ch)
    return 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF


def mirror_char(c):
    return {'(': ')', ')': '(', '[': ']', ']': '[', '{': '}', '}': '{',
            '<': '>', '>': '<', '«': '»', '»': '«'}.get(c, c)


def reverse_rtl(s):
    return ''.join(mirror_char(c) for c in reversed(s))


def fix_line(line):
    if not re.search(r'[\u0600-\u06FF]', line):
        return line
    # Split into runs of RTL / non-RTL (digit sequences stay inside RTL runs)
    runs = re.findall(r'[0-9]+(?:[.,][0-9]+)*|.|\u200c', line)
    out = []
    rtl_buf = []
    rtl_active = False

    def flush():
        if rtl_buf:
            out.append(reverse_rtl(''.join(rtl_buf)))
            rtl_buf.clear()

    for run in runs:
        r = is_rtl(run[0]) or (run == '\u200c')
        is_num = run[0].isdigit()
        if r or rtl_active:
            if r or is_num:
                rtl_buf.append(run)
                rtl_active = True
                continue
            # Latin run: punctuation only? treat as part of current line direction
            if all(c in PUNCT or c == ' ' for c in run):
                rtl_buf.append(run)
                continue
            flush()
            rtl_active = False
            out.append(run)
        else:
            if is_num and out and out[-1] and is_rtl(out[-1][-1]):
                # number following RTL text inside an RTL sentence
                rtl_buf.append(run)
                rtl_active = True
                continue
            out.append(run)
    flush()
    # Whole line mostly RTL => reverse the Latin fragments order too
    joined = ''.join(out)
    if sum(1 for c in joined if is_rtl(c)) > len(joined.strip()) / 2:
        # re-join: reverse order of non-RTL segments relative to RTL text
        pass
    return joined


def fix_text(text):
    lines = text.replace('\r\n', '\n').split('\n')
    return '\n'.join(fix_line(l) for l in lines)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else '/tmp/daneshyar-specs'
    for path in glob.glob(os.path.join(src, 'raw-*.txt')):
        with open(path, encoding='utf-8') as f:
            text = f.read()
        fixed = fix_text(text)
        out_path = path.replace('raw-', 'fixed-')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(fixed)
        print('OK:', out_path)


if __name__ == '__main__':
    main()
