import base64
import json
import sys
import unittest
import zlib
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[1] / "agent"
sys.path.insert(0, str(AGENT_ROOT))

from services.encode_config import encode_payload


class EncodeConfigTest(unittest.TestCase):
    def test_omits_disabled_sessions_from_season_definition(self):
        _, encoded_season = encode_payload({
            "Server": {
                "TcpPort": 9600,
                "UdpPort": 9600,
                "HttpPort": 8081,
                "ServerName": "Contract test",
                "MaxPlayers": 20,
                "IsCycleEnabled": False,
                "DriverPassword": "",
                "SpectatorPassword": "",
                "AdminPassword": "",
                "SelectedServerTypeValue": "MultiplayerServerListSessionType_RANKED",
            },
            "Event": {
                "SelectedSessionTypeValue": "GameModeType_RACE_WEEKEND",
                "SelectedWeatherTypeValue": "WeatherType_Clear",
                "SelectedWeatherBehaviorValue": "WeatherBehavior_Static",
                "SelectedInitialGripValue": "TrackGripValue_Optimum",
                "SelectedTrackValue": "Track|Layout|Event|5000",
                "Cars": [{"name": "car", "IsSelected": True}],
            },
            "Sessions": {
                "PracticeSession": self.session(1, 10, True),
                "QualifyingSession": self.session(2, 120, False),
                "WarmupSession": self.session(3, 30, False),
                "RaceSession": self.session(4, 60, True),
            },
        })

        season = self.decode(encoded_season)
        game_config = season["game_config"]

        self.assertEqual(10, game_config["practice_duration"])
        self.assertEqual(60, game_config["race_duration"])
        self.assertNotIn("qualify_duration", game_config)
        self.assertNotIn("qualify_time_of_day", game_config)
        self.assertNotIn("warmup_duration", game_config)
        self.assertNotIn("warmup_time_of_day", game_config)

    @staticmethod
    def session(order, length, visible):
        return {
            "Order": order,
            "Length": length,
            "Hour": 13,
            "Minute": 0,
            "OvertimeWaitingNextSession": 10,
            "MaxWaitToBox": 10,
            "MinWaitingForPlayers": 10,
            "MaxWaitingForPlayers": 30,
            "IsVisible": visible,
        }

    @staticmethod
    def decode(encoded):
        payload = base64.b64decode(encoded)

        return json.loads(zlib.decompress(payload[4:]).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
