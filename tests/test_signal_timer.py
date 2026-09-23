import unittest
from unittest.mock import patch

import app as server


class SignalTimerTest(unittest.TestCase):
    def setUp(self):
        server.game.reset()
        server.game.active = True
        server.game.round_id += 1
        server.game.mr_x = 'mrx'
        server.game.update_interval_minutes = 5
        server.game.players['mrx'] = server.PlayerState(sid='')
        self.now = 1000.0
        self.events = []
        self.tasks = []
        self.time_patch = patch.object(server.time, 'time', side_effect=lambda: self.now)
        self.emit_patch = patch.object(server.socketio, 'emit', side_effect=lambda name, payload, **kwargs: self.events.append((name, payload)))
        self.task_patch = patch.object(server.socketio, 'start_background_task', side_effect=lambda target, *args, **kwargs: self.tasks.append((target, args)))
        self.time_patch.start()
        self.emit_patch.start()
        self.task_patch.start()
        self.addCleanup(self.time_patch.stop)
        self.addCleanup(self.emit_patch.stop)
        self.addCleanup(self.task_patch.stop)
        self.addCleanup(server.game.reset)

    def test_decoy_and_next_real_signal_fire_without_new_location(self):
        server.publish_location('mrx', 52.5, 13.4)
        self.assertEqual(len(self.tasks), 1)
        result, error = server.set_decoy_for('mrx', {'lat': 52.6, 'lon': 13.5})
        self.assertIsNone(error)
        self.assertEqual(result['remaining_decoys'], 0)
        self.now = 1299.0
        self.assertFalse(server.broadcast_mrx_location_if_due())

        sleeps = 0

        def advance(seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 3:
                raise StopIteration
            self.now += seconds

        with patch.object(server.socketio, 'sleep', side_effect=advance):
            with self.assertRaises(StopIteration):
                target, args = self.tasks[0]
                target(*args)

        updates = [payload for name, payload in self.events if name == 'location_update']
        self.assertEqual([(item['lat'], item['lon']) for item in updates],
                         [(52.5, 13.4), (52.6, 13.5), (52.5, 13.4)])
        self.assertTrue(updates[-1]['previous_was_decoy'])
        self.assertEqual(server.game.mr_x_last_broadcast_time, 1600.0)
        self.assertEqual(len([name for name, _ in self.events if name == 'mrx_update_timer']), 3)

    def test_old_timer_does_not_emit_in_a_new_round(self):
        server.publish_location('mrx', 52.5, 13.4)
        target, args = self.tasks[0]
        server.game.round_id += 1
        server.game.mr_x_last_broadcast_time = 0
        self.events.clear()
        target(*args)
        self.assertEqual(self.events, [])

    def test_invisibility_response_contains_expiration(self):
        server.game.players['seeker'] = server.PlayerState(sid='')
        result, error = server.activate_invisibility_for('seeker')
        self.assertIsNone(error)
        self.assertEqual(result['invisible_until'], 1030.0)
        self.assertEqual(result['remaining_uses'], 1)


if __name__ == '__main__':
    unittest.main()
