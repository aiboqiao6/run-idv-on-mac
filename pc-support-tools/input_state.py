"""Validate native snapshots and produce Windows VK transitions in chord order."""


class InputState:
    MODIFIERS = frozenset((16, 17, 18, 91, 92))

    def __init__(self):
        self.keys = set()
        self.seq = -1

    def release(self):
        events = [(5, k) for k in sorted(self.keys, key=lambda k: (k in self.MODIFIERS, k))]
        self.keys.clear()
        return events

    def update(self, frame):
        if not isinstance(frame, dict):
            raise ValueError('snapshot must be an object')
        seq, active, keys = frame.get('seq'), frame.get('active'), frame.get('keys')
        if type(seq) is not int or seq < 0 or type(active) is not bool:
            raise ValueError('invalid sequence or focus state')
        if not isinstance(keys, list) or len(keys) > 256:
            raise ValueError('invalid key list')
        if any(type(k) is not int or not 1 <= k <= 255 for k in keys):
            raise ValueError('invalid virtual key')
        if seq <= self.seq:
            return []
        new = set(keys) if active else set()
        events = [(5, k) for k in sorted(self.keys - new, key=lambda k: (k in self.MODIFIERS, k))]
        events += [(4, k) for k in sorted(new - self.keys, key=lambda k: (k not in self.MODIFIERS, k))]
        self.keys, self.seq = new, seq
        return events
