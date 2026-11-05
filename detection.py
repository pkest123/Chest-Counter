"""Pure event logic; independent of capture and UI."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Notification:
    bounds: tuple
    confidence: float


def normalize(text):
    text = re.sub(r'(?<=\d)[,.](?=\d)', '', text.upper())
    text = re.sub(r'\bCHE5T(?=\b|SEARCHED|OPENED)', 'CHEST', text)
    text = re.sub(r'\bX\s+P\b', 'XP', text)
    text = re.sub(r'CHEST(SEARCHED|OPENED)', r'CHEST \1', text)
    text = re.sub(r'(SEARCHED|OPENED)CHEST', r'\1 CHEST', text)
    return ' '.join(re.sub(r'[^A-Z0-9+ ]', ' ', text).split())


def bounds(box):
    xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
    return min(xs), min(ys), max(xs), max(ys)


def nearby(a, b, horizontal=8, vertical=4):
    height = max(a[3]-a[1], b[3]-b[1], 8)
    return max(0, a[0]-b[2], b[0]-a[2]) <= height*horizontal and max(0, a[1]-b[3], b[1]-a[3]) <= height*vertical


def union(a, b):
    return min(a[0],b[0]), min(a[1],b[1]), max(a[2],b[2]), max(a[3],b[3])


def locate_notifications(rows):
    """Locate completion text, or a chest label with spatially adjacent XP.

    Interaction prompts, progress/quest sentences and generic container toasts
    are deliberately excluded. Explicit past-tense completion text does not
    require a separately recognized XP amount.
    """
    labels, xp, numbers, xp_only, found, fragments = [], [], [], [], [], []
    amount = re.compile(r'(?:\+?\s*\d+\s*K?\s*XP\b|\bXP\s*\+?\s*\d+\s*K?)')
    completion = r'(?:(?:RARE|LEGENDARY|EPIC) )?CHEST (?:SEARCHED|OPENED)|(?:SEARCHED|OPENED) (?:A )?(?:(?:RARE|LEGENDARY|EPIC) )?CHEST'
    for box, text, confidence in rows:
        if confidence < .65:
            continue
        line, rect = normalize(text), bounds(box)
        fragments.append((line,rect,confidence))
        stripped = amount.sub('', line).strip()
        explicit = bool(re.fullmatch(completion, stripped))
        is_chest = explicit or bool(re.fullmatch(r'(?:(?:RARE|LEGENDARY|EPIC) )?CHEST', stripped))
        if explicit and confidence >= .80:
            found.append(Notification(rect, confidence))
        elif is_chest:
            if amount.search(line):
                found.append(Notification(rect, confidence))
            else:
                labels.append((rect, confidence))
        if amount.fullmatch(line):
            xp.append((rect, confidence))
        elif line == 'XP':
            xp_only.append((rect, confidence))
        elif re.fullmatch(r'\+?\s*\d+\s*K?', line):
            numbers.append((rect, confidence))
    for word, confidence in xp_only:
        for number, number_confidence in numbers:
            if nearby(word, number, 4, 2):
                xp.append((union(word, number), min(confidence, number_confidence)))
    for text, rect, confidence in fragments:
        if not re.fullmatch(r'(?:(?:RARE|LEGENDARY|EPIC) )?CHEST',text):
            continue
        for word, word_rect, word_confidence in fragments:
            if word in ('SEARCHED','OPENED') and min(confidence,word_confidence)>=.80 and nearby(rect,word_rect,3,2):
                found.append(Notification(union(rect,word_rect),min(confidence,word_confidence)))
    for label, confidence in labels:
        for points, xp_confidence in xp:
            if nearby(label, points):
                found.append(Notification(union(label, points), min(confidence, xp_confidence)))
    return found


def automatic_notification(rows):
    """English chest completion label near XP; reject search prompts/quests.

    OCR rows: (four-point polygon, text, confidence). Proximity is relative to
    text height so detection works at different capture resolutions.
    """
    return bool(locate_notifications(rows))


def chest_notification(lines, phrase):
    """Require the configured completion phrase, never the interaction prompt."""
    normalize = lambda s: re.sub(r'[^A-Z0-9 ]', ' ', s.upper())
    target = ' '.join(normalize(phrase).split())
    if not target:
        return False
    for text, confidence in lines:
        line = ' '.join(normalize(text).split())
        if confidence >= .65 and re.search(r'\b' + re.escape(target) + r'\b', line):
            return True
    return False


class EventGate:
    """One event per appearance, plus shared cooldown across detection modes."""
    def __init__(self, cooldown=3.0, clear_time=.8):
        self.cooldown = cooldown
        self.clear_time = clear_time
        self.last = -float('inf')
        self.latched = {}
        self.absent = {}

    def update(self, signals, now):
        rising = []
        for key, active in signals.items():
            if active:
                # A single observed clear frame followed by a sufficiently long
                # gap can rearm, even if slow OCR did not sample a second blank.
                if key in self.absent and now-self.absent[key] >= self.clear_time:
                    self.latched[key] = False
                self.absent.pop(key, None)
                if not self.latched.get(key, False):
                    rising.append(key)
                self.latched[key] = True
            else:
                self.absent.setdefault(key, now)
                if now - self.absent[key] >= self.clear_time:
                    self.latched[key] = False
        if rising and now - self.last >= self.cooldown:
            self.last = now
            return rising[0]
        return None
