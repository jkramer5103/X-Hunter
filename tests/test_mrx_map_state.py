import unittest
from unittest.mock import patch

import app as server


class MrXMapStateTest(unittest.TestCase):
    def setUp(self):
        server.game.reset()
        server.game.active = True
        server.game.mr_x = 'mrx'
        server.game.players = {
            'mrx': server.PlayerState(sid=''),
            'seeker': server.PlayerState(sid=''),
        }
        server.game.mr_x_last_known_location = {'lat': 52.5, 'lon': 13.4}
        server.game.mr_x_public_location = {'lat': 52.6, 'lon': 13.5}
        server.game.mrx_last_update_was_decoy = True
        self.addCleanup(server.game.reset)

    def test_native_state_separates_real_and_public_for_mrx(self):
        with patch.object(server, 'native_user', return_value='mrx'), patch.object(server.user_repo, 'get_user', return_value={'is_admin': False}):
            response = server.app.test_client().get('/api/native/state')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['locations']['mrx'], {'lat': 52.6, 'lon': 13.5})
        self.assertEqual(response.json['mr_x_real_location'], {'lat': 52.5, 'lon': 13.4})
        self.assertTrue(response.json['mr_x_public_is_decoy'])

    def test_native_state_never_sends_real_location_to_seeker(self):
        with patch.object(server, 'native_user', return_value='seeker'), patch.object(server.user_repo, 'get_user', return_value={'is_admin': False}):
            response = server.app.test_client().get('/api/native/state')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['locations']['mrx'], {'lat': 52.6, 'lon': 13.5})
        self.assertIsNone(response.json['mr_x_real_location'])
        self.assertFalse(response.json['mr_x_public_is_decoy'])

    def test_socket_snapshot_uses_public_marker_for_mrx(self):
        with patch.object(server, 'current_user', return_value='mrx'):
            client = server.socketio.test_client(server.app)
        try:
            updates = [event['args'][0] for event in client.get_received() if event['name'] == 'game_update']
            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0]['locations']['mrx'], {'lat': 52.6, 'lon': 13.5})
            self.assertEqual(updates[0]['mr_x_real_location'], {'lat': 52.5, 'lon': 13.4})
            self.assertTrue(updates[0]['mr_x_public_is_decoy'])
        finally:
            client.disconnect()


if __name__ == '__main__':
    unittest.main()
