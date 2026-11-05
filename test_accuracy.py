import unittest
from detection import EventGate, automatic_notification, locate_notifications
from notification_focus import focus_box


def row(text,x=100,y=100,confidence=.98):
    return ([[x,y],[x+160,y],[x+160,y+20],[x,y+20]],text,confidence)


class AccuracyTests(unittest.TestCase):
    def test_completion_variations_and_split_xp(self):
        for text in ('CHEST SEARCHED','CHESTOPENED','SEARCHED A RARE CHEST','100 XP CHE5T','XP +100 CHEST'):
            self.assertTrue(automatic_notification([row(text)]),text)
        self.assertTrue(automatic_notification([row('CHEST',100,140),row('XP',160,110),row('+100',100,110)]))
        self.assertTrue(automatic_notification([row('CHEST',100,100),row('SEARCHED',270,100)]))

    def test_no_interaction_quest_or_sprite_false_positives(self):
        for text in ('SEARCH','OPEN CHEST','Search chests 1/10','43/50 Open Rare Chests',
                     'CHEST SEARCHED 3/10','CONTAINER OPENED','+75 CONTAINER OPENED'):
            self.assertFalse(automatic_notification([row(text),row('+100 XP',100,70)]),text)
        self.assertFalse(automatic_notification([row('CHEST')]))
        self.assertFalse(automatic_notification([row('CHEST SEARCHED',confidence=.7)]))

    def test_fast_consecutive_notifications_count_once_each(self):
        gate=EventGate(cooldown=.35,clear_time=.30)
        self.assertEqual(gate.update({'notification':True},0),'notification')
        self.assertIsNone(gate.update({'notification':True},.2))
        gate.update({'notification':False},.4)
        gate.update({'notification':False},.6)
        self.assertEqual(gate.update({'notification':True},.8),'notification')
        self.assertIsNone(gate.update({'notification':True},1))

    def test_single_slow_clear_sample_rearms_without_second_blank(self):
        gate=EventGate()
        gate.update({'notification':True},0)
        gate.update({'notification':False},2)
        self.assertEqual(gate.update({'notification':True},4),'notification')

    def test_brief_ocr_flicker_does_not_recount_lingering_toast(self):
        gate=EventGate(cooldown=.35,clear_time=.30)
        gate.update({'notification':True},0)
        gate.update({'notification':False},.2)
        self.assertIsNone(gate.update({'notification':True},.4))
        self.assertIsNone(gate.update({'notification':True},3))

    def test_focus_uses_scaled_coordinates_and_stays_on_display(self):
        items=locate_notifications([row('CHEST SEARCHED',1800,1000)])
        box=focus_box(items,1920,1080,2560,1440)
        self.assertIsNotNone(box)
        self.assertLessEqual(box[0],1800*2560/1920)
        self.assertLessEqual(box[2],2560)
        self.assertLessEqual(box[3],1440)


if __name__=='__main__':unittest.main()
