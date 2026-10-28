# SPDX-License-Identifier: GPL-3.0-or-later
"""Raw LZMA1 (lc=3, lp=0, pb=2) encoder whose output size can be raised.

The game rejected zero padding after a stream inside an IGA block's declared
length. To keep each recompressed block ending at its original boundary, a block
that shrinks past an alignment unit gets a stream that is genuinely longer. This encoder only chooses a less efficient parse (shorter
matches); the decoded bytes are identical. Streams carry no end marker, like
the original archive streams; the decoded size is known from the archive.
"""
import lzma
import random

_LC, _PB = 3, 2
_NUM_STATES = 12
_MAX_LEN = 273
_PROB_INIT = 1024


class _Range:
    def __init__(self):
        self.low, self.range, self.cache, self.cache_size, self.out = 0, 0xFFFFFFFF, 0, 1, bytearray()

    def _shift_low(self):
        if self.low < 0xFF000000 or self.low > 0xFFFFFFFF:
            carry, temp = self.low >> 32, self.cache
            while True:
                self.out.append((temp + carry) & 0xFF)
                temp = 0xFF
                self.cache_size -= 1
                if not self.cache_size:
                    break
            self.cache = (self.low >> 24) & 0xFF
        self.cache_size += 1
        self.low = (self.low & 0x00FFFFFF) << 8

    def bit(self, probs, index, bit):
        probability = probs[index]
        bound = (self.range >> 11) * probability
        if bit:
            self.low += bound
            self.range -= bound
            probs[index] = probability - (probability >> 5)
        else:
            self.range = bound
            probs[index] = probability + ((2048 - probability) >> 5)
        while self.range < 1 << 24:
            self.range <<= 8
            self._shift_low()

    def direct(self, value, count):
        for shift in range(count - 1, -1, -1):
            self.range >>= 1
            if value >> shift & 1:
                self.low += self.range
            while self.range < 1 << 24:
                self.range <<= 8
                self._shift_low()

    def tree(self, probs, base, count, value):
        index = 1
        for shift in range(count - 1, -1, -1):
            bit = value >> shift & 1
            self.bit(probs, base + index, bit)
            index = index << 1 | bit

    def reverse_tree(self, probs, base, count, value):
        index = 1
        for _ in range(count):
            bit = value & 1
            self.bit(probs, base + index, bit)
            index = index << 1 | bit
            value >>= 1

    def finish(self):
        for _ in range(5):
            self._shift_low()
        return bytes(self.out)


class _Length:
    def __init__(self):
        self.choice = [_PROB_INIT] * 2
        self.low = [_PROB_INIT] * (16 << 3)
        self.mid = [_PROB_INIT] * (16 << 3)
        self.high = [_PROB_INIT] * 256

    def encode(self, rc, length, pos_state):
        length -= 2
        if length < 8:
            rc.bit(self.choice, 0, 0)
            rc.tree(self.low, pos_state << 3, 3, length)
        elif length < 16:
            rc.bit(self.choice, 0, 1)
            rc.bit(self.choice, 1, 0)
            rc.tree(self.mid, pos_state << 3, 3, length - 8)
        else:
            rc.bit(self.choice, 0, 1)
            rc.bit(self.choice, 1, 1)
            rc.tree(self.high, 0, 8, length - 16)


def _distance_slot(distance):
    if distance < 4:
        return distance
    bits = distance.bit_length() - 1
    return 2 * bits + (distance >> (bits - 1) & 1)


