import base64
import json
import sys
import unittest
import zlib
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[1] / "agent"
sys.path.insert(0, str(AGENT_ROOT))

from services.encode_config import encode_payload


def decode_config(encoded: str) -> tuple[int, dict]:
    payload = base64.b64decode(encoded)
    declared_length = int.from_bytes(payload[:4], byteorder="big")
    json_bytes = zlib.decompress(payload[4:])

    return declared_length, json.loads(json_bytes.decode("utf-8"))


class EncodeConfigTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "Server": {
                "TcpPort": 9600,
                "UdpPort": 9600,
                "HttpPort": 8081,
                "ServerName": "PitLane test",
                "MaxPlayers": 24,
                "IsCycleEnabled": False,
                "DriverPassword": "driver",
                "SpectatorPassword": "spectator",
                "AdminPassword": "admin",
                "SelectedServerTypeValue": "Race",
                "SelectedTuningTypeValue": "TuningDenied",
            },
            "Event": {
                "Cars": [
                    {"name": "Alpine A110 EVO", "IsSelected": True},
                    {"name": "Porsche 911 GT3 Cup", "IsSelected": False},
                ],
                "SelectedTrackValue": "Spa|Grand Prix|Test event|7004",
                "SelectedSessionTypeValue": "RaceWeekend",
                "SelectedWeatherTypeValue": "Clear",
                "SelectedWeatherBehaviorValue": "Static",
                "SelectedInitialGripValue": "Optimum",
            },
            "Sessions": {
                "PracticeSession": self.session(order=1, time_multiplier=1),
                "QualifyingSession": self.session(order=2, time_multiplier=12),
                "WarmupSession": self.session(order=3, time_multiplier=28),
                "RaceSession": self.session(order=4, time_multiplier=48),
            },
        }

    @staticmethod
    def session(order: int, time_multiplier: int) -> dict:
        return {
            "Order": order,
            "Length": 20,
            "Hour": 14,
            "Minute": 30,
            "TimeMultiplier": time_multiplier,
            "OvertimeWaitingNextSession": 60,
            "MaxWaitToBox": 120,
            "MinWaitingForPlayers": 10,
            "MaxWaitingForPlayers": 30,
        }

    def test_encodes_each_session_time_multiplier(self):
        _, season_definition = decode_config(encode_payload(self.config)[1])
        game_config = season_definition["game_config"]

        self.assertEqual(1, game_config["practice_time_of_day"]["time_multiplier"])
        self.assertEqual(12, game_config["qualify_time_of_day"]["time_multiplier"])
        self.assertEqual(28, game_config["warmup_time_of_day"]["time_multiplier"])
        self.assertEqual(48, game_config["race_time_of_day"]["time_multiplier"])

    def test_defaults_time_multiplier_to_one_for_legacy_payloads(self):
        del self.config["Sessions"]["PracticeSession"]["TimeMultiplier"]

        _, season_definition = decode_config(encode_payload(self.config)[1])

        self.assertEqual(
            1,
            season_definition["game_config"]["practice_time_of_day"]["time_multiplier"],
        )

    def test_omits_mandatory_pitstop_fields_when_rule_is_off(self):
        _, season_definition = decode_config(encode_payload(self.config)[1])

        self.assertNotIn("mandatory_pit_stop", season_definition["game_config"])
        self.assertNotIn("requires_tyre_change", season_definition["game_config"])
        self.assertNotIn("requires_refuelling", season_definition["game_config"])
        self.assertNotIn("pit_window", season_definition["game_config"])

    def test_maps_mandatory_pitstop_to_native_acevo_fields(self):
        self.config["Sessions"]["RaceSession"]["MandatoryPitStop"] = {
            "RequiresTyreChange": True,
            "RequiresRefuelling": False,
            "WindowDurationSeconds": 600,
        }

        _, season_definition = decode_config(encode_payload(self.config)[1])

        self.assertEqual(
            {
                "mandatory_pit_stop": True,
                "requires_tyre_change": True,
                "requires_refuelling": False,
                "pit_window": 600,
            },
            {
                key: season_definition["game_config"][key]
                for key in (
                    "mandatory_pit_stop",
                    "requires_tyre_change",
                    "requires_refuelling",
                    "pit_window",
                )
            },
        )

if __name__ == "__main__":
    unittest.main()
