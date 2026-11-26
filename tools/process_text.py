# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode a child process's output as UTF-8 across reads.

Output arrives in arbitrary chunks, so a character can be split between two
reads; decoding each chunk alone turns it into U+FFFD. One incremental decoder
per process keeps characters whole."""
import codecs


def utf8_reader(_owner, process):
    """The UTF-8 decoder kept on this QProcess (created on first use)."""
    decoder = getattr(process, '_utf8_decoder', None)
    if decoder is None:
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        process._utf8_decoder = decoder
    return decoder