def encode(data, dict_size, noise=0.0, seed=0):
    """Greedy-parse encode. With probability `noise` per step, a seeded choice
    replaces the greedy one (a random earlier match and shorter length, or a
    literal); varied choices stay costly where repetition would adapt away."""
    data = bytes(data)
    size = len(data)
    rng = random.Random(seed)
    rc = _Range()
    is_match = [_PROB_INIT] * (_NUM_STATES << 4)
    is_rep = [_PROB_INIT] * _NUM_STATES
    literal = [_PROB_INIT] * (0x300 << _LC)
    slots = [_PROB_INIT] * (4 << 6)
    special = [_PROB_INIT] * (128 - 14)
    align = [_PROB_INIT] * 16
    lengths = _Length()
    state, rep0, previous = 0, 0, 0
    chains = {}
    pos = 0

    def insert(at):
        if at + 3 <= size:
            key = data[at:at + 3]
            chain = chains.setdefault(key, [])
            chain.append(at)
            if len(chain) > 24:
                del chain[0]

    while pos < size:
        matches = []
        if pos + 3 <= size:
            for candidate in reversed(chains.get(data[pos:pos + 3], ())):
                distance = pos - candidate
                if distance > dict_size:
                    break
                length = 3
                limit = min(_MAX_LEN, size - pos)
                while length < limit and data[candidate + length] == data[pos + length]:
                    length += 1
                matches.append((length, distance))
        best_length, best_distance = max(matches) if matches else (0, 0)
        if noise and rng.random() < noise:
            if matches and rng.random() < 0.6:
                length, best_distance = rng.choice(matches)
                best_length = rng.randint(3, min(length, 12)) if length > 3 else 3
            else:
                best_length = 0
        pos_state = pos & ((1 << _PB) - 1)
        if best_length >= 2:
            rc.bit(is_match, (state << 4) + pos_state, 1)
            rc.bit(is_rep, state, 0)
            lengths.encode(rc, best_length, pos_state)
            distance = best_distance - 1
            slot = _distance_slot(distance)
            rc.tree(slots, min(best_length - 2, 3) << 6, 6, slot)
            if slot >= 4:
                footer = (slot >> 1) - 1
                base = (2 | (slot & 1)) << footer
                reduced = distance - base
                if slot < 14:
                    rc.reverse_tree(special, base - slot - 1, footer, reduced)
                else:
                    rc.direct(reduced >> 4, footer - 4)
                    rc.reverse_tree(align, 0, 4, reduced & 15)
            rep0 = distance
            state = 7 if state < 7 else 10
            for at in range(pos, pos + best_length):
                insert(at)
            pos += best_length
            previous = data[pos - 1]
            continue
        rc.bit(is_match, (state << 4) + pos_state, 0)
        base = 0x300 * (previous >> (8 - _LC))
        symbol = data[pos] | 0x100
        if state < 7:
            rc.tree(literal, base, 8, data[pos])
        else:
            match_byte = data[pos - rep0 - 1]
            offset = 0x100
            while symbol < 0x10000:
                match_byte <<= 1
                rc.bit(literal, base + offset + (match_byte & offset) + (symbol >> 8), (symbol >> 7) & 1)
                symbol <<= 1
                offset &= ~(match_byte ^ symbol)
        state = 0 if state < 4 else state - 3 if state < 10 else state - 6
        previous = data[pos]
        insert(pos)
        pos += 1
    return rc.finish()


def _verify(stream, data, dict_size):
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[dict(
        id=lzma.FILTER_LZMA1, dict_size=dict_size, lc=_LC, lp=0, pb=_PB)])
    if decoder.decompress(stream, max_length=len(data)) != data:
        raise ValueError('filled LZMA stream does not decode to the block')
    return stream


def fill(data, dict_size, minimum, maximum):
    """Return a verified stream with minimum <= length <= maximum."""
    if minimum > maximum:
        raise ValueError('empty LZMA size window')
    stream = encode(data, dict_size)
    if len(stream) > maximum:
        raise ValueError('block does not fit its allocation')
    if len(stream) >= minimum:
        return _verify(stream, data, dict_size)
    if len(encode(data, dict_size, 1.0)) < minimum:
        raise ValueError('block cannot be encoded large enough for its allocation')
    low, high = 0.0, 1.0  # the output grows with noise
    for _ in range(30):
        noise = (low + high) / 2
        stream = encode(data, dict_size, noise)
        if len(stream) < minimum:
            low = noise
        elif len(stream) > maximum:
            high = noise
        else:
            return _verify(stream, data, dict_size)
    raise ValueError('block cannot be encoded within its allocation window')
